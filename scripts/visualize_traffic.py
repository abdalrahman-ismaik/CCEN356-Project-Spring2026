"""
Script 4 - Advanced Matplotlib Visualization

Reads CSV data files and generates professional multi-panel analytics charts.
Run after capture_traffic.py and performance_metrics.py:
    python scripts/visualize_traffic.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # Non-interactive backend for headless servers
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CHARTS_DIR = BASE_DIR / "charts"

COLORS = {
    "HTTP": "#1479FF",
    "HTTPS": "#06B27A",
    "ACCENT": "#F08C2B",
    "GRID": "#D7E2EF",
    "TEXT": "#1E2A3A",
    "TEXT_SOFT": "#5D6C80",
}


def _configure_style():
    """Apply a consistent style for publication-ready visuals."""
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "axes.facecolor": "#F8FBFF",
            "figure.facecolor": "white",
            "axes.edgecolor": "#BCCBDB",
            "axes.labelcolor": COLORS["TEXT"],
            "xtick.color": COLORS["TEXT_SOFT"],
            "ytick.color": COLORS["TEXT_SOFT"],
            "grid.color": COLORS["GRID"],
            "grid.alpha": 0.8,
            "axes.grid": True,
            "axes.titleweight": "bold",
        }
    )


def _percentile(values, percentile):
    """Return percentile value with linear interpolation."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * (percentile / 100.0)
    lower = int(np.floor(rank))
    upper = int(np.ceil(rank))
    if lower == upper:
        return float(ordered[lower])
    lower_weight = upper - rank
    upper_weight = rank - lower
    return float((ordered[lower] * lower_weight) + (ordered[upper] * upper_weight))


def _read_csv_safe(csv_file):
    if not csv_file.exists():
        return None
    df = pd.read_csv(csv_file)
    if df.empty:
        return None
    return df


def _ensure_protocol_order(df):
    order = {"HTTP": 0, "HTTPS": 1}
    df["protocol"] = df["protocol"].astype(str).str.upper()
    df["sort_key"] = df["protocol"].map(order).fillna(99)
    df = df.sort_values("sort_key").drop(columns=["sort_key"])
    return df


def plot_response_comparison(metrics_file=None):
    """Generate an executive performance storyboard from benchmark data."""
    _configure_style()
    metrics_file = Path(metrics_file) if metrics_file else DATA_DIR / "performance_results.csv"

    df = _read_csv_safe(metrics_file)
    if df is None:
        print(f"Skipped performance chart: missing or empty file {metrics_file}")
        print("Run: python scripts/performance_metrics.py")
        return False

    required_cols = {
        "protocol",
        "avg_ms",
        "min_ms",
        "max_ms",
        "stdev_ms",
        "throughput_kbps",
        "error_rate_%",
        "requests",
        "errors",
    }
    missing = required_cols - set(df.columns)
    if missing:
        print(f"Skipped performance chart: missing columns {sorted(missing)}")
        return False

    df = _ensure_protocol_order(df)
    for col in [
        "avg_ms",
        "min_ms",
        "max_ms",
        "stdev_ms",
        "throughput_kbps",
        "error_rate_%",
        "requests",
        "errors",
    ]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    df["success_rate"] = (100.0 - df["error_rate_%"]).clip(lower=0.0, upper=100.0)
    df["jitter_index_pct"] = np.where(
        df["avg_ms"] > 0,
        (df["stdev_ms"] / df["avg_ms"]) * 100.0,
        0.0,
    )
    df["p95_est_ms"] = df.apply(
        lambda row: max(row["avg_ms"], row["avg_ms"] + (1.645 * row["stdev_ms"])),
        axis=1,
    )

    protocol_names = df["protocol"].tolist()
    protocol_colors = [COLORS.get(name, "#8899AA") for name in protocol_names]

    avg_map = {row["protocol"]: row["avg_ms"] for _, row in df.iterrows()}
    throughput_map = {row["protocol"]: row["throughput_kbps"] for _, row in df.iterrows()}
    faster_label = "N/A"
    if "HTTP" in avg_map and "HTTPS" in avg_map and avg_map["HTTP"] > 0 and avg_map["HTTPS"] > 0:
        faster = "HTTP" if avg_map["HTTP"] < avg_map["HTTPS"] else "HTTPS"
        slower = "HTTPS" if faster == "HTTP" else "HTTP"
        gain = ((avg_map[slower] - avg_map[faster]) / avg_map[slower]) * 100.0
        faster_label = f"{faster} is ~{gain:.1f}% faster on average"

    fig = plt.figure(figsize=(18, 10.5), constrained_layout=True)
    grid = fig.add_gridspec(2, 3)

    ax_summary = fig.add_subplot(grid[0, 0])
    ax_latency = fig.add_subplot(grid[0, 1])
    ax_reliability = fig.add_subplot(grid[0, 2])
    ax_throughput = fig.add_subplot(grid[1, 0])
    ax_range = fig.add_subplot(grid[1, 1])
    ax_variability = fig.add_subplot(grid[1, 2])

    fig.suptitle(
        "CCEN356 HTTP vs HTTPS Performance Storyboard",
        fontsize=20,
        fontweight="bold",
        color=COLORS["TEXT"],
    )

    ax_summary.axis("off")
    summary_lines = [
        "Executive Summary",
        f"- {faster_label}",
        f"- Best throughput: {df.loc[df['throughput_kbps'].idxmax(), 'protocol']}"
        f" ({df['throughput_kbps'].max():.1f} KB/s)",
        f"- Lowest jitter index: {df.loc[df['jitter_index_pct'].idxmin(), 'protocol']}"
        f" ({df['jitter_index_pct'].min():.1f}%)",
        f"- Total benchmark requests: {int(df['requests'].sum())}",
        f"- Total failed requests: {int(df['errors'].sum())}",
    ]
    ax_summary.text(
        0.02,
        0.98,
        "\n".join(summary_lines),
        va="top",
        fontsize=12,
        linespacing=1.7,
        color=COLORS["TEXT"],
        bbox={"boxstyle": "round,pad=0.6", "facecolor": "#EEF5FF", "edgecolor": "#B7CAE2"},
    )

    ax_latency.bar(protocol_names, df["avg_ms"], yerr=df["stdev_ms"],
                   color=protocol_colors, edgecolor="#16324F", capsize=8)
    ax_latency.set_title("Average Latency with Standard Deviation")
    ax_latency.set_ylabel("Milliseconds")
    for x, (_, row) in enumerate(df.iterrows()):
        ax_latency.text(x, row["avg_ms"] + row["stdev_ms"] + 0.6, f"{row['avg_ms']:.1f} ms",
                        ha="center", fontsize=10, color=COLORS["TEXT"])

    ax_reliability.bar(protocol_names, df["success_rate"], color=protocol_colors, edgecolor="#16324F")
    ax_reliability.set_ylim(0, 105)
    ax_reliability.set_title("Reliability (Success Rate)")
    ax_reliability.set_ylabel("Percent")
    for x, value in enumerate(df["success_rate"]):
        ax_reliability.text(x, value + 1.0, f"{value:.1f}%", ha="center", fontsize=10)

    ax_throughput.bar(protocol_names, df["throughput_kbps"], color=protocol_colors, edgecolor="#16324F")
    ax_throughput.set_title("Throughput Comparison")
    ax_throughput.set_ylabel("KB/s")
    for x, value in enumerate(df["throughput_kbps"]):
        ax_throughput.text(x, value + 0.4, f"{value:.1f}", ha="center", fontsize=10)

    x_positions = np.arange(len(df))
    ax_range.vlines(x_positions, df["min_ms"], df["max_ms"], color=protocol_colors, linewidth=4, alpha=0.9)
    ax_range.scatter(x_positions, df["avg_ms"], color=COLORS["ACCENT"], s=140, zorder=4, label="Average")
    ax_range.scatter(x_positions, df["p95_est_ms"], color="#5A4FCF", s=60, zorder=5, label="Estimated P95")
    ax_range.set_xticks(x_positions)
    ax_range.set_xticklabels(protocol_names)
    ax_range.set_ylabel("Milliseconds")
    ax_range.set_title("Latency Envelope (Min to Max)")
    ax_range.legend(frameon=True, facecolor="white")

    bar_positions = np.arange(len(df))
    width = 0.35
    ax_variability.bar(bar_positions - (width / 2), df["jitter_index_pct"], width,
                       color=protocol_colors, edgecolor="#16324F", label="Jitter Index (%)")
    ax_variability.bar(bar_positions + (width / 2), df["p95_est_ms"], width,
                       color="#8B7EDE", edgecolor="#16324F", label="Estimated P95 (ms)")
    ax_variability.set_xticks(bar_positions)
    ax_variability.set_xticklabels(protocol_names)
    ax_variability.set_title("Tail and Variability Indicators")
    ax_variability.set_ylabel("Metric Value")
    ax_variability.legend(frameon=True, facecolor="white")

    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    output = CHARTS_DIR / "performance_comparison.png"
    plt.savefig(output, dpi=220, bbox_inches="tight")
    plt.close(fig)
    print(f"Chart saved: {output}")
    return True


def plot_traffic_over_time(traffic_file=None):
    """Generate advanced packet-level traffic intelligence visuals."""
    _configure_style()
    traffic_file = Path(traffic_file) if traffic_file else DATA_DIR / "traffic_log.csv"

    df = _read_csv_safe(traffic_file)
    if df is None:
        print(f"Skipped traffic chart: missing or empty file {traffic_file}")
        print("Run: python scripts/capture_traffic.py")
        return False

    required_cols = {"timestamp", "src_ip", "dst_ip", "protocol", "length"}
    missing = required_cols - set(df.columns)
    if missing:
        print(f"Skipped traffic chart: missing columns {sorted(missing)}")
        return False

    df["protocol"] = df["protocol"].astype(str).str.upper()
    df["length"] = pd.to_numeric(df["length"], errors="coerce").fillna(0)
    df = df[df["protocol"].isin(["HTTP", "HTTPS"])]
    if df.empty:
        print("Skipped traffic chart: no HTTP/HTTPS rows found")
        return False

    df["time_dt"] = pd.to_datetime(df["timestamp"], format="%H:%M:%S.%f", errors="coerce")
    df = df.dropna(subset=["time_dt"]).sort_values("time_dt")
    if df.empty:
        print("Skipped traffic chart: timestamps could not be parsed")
        return False

    df["second_bucket"] = df["time_dt"].dt.floor("s")
    per_second = df.groupby(["second_bucket", "protocol"]).size().unstack(fill_value=0)
    protocol_counts = df["protocol"].value_counts()

    df["flow"] = df["src_ip"].astype(str) + " -> " + df["dst_ip"].astype(str)
    top_flows = df["flow"].value_counts().head(8).sort_values(ascending=True)

    fig = plt.figure(figsize=(18, 11), constrained_layout=True)
    grid = fig.add_gridspec(2, 3)

    ax_timeline = fig.add_subplot(grid[0, :2])
    ax_share = fig.add_subplot(grid[0, 2])
    ax_size = fig.add_subplot(grid[1, 0])
    ax_cdf = fig.add_subplot(grid[1, 1])
    ax_flows = fig.add_subplot(grid[1, 2])

    fig.suptitle(
        "CCEN356 Packet Capture Intelligence View",
        fontsize=20,
        fontweight="bold",
        color=COLORS["TEXT"],
    )

    for protocol in ["HTTP", "HTTPS"]:
        if protocol in per_second.columns:
            ax_timeline.plot(
                per_second.index,
                per_second[protocol],
                label=f"{protocol} packets/s",
                color=COLORS[protocol],
                linewidth=2.4,
            )
    ax_timeline.set_title("Packets Per Second Timeline")
    ax_timeline.set_ylabel("Packets per second")
    ax_timeline.set_xlabel("Capture timeline")
    ax_timeline.tick_params(axis="x", rotation=30)
    ax_timeline.legend(frameon=True, facecolor="white")

    share_labels = protocol_counts.index.tolist()
    share_values = protocol_counts.values.tolist()
    share_colors = [COLORS.get(label, "#8899AA") for label in share_labels]
    wedges, texts, autotexts = ax_share.pie(
        share_values,
        labels=share_labels,
        colors=share_colors,
        autopct="%1.1f%%",
        startangle=90,
        wedgeprops={"width": 0.45, "edgecolor": "white"},
    )
    for text in texts + autotexts:
        text.set_color(COLORS["TEXT"])
    ax_share.set_title("Protocol Share")

    http_lengths = df.loc[df["protocol"] == "HTTP", "length"].tolist()
    https_lengths = df.loc[df["protocol"] == "HTTPS", "length"].tolist()
    bins = min(30, max(10, int(np.sqrt(len(df)))))
    if http_lengths:
        ax_size.hist(http_lengths, bins=bins, alpha=0.7, color=COLORS["HTTP"], label="HTTP")
    if https_lengths:
        ax_size.hist(https_lengths, bins=bins, alpha=0.7, color=COLORS["HTTPS"], label="HTTPS")
    ax_size.set_title("Packet Size Distribution")
    ax_size.set_xlabel("Packet size (bytes)")
    ax_size.set_ylabel("Frequency")
    ax_size.legend(frameon=True, facecolor="white")

    for protocol in ["HTTP", "HTTPS"]:
        series = np.sort(df.loc[df["protocol"] == protocol, "length"].to_numpy())
        if len(series) == 0:
            continue
        cumulative = np.arange(1, len(series) + 1) / len(series)
        ax_cdf.plot(series, cumulative, color=COLORS[protocol], linewidth=2.3, label=protocol)
        p95 = _percentile(series.tolist(), 95)
        ax_cdf.axvline(p95, color=COLORS[protocol], linestyle="--", alpha=0.6)
    ax_cdf.set_title("Packet Size CDF")
    ax_cdf.set_xlabel("Packet size (bytes)")
    ax_cdf.set_ylabel("Cumulative probability")
    ax_cdf.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(xmax=1.0))
    ax_cdf.legend(frameon=True, facecolor="white")

    if not top_flows.empty:
        ax_flows.barh(top_flows.index, top_flows.values, color="#2E5EAA", edgecolor="#16324F")
    ax_flows.set_title("Top Conversations by Packet Count")
    ax_flows.set_xlabel("Packets")

    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    output = CHARTS_DIR / "traffic_analysis.png"
    plt.savefig(output, dpi=220, bbox_inches="tight")
    plt.close(fig)
    print(f"Chart saved: {output}")
    return True


if __name__ == "__main__":
    performance_ok = plot_response_comparison()
    traffic_ok = plot_traffic_over_time()

    if not performance_ok and not traffic_ok:
        print("No charts generated. Ensure data files exist in the data directory.")
