"""
Script 6 - Congestion Generator and HTTPS-vs-HTTP Comparator

Creates sustained parallel traffic to both HTTP and HTTPS endpoints so QoS impact is
visible, then prints latency statistics and winner.

Run from a Client PC (not the Server PC):
    python scripts/congestion_test.py

Example:
    python scripts/congestion_test.py --duration 90 --concurrency 80 --priority https
"""

import argparse
import csv
import math
import os
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEFAULT_HTTP_URL = os.getenv("CCEN356_HTTP_URL", "http://192.165.20.79")
DEFAULT_HTTPS_URL = os.getenv("CCEN356_HTTPS_URL", "https://192.165.20.79")
QOS_HEADER = os.getenv("CCEN356_QOS_MODE_HEADER", "X-CCEN356-QOS-MODE")
QOS_VALUE = os.getenv("CCEN356_QOS_MODE_VALUE", "on")


def qos_headers_for_priority(priority_mode):
    """Return per-protocol headers based on requested priority direction."""
    mode = (priority_mode or "none").strip().lower()
    qos_header = {QOS_HEADER: QOS_VALUE}

    if mode == "https":
        # Keep legacy behavior: QoS header is sent on both protocols.
        return qos_header, qos_header
    if mode == "http":
        # Apply QoS header only on HTTPS requests so HTTP remains baseline.
        # If HTTPS server has a non-zero QoS delay configured, this makes HTTP win.
        return None, qos_header
    return None, None


class ProtocolStats:
    def __init__(self, name):
        self.name = name
        self.lock = threading.Lock()
        self.latencies_ms = []
        self.successes = 0
        self.errors = 0
        self.bytes_total = 0

    def add_success(self, latency_ms, bytes_count):
        with self.lock:
            self.latencies_ms.append(latency_ms)
            self.successes += 1
            self.bytes_total += bytes_count

    def add_error(self):
        with self.lock:
            self.errors += 1

    def snapshot(self, duration_sec):
        with self.lock:
            values = list(self.latencies_ms)
            successes = self.successes
            errors = self.errors
            bytes_total = self.bytes_total

        total = successes + errors
        error_rate = (errors / total * 100.0) if total else 0.0

        if values:
            avg_ms = statistics.mean(values)
            p95_ms = percentile(values, 95)
            p99_ms = percentile(values, 99)
            min_ms = min(values)
            max_ms = max(values)
            stdev_ms = statistics.stdev(values) if len(values) > 1 else 0.0
        else:
            avg_ms = p95_ms = p99_ms = min_ms = max_ms = stdev_ms = 0.0

        throughput_kbps = (bytes_total / 1024.0) / duration_sec if duration_sec > 0 else 0.0

        return {
            "protocol": self.name,
            "duration_sec": round(duration_sec, 2),
            "successes": successes,
            "errors": errors,
            "error_rate_pct": round(error_rate, 2),
            "avg_ms": round(avg_ms, 2),
            "p95_ms": round(p95_ms, 2),
            "p99_ms": round(p99_ms, 2),
            "min_ms": round(min_ms, 2),
            "max_ms": round(max_ms, 2),
            "stdev_ms": round(stdev_ms, 2),
            "throughput_kbps": round(throughput_kbps, 2),
            "samples": len(values),
        }


def percentile(values, p):
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]

    rank = (len(ordered) - 1) * (p / 100.0)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return ordered[lower]

    lower_weight = upper - rank
    upper_weight = rank - lower
    return (ordered[lower] * lower_weight) + (ordered[upper] * upper_weight)


def worker(url, verify_tls, timeout_sec, headers, stop_event, stats):
    session = requests.Session()
    while not stop_event.is_set():
        start = time.perf_counter()
        try:
            response = session.get(url, timeout=timeout_sec, verify=verify_tls, headers=headers)
            latency_ms = (time.perf_counter() - start) * 1000.0
            stats.add_success(latency_ms, len(response.content))
        except Exception:
            stats.add_error()



def run_test(http_url, https_url, duration_sec, concurrency, timeout_sec, priority_mode):
    # Split workers evenly so both protocols are stressed at the same time.
    http_workers = max(1, concurrency // 2)
    https_workers = max(1, concurrency - http_workers)

    http_headers, https_headers = qos_headers_for_priority(priority_mode)

    http_stats = ProtocolStats("HTTP")
    https_stats = ProtocolStats("HTTPS")

    stop_event = threading.Event()
    futures = []

    print("\nStarting congestion test")
    print("-" * 60)
    print(f"HTTP URL      : {http_url}")
    print(f"HTTPS URL     : {https_url}")
    print(f"Duration      : {duration_sec}s")
    print(f"Concurrency   : {concurrency} (HTTP {http_workers}, HTTPS {https_workers})")
    print(f"Request timeout: {timeout_sec}s")
    print(f"Priority mode : {priority_mode}")
    print(f"QoS on HTTP   : {'yes' if http_headers else 'no'}")
    print(f"QoS on HTTPS  : {'yes' if https_headers else 'no'}")

    start_time = time.perf_counter()

    with ThreadPoolExecutor(max_workers=http_workers + https_workers) as executor:
        for _ in range(http_workers):
            futures.append(
                executor.submit(
                    worker,
                    http_url,
                    False,
                    timeout_sec,
                    http_headers,
                    stop_event,
                    http_stats,
                )
            )
        for _ in range(https_workers):
            futures.append(
                executor.submit(
                    worker,
                    https_url,
                    False,
                    timeout_sec,
                    https_headers,
                    stop_event,
                    https_stats,
                )
            )

        time.sleep(duration_sec)
        stop_event.set()

        for future in futures:
            future.result()

    elapsed = time.perf_counter() - start_time

    http_result = http_stats.snapshot(elapsed)
    https_result = https_stats.snapshot(elapsed)

    return http_result, https_result


def print_summary(http_result, https_result):
    print("\nResults")
    print("-" * 60)
    for result in (http_result, https_result):
        print(
            f"{result['protocol']:<6} | avg {result['avg_ms']:>7} ms | "
            f"p95 {result['p95_ms']:>7} ms | p99 {result['p99_ms']:>7} ms | "
            f"ok {result['successes']:>6} | err {result['errors']:>5} | "
            f"err% {result['error_rate_pct']:>6} | KB/s {result['throughput_kbps']:>8}"
        )

    if http_result["avg_ms"] == 0 and https_result["avg_ms"] == 0:
        winner = "N/A"
    else:
        winner = "HTTPS" if https_result["avg_ms"] < http_result["avg_ms"] else "HTTP"

    delta = round(https_result["avg_ms"] - http_result["avg_ms"], 2)
    print("\nComparison")
    print("-" * 60)
    print(f"Faster protocol (avg latency): {winner}")
    print(f"Delta (HTTPS - HTTP): {delta} ms")
    print("Tip: verify QoS counters on R1 with 'show policy-map interface gi0/0'.")


def save_csv(http_result, https_result, output_file):
    rows = [http_result, https_result]
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)



def main():
    parser = argparse.ArgumentParser(
        description="Generate sustained HTTP/HTTPS load and compare latency under congestion."
    )
    parser.add_argument("--http-url", default=DEFAULT_HTTP_URL, help="HTTP target URL")
    parser.add_argument("--https-url", default=DEFAULT_HTTPS_URL, help="HTTPS target URL")
    parser.add_argument("--duration", type=int, default=90, help="Test duration in seconds")
    parser.add_argument("--concurrency", type=int, default=80, help="Total concurrent workers")
    parser.add_argument("--timeout", type=float, default=2.0, help="Per-request timeout in seconds")
    parser.add_argument(
        "--priority",
        choices=("none", "http", "https"),
        default="none",
        help=(
            "Traffic-priority profile: 'https' sends QoS header on both protocols "
            "(legacy behavior), 'http' sends QoS header only on HTTPS requests, "
            "'none' sends no QoS header."
        ),
    )
    parser.add_argument(
        "--with-qos",
        action="store_true",
        help="Deprecated alias for --priority https",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(os.path.dirname(__file__), "..", "data", "congestion_results.csv"),
        help="CSV output path",
    )

    args = parser.parse_args()

    if args.with_qos and args.priority != "none":
        parser.error("Use either --with-qos or --priority, not both.")

    if args.with_qos:
        args.priority = "https"

    if args.concurrency < 2:
        raise ValueError("--concurrency must be at least 2")

    http_result, https_result = run_test(
        args.http_url,
        args.https_url,
        args.duration,
        args.concurrency,
        args.timeout,
        args.priority,
    )

    print_summary(http_result, https_result)
    save_csv(http_result, https_result, args.output)
    print(f"\nSaved results to: {os.path.abspath(args.output)}")


if __name__ == "__main__":
    main()
