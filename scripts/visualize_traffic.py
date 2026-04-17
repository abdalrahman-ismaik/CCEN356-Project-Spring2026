"""
Script 4 — Matplotlib Visualization

Reads CSV data files and generates comparison charts as PNG images.
Run after capture_traffic.py and performance_metrics.py:
    python3 visualize_traffic.py
"""

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for headless servers
import matplotlib.pyplot as plt
import pandas as pd
import os

BASE_DIR = os.path.join(os.path.dirname(__file__), '..')
DATA_DIR = os.path.join(BASE_DIR, 'data')
CHARTS_DIR = os.path.join(BASE_DIR, 'charts')


def plot_response_comparison(metrics_file=None):
    """Generate HTTP vs HTTPS performance comparison charts."""
    if metrics_file is None:
        metrics_file = os.path.join(DATA_DIR, 'performance_results.csv')

    if not os.path.exists(metrics_file):
        print(f"Skipped performance chart: missing file {metrics_file}")
        print("Run: python scripts/performance_metrics.py")
        return False

    df = pd.read_csv(metrics_file)

    if df.empty:
        print(f"Skipped performance chart: no rows in {metrics_file}")
        return False

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle('HTTP vs HTTPS Performance Comparison', fontsize=14, fontweight='bold')

    colors = ['#2196F3', '#4CAF50']

    # Plot 1: Average Response Time
    axes[0].bar(df['protocol'], df['avg_ms'], color=colors, edgecolor='black')
    axes[0].set_title('Average Response Time (ms)')
    axes[0].set_ylabel('Milliseconds')
    for i, v in enumerate(df['avg_ms']):
        axes[0].text(i, v + 0.5, f'{v:.1f}ms', ha='center', fontweight='bold')

    # Plot 2: Throughput
    axes[1].bar(df['protocol'], df['throughput_kbps'], color=colors, edgecolor='black')
    axes[1].set_title('Throughput (KB/s)')
    axes[1].set_ylabel('KB/s')
    for i, v in enumerate(df['throughput_kbps']):
        axes[1].text(i, v + 0.5, f'{v:.1f}', ha='center', fontweight='bold')

    # Plot 3: Response Time Range (Min/Avg/Max)
    for i, (_, row) in enumerate(df.iterrows()):
        axes[2].errorbar(
            i, row['avg_ms'],
            yerr=[[row['avg_ms'] - row['min_ms']], [row['max_ms'] - row['avg_ms']]],
            fmt='o', color=colors[i], capsize=8, markersize=10, linewidth=2
        )
    axes[2].set_title('Response Time Range (Min/Avg/Max)')
    axes[2].set_ylabel('Milliseconds')
    axes[2].set_xticks([0, 1])
    axes[2].set_xticklabels(df['protocol'])

    plt.tight_layout()
    os.makedirs(CHARTS_DIR, exist_ok=True)
    output = os.path.join(CHARTS_DIR, 'performance_comparison.png')
    plt.savefig(output, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Chart saved: {output}")
    return True


def plot_traffic_over_time(traffic_file=None):
    """Generate traffic capture analysis charts."""
    if traffic_file is None:
        traffic_file = os.path.join(DATA_DIR, 'traffic_log.csv')

    if not os.path.exists(traffic_file):
        print(f"Skipped traffic chart: missing file {traffic_file}")
        print("Run: python scripts/capture_traffic.py")
        return False

    df = pd.read_csv(traffic_file)

    if df.empty:
        print(f"Skipped traffic chart: no rows in {traffic_file}")
        return False

    http_df = df[df['protocol'] == 'HTTP']
    https_df = df[df['protocol'] == 'HTTPS']

    fig, axes = plt.subplots(2, 1, figsize=(12, 8))
    fig.suptitle('Traffic Capture Analysis', fontsize=14, fontweight='bold')

    # Packet count per protocol
    counts = df['protocol'].value_counts()
    axes[0].bar(counts.index, counts.values, color=['#2196F3', '#4CAF50'], edgecolor='black')
    axes[0].set_title('Packet Count by Protocol')
    axes[0].set_ylabel('Number of Packets')

    # Packet size distribution
    if not http_df.empty:
        axes[1].hist(http_df['length'], bins=20, alpha=0.7, label='HTTP', color='#2196F3')
    if not https_df.empty:
        axes[1].hist(https_df['length'], bins=20, alpha=0.7, label='HTTPS', color='#4CAF50')
    axes[1].set_title('Packet Size Distribution')
    axes[1].set_xlabel('Packet Size (bytes)')
    axes[1].set_ylabel('Frequency')
    axes[1].legend()

    plt.tight_layout()
    os.makedirs(CHARTS_DIR, exist_ok=True)
    output = os.path.join(CHARTS_DIR, 'traffic_analysis.png')
    plt.savefig(output, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Chart saved: {output}")
    return True


if __name__ == '__main__':
    perf_ok = plot_response_comparison()
    traffic_ok = plot_traffic_over_time()

    if not perf_ok and not traffic_ok:
        print("No charts generated. Ensure data files exist in the data directory.")
