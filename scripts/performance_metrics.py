"""
Script 3 - HTTP vs HTTPS Performance Benchmark.

Sends requests to both HTTP and HTTPS endpoints, then measures latency and
throughput. Target URLs can be supplied by CLI arguments or environment variables.
"""

import argparse
import requests
import time
import statistics
import csv
import os
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEFAULT_SERVER_HOST = os.getenv("CCEN356_SERVER_HOST", "192.165.20.79")
DEFAULT_HTTP_URL = os.getenv("CCEN356_HTTP_URL", f"http://{DEFAULT_SERVER_HOST}")
DEFAULT_HTTPS_URL = os.getenv("CCEN356_HTTPS_URL", f"https://{DEFAULT_SERVER_HOST}")
DEFAULT_REQUESTS = int(os.getenv("CCEN356_REQUESTS_PER_PROTOCOL", "50"))
DEFAULT_TIMEOUT_SEC = float(os.getenv("CCEN356_BENCHMARK_TIMEOUT_SEC", "10"))
DEFAULT_INTERVAL_SEC = float(os.getenv("CCEN356_BENCHMARK_INTERVAL_SEC", "0.1"))
DEFAULT_VERIFY_TLS = os.getenv("CCEN356_VERIFY_TLS", "false").strip().lower() in {"1", "true", "yes", "on"}


def percentile(values, p):
    """Return percentile with linear interpolation."""
    if not values:
        return 0.0

    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])

    rank = (len(ordered) - 1) * (p / 100.0)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return float(ordered[lower])

    weight = rank - lower
    return float((ordered[lower] * (1 - weight)) + (ordered[upper] * weight))


def average_jitter(values):
    """Return mean absolute delta between consecutive samples in milliseconds."""
    if len(values) < 2:
        return 0.0
    deltas = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    return float(sum(deltas) / len(deltas)) if deltas else 0.0


def measure_request(url, protocol_label, num_requests=50, timeout_sec=10, interval_sec=0.2, verify_tls=False):
    """Send multiple GET requests and collect performance metrics."""
    response_times = []
    errors = 0
    total_bytes = 0
    status_2xx = 0
    status_3xx = 0
    status_4xx = 0
    status_5xx = 0
    started_at = time.perf_counter()

    print(f"\nTesting {protocol_label} -> {url}")
    print("-" * 50)

    for i in range(num_requests):
        try:
            start = time.perf_counter()
            response = requests.get(url, timeout=timeout_sec, verify=verify_tls)
            elapsed = (time.perf_counter() - start) * 1000  # ms

            response_times.append(elapsed)
            total_bytes += len(response.content)
            code = int(response.status_code)
            if 200 <= code <= 299:
                status_2xx += 1
            elif 300 <= code <= 399:
                status_3xx += 1
            elif 400 <= code <= 499:
                status_4xx += 1
            elif code >= 500:
                status_5xx += 1
            print(f"  Request {i+1:02d}: {elapsed:.2f} ms | Status: {response.status_code}")
        except Exception as e:
            errors += 1
            print(f"  Request {i+1:02d}: ERROR - {e}")

        if interval_sec > 0:
            time.sleep(interval_sec)

    wall_time_s = time.perf_counter() - started_at
    successful_requests = len(response_times)
    completed_requests = successful_requests + errors

    if completed_requests > 0:
        avg_ms = statistics.mean(response_times) if response_times else 0.0
        min_ms = min(response_times) if response_times else 0.0
        max_ms = max(response_times) if response_times else 0.0
        stdev_ms = statistics.stdev(response_times) if len(response_times) > 1 else 0.0
        median_ms = statistics.median(response_times) if response_times else 0.0
        p25_ms = percentile(response_times, 25)
        p90_ms = percentile(response_times, 90)
        p95_ms = percentile(response_times, 95)
        p99_ms = percentile(response_times, 99)
        p75_ms = percentile(response_times, 75)
        iqr_ms = max(0.0, p75_ms - p25_ms)
        jitter_ms = average_jitter(response_times)

        # Keep the existing throughput_kbps field unchanged for compatibility.
        legacy_throughput = (
            (total_bytes / 1024) / (sum(response_times) / 1000)
            if response_times and sum(response_times) > 0
            else 0.0
        )

        metrics = {
            'protocol': protocol_label,
            'url': url,
            'requests': num_requests,
            'successful_requests': successful_requests,
            'errors': errors,
            'error_rate_%': round((errors / num_requests) * 100, 2),
            'success_rate_%': round((successful_requests / num_requests) * 100, 2),
            'status_2xx': status_2xx,
            'status_3xx': status_3xx,
            'status_4xx': status_4xx,
            'status_5xx': status_5xx,
            'avg_ms': round(avg_ms, 2),
            'median_ms': round(median_ms, 2),
            'min_ms': round(min_ms, 2),
            'max_ms': round(max_ms, 2),
            'stdev_ms': round(stdev_ms, 2),
            'latency_cv_%': round((stdev_ms / avg_ms) * 100, 2) if avg_ms > 0 else 0.0,
            'p25_ms': round(p25_ms, 2),
            'p90_ms': round(p90_ms, 2),
            'p95_ms': round(p95_ms, 2),
            'p99_ms': round(p99_ms, 2),
            'iqr_ms': round(iqr_ms, 2),
            'jitter_ms': round(jitter_ms, 2),
            'bytes_total': total_bytes,
            'wall_time_s': round(wall_time_s, 2),
            'requests_per_sec': round((completed_requests / wall_time_s), 2) if wall_time_s > 0 else 0.0,
            'success_rps': round((successful_requests / wall_time_s), 2) if wall_time_s > 0 else 0.0,
            'throughput_kbps': round(legacy_throughput, 2),
            'throughput_kib_s': round((total_bytes / 1024) / wall_time_s, 2) if wall_time_s > 0 else 0.0,
            'throughput_kbps_wire': round(((total_bytes * 8) / 1000) / wall_time_s, 2) if wall_time_s > 0 else 0.0,
        }

        print(
            f"\n  Avg: {metrics['avg_ms']} ms | Median: {metrics['median_ms']} ms | "
            f"P95: {metrics['p95_ms']} ms | P99: {metrics['p99_ms']} ms"
        )
        print(
            f"  Min: {metrics['min_ms']} ms | Max: {metrics['max_ms']} ms | "
            f"Jitter: {metrics['jitter_ms']} ms | CV: {metrics['latency_cv_%']}%"
        )
        print(
            f"  Success: {metrics['success_rate_%']}% | RPS: {metrics['requests_per_sec']} | "
            f"Throughput: {metrics['throughput_kib_s']} KiB/s ({metrics['throughput_kbps_wire']} kbps)"
        )
        return metrics
    return None


def run_comparison(
    num_requests=50,
    timeout_sec=10,
    interval_sec=0.2,
    http_url=DEFAULT_HTTP_URL,
    https_url=DEFAULT_HTTPS_URL,
    verify_tls=DEFAULT_VERIFY_TLS,
):
    """Run HTTP vs HTTPS comparison and save results to CSV."""
    targets = [
        (http_url, "HTTP"),
        (https_url, "HTTPS"),
    ]

    all_metrics = []
    for url, label in targets:
        result = measure_request(
            url,
            label,
            num_requests=num_requests,
            timeout_sec=timeout_sec,
            interval_sec=interval_sec,
            verify_tls=verify_tls,
        )
        if result:
            all_metrics.append(result)

    if all_metrics:
        output_file = os.path.join(os.path.dirname(__file__), '..', 'data', 'performance_results.csv')
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=all_metrics[0].keys())
            writer.writeheader()
            writer.writerows(all_metrics)
        print(f"\nResults saved to {output_file}")

    return all_metrics


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="HTTP vs HTTPS benchmark with extended metrics")
    parser.add_argument("--http-url", default=DEFAULT_HTTP_URL, help="HTTP target URL")
    parser.add_argument("--https-url", default=DEFAULT_HTTPS_URL, help="HTTPS target URL")
    parser.add_argument("--requests", type=int, default=DEFAULT_REQUESTS, help="Requests per protocol")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SEC, help="Request timeout in seconds")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_SEC, help="Delay between requests in seconds")
    parser.add_argument(
        "--verify-tls",
        action="store_true",
        default=DEFAULT_VERIFY_TLS,
        help="Verify HTTPS certificates. Disabled by default for lab self-signed certificates.",
    )
    args = parser.parse_args()

    run_comparison(
        num_requests=args.requests,
        timeout_sec=args.timeout,
        interval_sec=args.interval,
        http_url=args.http_url,
        https_url=args.https_url,
        verify_tls=args.verify_tls,
    )
