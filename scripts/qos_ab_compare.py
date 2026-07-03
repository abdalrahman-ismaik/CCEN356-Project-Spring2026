"""
Script 7 - Isolated QoS A/B Comparison

Runs a direct A/B test in two phases:
1) without_qos
2) with_qos

Each phase sends a fixed number of HTTP and HTTPS requests, captures only packets
that belong to this experiment (using the script's own ephemeral ports), computes
metrics, and generates a dedicated comparison graph.

Example:
    python scripts/qos_ab_compare.py --packets 200
"""

import argparse
import csv
import math
import os
import ssl
import statistics
import time
import uuid
from datetime import datetime
from threading import Event, Lock, Thread
from urllib.parse import urlsplit

import matplotlib.pyplot as plt
from scapy.all import IP, TCP, conf, sniff

QOS_HEADER = os.getenv("CCEN356_QOS_MODE_HEADER", "X-CCEN356-QOS-MODE")
QOS_VALUE = os.getenv("CCEN356_QOS_MODE_VALUE", "on")
EXPERIMENT_HEADER = "X-CCEN356-Experiment-ID"

DEFAULT_HTTP_URL = os.getenv("CCEN356_HTTP_URL", "http://192.165.20.79")
DEFAULT_HTTPS_URL = os.getenv("CCEN356_HTTPS_URL", "https://192.165.20.79")


def percentile(values, p):
    if not values:
        return 0.0

    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])

    rank = (len(ordered) - 1) * (p / 100.0)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))

    if lower == upper:
        return float(ordered[lower])

    lower_weight = upper - rank
    upper_weight = rank - lower
    return float((ordered[lower] * lower_weight) + (ordered[upper] * upper_weight))


def average_jitter(values):
    if len(values) < 2:
        return 0.0
    deltas = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    return float(sum(deltas) / len(deltas)) if deltas else 0.0


class PacketCapture:
    def __init__(self, server_ip):
        self.server_ip = server_ip
        self._packets = []
        self._lock = Lock()
        self._stop_event = Event()
        self._thread = None
        self.iface = None

    def _packet_callback(self, packet):
        if not (packet.haslayer(IP) and packet.haslayer(TCP)):
            return

        src_ip = packet[IP].src
        dst_ip = packet[IP].dst
        src_port = int(packet[TCP].sport)
        dst_port = int(packet[TCP].dport)

        if self.server_ip not in (src_ip, dst_ip):
            return

        if not ({src_port, dst_port} & {80, 443}):
            return

        record = {
            "ts": time.time(),
            "timestamp": datetime.now().strftime("%H:%M:%S.%f"),
            "src_ip": src_ip,
            "dst_ip": dst_ip,
            "src_port": src_port,
            "dst_port": dst_port,
            "length": len(packet),
            "tcp_flags": str(packet[TCP].flags),
            "protocol": "HTTPS" if (src_port == 443 or dst_port == 443) else "HTTP",
        }

        with self._lock:
            self._packets.append(record)

    def _sniff_loop(self):
        bpf_filter = f"host {self.server_ip} and (tcp port 80 or tcp port 443)"

        sniff(
            iface=self.iface,
            filter=bpf_filter,
            prn=self._packet_callback,
            store=False,
            timeout=0,
            stop_filter=lambda _: self._stop_event.is_set(),
        )

    def start(self):
        route_iface = conf.route.route(self.server_ip)[0]
        self.iface = route_iface

        self._thread = Thread(target=self._sniff_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def snapshot(self):
        with self._lock:
            return list(self._packets)


def send_single_request(parsed_url, timeout_sec, headers, verify_tls):
    import http.client

    port = parsed_url.port
    if port is None:
        port = 443 if parsed_url.scheme == "https" else 80

    path = parsed_url.path or "/"
    if parsed_url.query:
        path = f"{path}?{parsed_url.query}"

    if parsed_url.scheme == "https":
        context = ssl.create_default_context()
        if not verify_tls:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        conn = http.client.HTTPSConnection(parsed_url.hostname, port=port, timeout=timeout_sec, context=context)
    else:
        conn = http.client.HTTPConnection(parsed_url.hostname, port=port, timeout=timeout_sec)

    local_port = None
    status_code = None
    body_len = 0
    elapsed_ms = None

    started = time.perf_counter()
    try:
        conn.putrequest("GET", path, skip_host=False)
        for key, value in headers.items():
            conn.putheader(key, value)
        conn.putheader("Connection", "close")
        conn.endheaders()

        if conn.sock is not None:
            local_port = int(conn.sock.getsockname()[1])

        response = conn.getresponse()
        status_code = int(response.status)
        body = response.read()
        body_len = len(body)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
    finally:
        conn.close()

    return elapsed_ms, status_code, body_len, local_port


def phase_headers(experiment_id, qos_enabled):
    headers = {
        EXPERIMENT_HEADER: experiment_id,
    }
    if qos_enabled:
        headers[QOS_HEADER] = QOS_VALUE
    return headers


def summarize(mode, protocol, url, latencies, status_codes, errors, bytes_total, wall_time_sec):
    ok_codes = [code for code in status_codes if code is not None and 200 <= code <= 399]

    successes = len(ok_codes)
    total = successes + errors
    error_rate = (errors / total * 100.0) if total else 0.0

    avg_ms = statistics.mean(latencies) if latencies else 0.0
    stdev_ms = statistics.stdev(latencies) if len(latencies) > 1 else 0.0

    return {
        "mode": mode,
        "protocol": protocol,
        "url": url,
        "requests": total,
        "successes": successes,
        "errors": errors,
        "error_rate_%": round(error_rate, 2),
        "avg_ms": round(avg_ms, 2),
        "median_ms": round(statistics.median(latencies), 2) if latencies else 0.0,
        "p95_ms": round(percentile(latencies, 95), 2),
        "p99_ms": round(percentile(latencies, 99), 2),
        "min_ms": round(min(latencies), 2) if latencies else 0.0,
        "max_ms": round(max(latencies), 2) if latencies else 0.0,
        "stdev_ms": round(stdev_ms, 2),
        "jitter_ms": round(average_jitter(latencies), 2),
        "bytes_total": int(bytes_total),
        "wall_time_s": round(wall_time_sec, 2),
        "requests_per_sec": round((total / wall_time_sec), 2) if wall_time_sec > 0 else 0.0,
        "throughput_kib_s": round(((bytes_total / 1024.0) / wall_time_sec), 2) if wall_time_sec > 0 else 0.0,
    }


def run_phase(mode_name, qos_enabled, http_url, https_url, packets_per_protocol, timeout_sec, interval_sec, verify_tls, port_registry):
    print(f"\n=== Phase: {mode_name} (qos={'on' if qos_enabled else 'off'}) ===")
    print(f"Requests per protocol: {packets_per_protocol}")

    phase_start = time.perf_counter()
    phase_rows = []

    targets = [
        ("HTTP", http_url, urlsplit(http_url)),
        ("HTTPS", https_url, urlsplit(https_url)),
    ]

    experiment_id = f"{mode_name}-{uuid.uuid4().hex[:8]}"

    for protocol, url, parsed_url in targets:
        headers = phase_headers(experiment_id, qos_enabled)
        latencies = []
        status_codes = []
        errors = 0
        bytes_total = 0

        for i in range(packets_per_protocol):
            try:
                elapsed_ms, status_code, body_len, local_port = send_single_request(
                    parsed_url,
                    timeout_sec=timeout_sec,
                    headers=headers,
                    verify_tls=verify_tls,
                )

                if local_port is not None:
                    port_registry[mode_name][protocol].add(int(local_port))

                if status_code >= 400:
                    errors += 1
                else:
                    status_codes.append(status_code)
                    bytes_total += body_len
                    if elapsed_ms is not None:
                        latencies.append(elapsed_ms)

                print(
                    f"  {mode_name} | {protocol} | req {i + 1:03d}/{packets_per_protocol} | "
                    f"status {status_code} | {elapsed_ms:.2f} ms"
                )
            except Exception as exc:
                errors += 1
                print(f"  {mode_name} | {protocol} | req {i + 1:03d}/{packets_per_protocol} | ERROR: {exc}")

            if interval_sec > 0:
                time.sleep(interval_sec)

        row = summarize(
            mode=mode_name,
            protocol=protocol,
            url=url,
            latencies=latencies,
            status_codes=status_codes,
            errors=errors,
            bytes_total=bytes_total,
            wall_time_sec=time.perf_counter() - phase_start,
        )
        phase_rows.append(row)

    return phase_rows


def classify_packet_mode(packet, tracked_ports):
    src_port = int(packet["src_port"])
    dst_port = int(packet["dst_port"])
    protocol = packet["protocol"]

    for mode_name, mode_data in tracked_ports.items():
        ports = mode_data[protocol]
        if src_port in ports or dst_port in ports:
            return mode_name

    return None


def isolate_experiment_packets(all_packets, tracked_ports):
    isolated = []
    for pkt in all_packets:
        mode_name = classify_packet_mode(pkt, tracked_ports)
        if not mode_name:
            continue
        enriched = dict(pkt)
        enriched["mode"] = mode_name
        isolated.append(enriched)
    return isolated


def summarize_packets(isolated_packets):
    buckets = {}
    for pkt in isolated_packets:
        key = (pkt["mode"], pkt["protocol"])
        buckets.setdefault(key, {"packets": 0, "bytes": 0})
        buckets[key]["packets"] += 1
        buckets[key]["bytes"] += int(pkt["length"])

    rows = []
    for (mode, protocol), data in sorted(buckets.items()):
        rows.append(
            {
                "mode": mode,
                "protocol": protocol,
                "captured_packets": data["packets"],
                "captured_bytes": data["bytes"],
            }
        )
    return rows


def write_csv(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not rows:
        return

    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_chart(metrics_rows, packet_rows, output_file):
    modes = ["without_qos", "with_qos"]
    protocols = ["HTTP", "HTTPS"]

    latency_map = {(row["mode"], row["protocol"]): row["avg_ms"] for row in metrics_rows}
    p95_map = {(row["mode"], row["protocol"]): row["p95_ms"] for row in metrics_rows}
    error_map = {(row["mode"], row["protocol"]): row["error_rate_%"] for row in metrics_rows}
    packets_map = {(row["mode"], row["protocol"]): row["captured_packets"] for row in packet_rows}

    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    fig.suptitle("QoS A/B Comparison (Isolated Test Traffic)", fontsize=14, fontweight="bold")

    width = 0.35
    x = list(range(len(protocols)))

    without_vals = [latency_map.get(("without_qos", p), 0.0) for p in protocols]
    with_vals = [latency_map.get(("with_qos", p), 0.0) for p in protocols]
    axes[0, 0].bar([i - width / 2 for i in x], without_vals, width=width, label="Without QoS")
    axes[0, 0].bar([i + width / 2 for i in x], with_vals, width=width, label="With QoS")
    axes[0, 0].set_title("Average Latency (ms)")
    axes[0, 0].set_xticks(x)
    axes[0, 0].set_xticklabels(protocols)
    axes[0, 0].set_ylabel("ms")
    axes[0, 0].legend()

    without_p95 = [p95_map.get(("without_qos", p), 0.0) for p in protocols]
    with_p95 = [p95_map.get(("with_qos", p), 0.0) for p in protocols]
    axes[0, 1].bar([i - width / 2 for i in x], without_p95, width=width, label="Without QoS")
    axes[0, 1].bar([i + width / 2 for i in x], with_p95, width=width, label="With QoS")
    axes[0, 1].set_title("P95 Latency (ms)")
    axes[0, 1].set_xticks(x)
    axes[0, 1].set_xticklabels(protocols)
    axes[0, 1].set_ylabel("ms")
    axes[0, 1].legend()

    without_err = [error_map.get(("without_qos", p), 0.0) for p in protocols]
    with_err = [error_map.get(("with_qos", p), 0.0) for p in protocols]
    axes[1, 0].bar([i - width / 2 for i in x], without_err, width=width, label="Without QoS")
    axes[1, 0].bar([i + width / 2 for i in x], with_err, width=width, label="With QoS")
    axes[1, 0].set_title("Error Rate (%)")
    axes[1, 0].set_xticks(x)
    axes[1, 0].set_xticklabels(protocols)
    axes[1, 0].set_ylabel("%")
    axes[1, 0].legend()

    without_packets = [packets_map.get(("without_qos", p), 0) for p in protocols]
    with_packets = [packets_map.get(("with_qos", p), 0) for p in protocols]
    axes[1, 1].bar([i - width / 2 for i in x], without_packets, width=width, label="Without QoS")
    axes[1, 1].bar([i + width / 2 for i in x], with_packets, width=width, label="With QoS")
    axes[1, 1].set_title("Captured Test Packets (Isolated)")
    axes[1, 1].set_xticks(x)
    axes[1, 1].set_xticklabels(protocols)
    axes[1, 1].set_ylabel("packets")
    axes[1, 1].legend()

    for ax in axes.flat:
        ax.grid(axis="y", alpha=0.25)

    fig.tight_layout(rect=[0, 0.03, 1, 0.95])
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    fig.savefig(output_file, dpi=160)
    plt.close(fig)


def print_phase_summary(rows):
    print("\nPhase Summary")
    print("-" * 80)
    for row in rows:
        print(
            f"{row['mode']:<12} | {row['protocol']:<5} | avg {row['avg_ms']:>7} ms | "
            f"p95 {row['p95_ms']:>7} ms | err% {row['error_rate_%']:>6} | "
            f"rps {row['requests_per_sec']:>6}"
        )


def print_ab_delta(rows):
    index = {(row["mode"], row["protocol"]): row for row in rows}
    print("\nQoS Delta (with_qos - without_qos)")
    print("-" * 80)
    for protocol in ("HTTP", "HTTPS"):
        base = index.get(("without_qos", protocol))
        tuned = index.get(("with_qos", protocol))
        if not base or not tuned:
            continue

        avg_delta = round(tuned["avg_ms"] - base["avg_ms"], 2)
        p95_delta = round(tuned["p95_ms"] - base["p95_ms"], 2)
        err_delta = round(tuned["error_rate_%"] - base["error_rate_%"], 2)

        print(
            f"{protocol:<5} | avg delta {avg_delta:>8} ms | p95 delta {p95_delta:>8} ms | "
            f"error delta {err_delta:>7}%"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Run isolated without-QoS vs with-QoS comparison and chart results."
    )
    parser.add_argument("--http-url", default=DEFAULT_HTTP_URL, help="HTTP target URL")
    parser.add_argument("--https-url", default=DEFAULT_HTTPS_URL, help="HTTPS target URL")
    parser.add_argument("--packets", type=int, default=200, help="Requests per protocol, per mode")
    parser.add_argument("--timeout", type=float, default=2.5, help="Request timeout in seconds")
    parser.add_argument("--interval", type=float, default=0.0, help="Delay between requests in seconds")
    parser.add_argument(
        "--verify-tls",
        action="store_true",
        help="Verify TLS certificates for HTTPS (default: disabled for lab self-signed certs)",
    )
    parser.add_argument(
        "--output-prefix",
        default="qos_ab",
        help="Output filename prefix (without extension)",
    )

    args = parser.parse_args()

    if args.packets <= 0:
        raise ValueError("--packets must be greater than zero")

    server_ip = urlsplit(args.http_url).hostname
    if not server_ip:
        raise ValueError("Could not determine server host from --http-url")

    out_dir_data = os.path.join(os.path.dirname(__file__), "..", "data")
    out_dir_charts = os.path.join(os.path.dirname(__file__), "..", "charts")

    metrics_csv = os.path.join(out_dir_data, f"{args.output_prefix}_metrics.csv")
    isolated_packets_csv = os.path.join(out_dir_data, f"{args.output_prefix}_isolated_packets.csv")
    packet_summary_csv = os.path.join(out_dir_data, f"{args.output_prefix}_packet_summary.csv")
    chart_png = os.path.join(out_dir_charts, f"{args.output_prefix}_comparison.png")

    tracked_ports = {
        "without_qos": {"HTTP": set(), "HTTPS": set()},
        "with_qos": {"HTTP": set(), "HTTPS": set()},
    }

    capture = PacketCapture(server_ip=server_ip)
    print(f"Starting isolated packet capture on interface route to {server_ip}...")
    try:
        capture.start()
    except Exception as exc:
        print(f"Warning: packet capture could not start ({exc}). Continuing with latency-only metrics.")
        capture = None

    all_rows = []
    try:
        all_rows.extend(
            run_phase(
                mode_name="without_qos",
                qos_enabled=False,
                http_url=args.http_url,
                https_url=args.https_url,
                packets_per_protocol=args.packets,
                timeout_sec=args.timeout,
                interval_sec=args.interval,
                verify_tls=args.verify_tls,
                port_registry=tracked_ports,
            )
        )
        all_rows.extend(
            run_phase(
                mode_name="with_qos",
                qos_enabled=True,
                http_url=args.http_url,
                https_url=args.https_url,
                packets_per_protocol=args.packets,
                timeout_sec=args.timeout,
                interval_sec=args.interval,
                verify_tls=args.verify_tls,
                port_registry=tracked_ports,
            )
        )
    finally:
        if capture is not None:
            capture.stop()

    isolated_packets = []
    packet_summary = []
    if capture is not None:
        all_packets = capture.snapshot()
        isolated_packets = isolate_experiment_packets(all_packets, tracked_ports)
        packet_summary = summarize_packets(isolated_packets)

    write_csv(metrics_csv, all_rows)
    if isolated_packets:
        write_csv(isolated_packets_csv, isolated_packets)
    if packet_summary:
        write_csv(packet_summary_csv, packet_summary)

    build_chart(all_rows, packet_summary, chart_png)

    print_phase_summary(all_rows)
    print_ab_delta(all_rows)
    print("\nSaved outputs")
    print("-" * 80)
    print(f"Metrics CSV         : {os.path.abspath(metrics_csv)}")
    if isolated_packets:
        print(f"Isolated packets CSV: {os.path.abspath(isolated_packets_csv)}")
        print(f"Packet summary CSV  : {os.path.abspath(packet_summary_csv)}")
    else:
        print("Isolated packets CSV: not written (capture unavailable or no packets matched)")
    print(f"Comparison chart    : {os.path.abspath(chart_png)}")


if __name__ == "__main__":
    main()
