"""
Script 3 — HTTP vs HTTPS Performance Benchmark

Sends 20 requests to both HTTP and HTTPS endpoints, measures latency and throughput.
Run from Client PC:
    python3 performance_metrics.py
"""

import requests
import time
import statistics
import csv
import os
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def measure_request(url, protocol_label, num_requests=100):
    """Send multiple GET requests and collect performance metrics."""
    response_times = []
    errors = 0
    total_bytes = 0

    print(f"\nTesting {protocol_label} -> {url}")
    print("-" * 50)

    for i in range(num_requests):
        try:
            start = time.time()
            response = requests.get(url, timeout=10, verify=False)
            elapsed = (time.time() - start) * 1000  # ms

            response_times.append(elapsed)
            total_bytes += len(response.content)
            print(f"  Request {i+1:02d}: {elapsed:.2f} ms | Status: {response.status_code}")
        except Exception as e:
            errors += 1
            print(f"  Request {i+1:02d}: ERROR - {e}")

        time.sleep(0.2)

    if response_times:
        metrics = {
            'protocol': protocol_label,
            'url': url,
            'requests': num_requests,
            'errors': errors,
            'avg_ms': round(statistics.mean(response_times), 2),
            'min_ms': round(min(response_times), 2),
            'max_ms': round(max(response_times), 2),
            'stdev_ms': round(statistics.stdev(response_times), 2) if len(response_times) > 1 else 0,
            'throughput_kbps': round((total_bytes / 1024) / (sum(response_times) / 1000), 2),
            'error_rate_%': round((errors / num_requests) * 100, 2),
        }

        print(f"\n  Avg: {metrics['avg_ms']} ms | Min: {metrics['min_ms']} ms | "
              f"Max: {metrics['max_ms']} ms | Throughput: {metrics['throughput_kbps']} KB/s")
        return metrics
    return None


def run_comparison():
    """Run HTTP vs HTTPS comparison and save results to CSV."""
    targets = [
        ("http://192.165.20.79", "HTTP"),
        ("https://192.165.20.79", "HTTPS"),
    ]

    all_metrics = []
    for url, label in targets:
        result = measure_request(url, label)
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
    run_comparison()
