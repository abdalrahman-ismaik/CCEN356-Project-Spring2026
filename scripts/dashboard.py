"""
Script 5 - Flask Live Dashboard (Advanced)

Professional real-time dashboard for HTTP/HTTPS monitoring.
Recommended run location: Server PC (so all clients can open it).

Examples:
    python scripts/dashboard.py
    set CCEN356_DASHBOARD_PORT=5000 && python scripts/dashboard.py
"""

from collections import deque
from datetime import datetime
import math
import os
import statistics
import threading
import time
from urllib.parse import urlsplit, urlunsplit

from flask import Flask, jsonify, render_template_string
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

DEFAULT_SERVER_HOST = os.getenv("CCEN356_SERVER_HOST", "192.165.20.79")
HTTP_TARGET = os.getenv("CCEN356_HTTP_URL", f"http://{DEFAULT_SERVER_HOST}")
HTTPS_TARGET = os.getenv("CCEN356_HTTPS_URL", f"https://{DEFAULT_SERVER_HOST}")

DASHBOARD_HOST = os.getenv("CCEN356_DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT = int(os.getenv("CCEN356_DASHBOARD_PORT", "5000"))
POLL_INTERVAL_SEC = float(os.getenv("CCEN356_POLL_INTERVAL_SEC", "3"))
REQUEST_TIMEOUT_SEC = float(os.getenv("CCEN356_REQUEST_TIMEOUT_SEC", "6"))
MAX_SAMPLES = int(os.getenv("CCEN356_DASHBOARD_MAX_SAMPLES", "240"))


def _safe_parse_ports(raw_value, defaults):
    """Parse comma-separated port list from environment variable."""
    ports = []
    for chunk in str(raw_value).split(","):
        text = chunk.strip()
        if not text:
            continue
        if text.isdigit():
            value = int(text)
            if 1 <= value <= 65535 and value not in ports:
                ports.append(value)
    return ports or list(defaults)


def _build_candidates(primary_url, scheme, candidate_ports):
    """Build deduplicated endpoint candidates preserving host/path while trying fallback ports."""
    seed_url = primary_url if "://" in primary_url else f"{scheme}://{primary_url}"
    parsed = urlsplit(seed_url)

    host = parsed.hostname or DEFAULT_SERVER_HOST
    path = parsed.path if parsed.path else "/"
    query = parsed.query

    candidates = []

    def add_candidate(hostname, port=None):
        netloc = hostname if port is None else f"{hostname}:{port}"
        url = urlunsplit((scheme, netloc, path, query, ""))
        if url not in candidates:
            candidates.append(url)

    # Keep the user-specified URL first so explicit configuration always takes priority.
    if seed_url not in candidates:
        candidates.append(seed_url)

    add_candidate(host, port=None)
    for port in candidate_ports:
        add_candidate(host, port=port)

    return candidates


HTTP_FALLBACK_PORTS = _safe_parse_ports(
    os.getenv("CCEN356_HTTP_FALLBACK_PORTS", "80"),
    defaults=[80],
)
HTTPS_FALLBACK_PORTS = _safe_parse_ports(
    os.getenv("CCEN356_HTTPS_FALLBACK_PORTS", "443,433"),
    defaults=[443, 433],
)

HTTP_CANDIDATES = _build_candidates(HTTP_TARGET, "http", HTTP_FALLBACK_PORTS)
HTTPS_CANDIDATES = _build_candidates(HTTPS_TARGET, "https", HTTPS_FALLBACK_PORTS)


def _new_endpoint_state(target_url, candidates, verify_tls):
    return {
        "target": target_url,
        "candidates": list(candidates),
        "verify_tls": verify_tls,
        "failover_hits": 0,
        "checks": 0,
        "successes": 0,
        "failures": 0,
        "last_error": "not sampled yet",
        "last_status_code": None,
        "last_latency_ms": None,
        "last_check_at": None,
        "is_up": False,
        "latencies": deque(maxlen=MAX_SAMPLES),
    }


METRICS_LOCK = threading.Lock()
DASHBOARD_STATE = {
    "started_at": time.time(),
    "timeline": {
        "labels": deque(maxlen=MAX_SAMPLES),
        "http_ms": deque(maxlen=MAX_SAMPLES),
        "https_ms": deque(maxlen=MAX_SAMPLES),
    },
    "endpoints": {
        "http": _new_endpoint_state(HTTP_TARGET, HTTP_CANDIDATES, verify_tls=False),
        "https": _new_endpoint_state(HTTPS_TARGET, HTTPS_CANDIDATES, verify_tls=False),
    },
}


def _round_or_zero(value, digits=2):
    return round(value, digits) if value is not None else 0.0


def _percentile(values, percentile):
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * (percentile / 100.0)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return float(ordered[lower])
    lower_weight = upper - rank
    upper_weight = rank - lower
    return float((ordered[lower] * lower_weight) + (ordered[upper] * upper_weight))


def _jitter(values):
    if len(values) < 2:
        return 0.0
    deltas = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    return float(sum(deltas) / len(deltas)) if deltas else 0.0


def _score_from_latency(value, factor, ceiling=100.0):
    score = max(0.0, ceiling - (value * factor))
    return min(100.0, score)


def _summarize(endpoint_state):
    values = list(endpoint_state["latencies"])
    checks = endpoint_state["checks"]
    successes = endpoint_state["successes"]
    failures = endpoint_state["failures"]
    uptime_pct = (successes / checks * 100.0) if checks else 0.0

    if values:
        avg_ms = float(statistics.mean(values))
        min_ms = float(min(values))
        max_ms = float(max(values))
        stdev_ms = float(statistics.stdev(values)) if len(values) > 1 else 0.0
        p95_ms = _percentile(values, 95)
        p99_ms = _percentile(values, 99)
        jitter_ms = _jitter(values)
    else:
        avg_ms = min_ms = max_ms = stdev_ms = p95_ms = p99_ms = jitter_ms = 0.0

    scores = {
        "latency": _score_from_latency(avg_ms, factor=1.5),
        "tail": _score_from_latency(p95_ms, factor=1.2),
        "jitter": _score_from_latency(jitter_ms, factor=3.0),
        "availability": min(100.0, uptime_pct),
        "consistency": _score_from_latency(stdev_ms, factor=3.0),
    }

    return {
        "checks": checks,
        "successes": successes,
        "failures": failures,
        "uptime_pct": _round_or_zero(uptime_pct, 2),
        "avg_ms": _round_or_zero(avg_ms, 2),
        "min_ms": _round_or_zero(min_ms, 2),
        "max_ms": _round_or_zero(max_ms, 2),
        "stdev_ms": _round_or_zero(stdev_ms, 2),
        "p95_ms": _round_or_zero(p95_ms, 2),
        "p99_ms": _round_or_zero(p99_ms, 2),
        "jitter_ms": _round_or_zero(jitter_ms, 2),
        "samples": [_round_or_zero(v, 2) for v in values[-20:]],
        "profile_scores": {k: _round_or_zero(v, 2) for k, v in scores.items()},
    }


def _probe_target(url, verify_tls):
    start = time.perf_counter()
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SEC, verify=verify_tls)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return {
            "ok": True,
            "status_code": response.status_code,
            "latency_ms": round(elapsed_ms, 2),
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "status_code": None,
            "latency_ms": None,
            "error": str(exc),
        }


def _probe_endpoint(endpoint_state):
    """Probe the active target first, then fallback candidates until one succeeds."""
    ordered_candidates = [endpoint_state["target"]] + [
        url for url in endpoint_state["candidates"] if url != endpoint_state["target"]
    ]

    errors = []
    for index, candidate in enumerate(ordered_candidates):
        result = _probe_target(candidate, verify_tls=endpoint_state["verify_tls"])
        if result["ok"]:
            result["target"] = candidate
            result["failover_used"] = index > 0
            return result
        errors.append(f"{candidate} -> {result['error']}")

    final_error = " | ".join(errors[:3]) if errors else "Unknown connection error"
    return {
        "ok": False,
        "status_code": None,
        "latency_ms": None,
        "error": f"All endpoint candidates failed. {final_error}",
        "target": endpoint_state["target"],
        "failover_used": False,
    }


def background_collector():
    """Continuously probe HTTP/HTTPS targets and update shared dashboard state."""
    while True:
        timestamp_label = datetime.now().strftime("%H:%M:%S")
        cycle = {}
        for key in ("http", "https"):
            endpoint_state = DASHBOARD_STATE["endpoints"][key]
            cycle[key] = _probe_endpoint(endpoint_state)

        with METRICS_LOCK:
            DASHBOARD_STATE["timeline"]["labels"].append(timestamp_label)
            DASHBOARD_STATE["timeline"]["http_ms"].append(cycle["http"]["latency_ms"])
            DASHBOARD_STATE["timeline"]["https_ms"].append(cycle["https"]["latency_ms"])

            for key in ("http", "https"):
                endpoint = DASHBOARD_STATE["endpoints"][key]
                result = cycle[key]
                endpoint["checks"] += 1
                endpoint["last_error"] = result["error"]
                endpoint["last_status_code"] = result["status_code"]
                endpoint["last_latency_ms"] = result["latency_ms"]
                endpoint["last_check_at"] = timestamp_label
                endpoint["is_up"] = bool(result["ok"])
                if result.get("target") and result["target"] != endpoint["target"]:
                    endpoint["target"] = result["target"]
                    endpoint["failover_hits"] += 1

                if result["ok"] and result["latency_ms"] is not None:
                    endpoint["successes"] += 1
                    endpoint["latencies"].append(result["latency_ms"])
                else:
                    endpoint["failures"] += 1

        time.sleep(POLL_INTERVAL_SEC)


def _snapshot_state():
    with METRICS_LOCK:
        timeline = {
            "labels": list(DASHBOARD_STATE["timeline"]["labels"]),
            "http_ms": [x if x is not None else None for x in DASHBOARD_STATE["timeline"]["http_ms"]],
            "https_ms": [x if x is not None else None for x in DASHBOARD_STATE["timeline"]["https_ms"]],
        }

        endpoints = {}
        for key, endpoint in DASHBOARD_STATE["endpoints"].items():
            endpoints[key] = {
                "target": endpoint["target"],
                "candidates": list(endpoint["candidates"]),
                "failover_hits": endpoint["failover_hits"],
                "checks": endpoint["checks"],
                "successes": endpoint["successes"],
                "failures": endpoint["failures"],
                "last_error": endpoint["last_error"],
                "last_status_code": endpoint["last_status_code"],
                "last_latency_ms": endpoint["last_latency_ms"],
                "last_check_at": endpoint["last_check_at"],
                "is_up": endpoint["is_up"],
                "latencies": list(endpoint["latencies"]),
            }
    return timeline, endpoints


def _build_payload():
    timeline, endpoints = _snapshot_state()

    http_summary = _summarize(endpoints["http"])
    https_summary = _summarize(endpoints["https"])

    avg_delta = _round_or_zero(https_summary["avg_ms"] - http_summary["avg_ms"], 2)
    p95_delta = _round_or_zero(https_summary["p95_ms"] - http_summary["p95_ms"], 2)
    jitter_delta = _round_or_zero(https_summary["jitter_ms"] - http_summary["jitter_ms"], 2)

    if http_summary["avg_ms"] == 0 and https_summary["avg_ms"] == 0:
        faster_protocol = "N/A"
    else:
        faster_protocol = "HTTP" if http_summary["avg_ms"] <= https_summary["avg_ms"] else "HTTPS"

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dashboard": {
            "poll_interval_sec": POLL_INTERVAL_SEC,
            "max_samples": MAX_SAMPLES,
            "uptime_sec": int(time.time() - DASHBOARD_STATE["started_at"]),
            "host": DASHBOARD_HOST,
            "port": DASHBOARD_PORT,
        },
        "targets": {
            "http": endpoints["http"]["target"],
            "https": endpoints["https"]["target"],
            "http_candidates": endpoints["http"]["candidates"],
            "https_candidates": endpoints["https"]["candidates"],
        },
        "timeline": timeline,
        "http": {
            **http_summary,
            "target": endpoints["http"]["target"],
            "failover_hits": endpoints["http"]["failover_hits"],
            "is_up": endpoints["http"]["is_up"],
            "last_error": endpoints["http"]["last_error"],
            "last_status_code": endpoints["http"]["last_status_code"],
            "last_latency_ms": endpoints["http"]["last_latency_ms"],
            "last_check_at": endpoints["http"]["last_check_at"],
        },
        "https": {
            **https_summary,
            "target": endpoints["https"]["target"],
            "failover_hits": endpoints["https"]["failover_hits"],
            "is_up": endpoints["https"]["is_up"],
            "last_error": endpoints["https"]["last_error"],
            "last_status_code": endpoints["https"]["last_status_code"],
            "last_latency_ms": endpoints["https"]["last_latency_ms"],
            "last_check_at": endpoints["https"]["last_check_at"],
        },
        "comparison": {
            "avg_delta_ms": avg_delta,
            "p95_delta_ms": p95_delta,
            "jitter_delta_ms": jitter_delta,
            "faster_protocol": faster_protocol,
        },
        # Backward-compatible keys for existing integrations.
        "http_avg_ms": http_summary["avg_ms"],
        "https_avg_ms": https_summary["avg_ms"],
        "http_samples": http_summary["samples"],
        "https_samples": https_summary["samples"],
        "http_status": {
            "ok": endpoints["http"]["is_up"],
            "last_error": endpoints["http"]["last_error"],
            "last_status_code": endpoints["http"]["last_status_code"],
        },
        "https_status": {
            "ok": endpoints["https"]["is_up"],
            "last_error": endpoints["https"]["last_error"],
            "last_status_code": endpoints["https"]["last_status_code"],
        },
        "http_target": endpoints["http"]["target"],
        "https_target": endpoints["https"]["target"],
    }

    return payload


DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>CCEN356 Performance Command Center</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Source+Code+Pro:wght@500;600&display=swap" rel="stylesheet" />
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --bg-a: #09162b;
            --bg-b: #050b16;
            --surface: #101b2d;
            --surface-soft: #15243a;
            --ink-strong: #e8efff;
            --ink-mid: #9eb1cb;
            --line: #233956;
            --http: #4ca5ff;
            --https: #38d7a3;
            --accent: #ffb44d;
            --danger: #ff7b72;
            --ok: #4dd6a0;
            --shadow: 0 18px 36px rgba(2, 8, 18, 0.45);
        }

        * { box-sizing: border-box; }

        body {
            margin: 0;
            min-height: 100vh;
            font-family: "Space Grotesk", "Trebuchet MS", sans-serif;
            color: var(--ink-strong);
            background: radial-gradient(circle at 14% 12%, rgba(32, 105, 186, 0.38) 0%, transparent 35%),
                        radial-gradient(circle at 88% 4%, rgba(14, 178, 138, 0.18) 0%, transparent 30%),
                        linear-gradient(160deg, var(--bg-a) 0%, var(--bg-b) 100%);
            padding: 24px;
        }

        .shell {
            max-width: 1400px;
            margin: 0 auto;
            display: grid;
            gap: 18px;
            animation: fade-slide 700ms ease-out;
        }

        .panel {
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: 18px;
            box-shadow: var(--shadow);
            padding: 18px;
        }

        .hero {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 14px;
            align-items: center;
        }

        .title {
            margin: 0;
            font-size: clamp(1.5rem, 2.2vw, 2.3rem);
            letter-spacing: 0.02em;
        }

        .subtitle {
            margin: 8px 0 0;
            color: var(--ink-mid);
            font-size: 0.98rem;
        }

        .timestamp {
            font-family: "Source Code Pro", Consolas, monospace;
            color: var(--ink-mid);
            text-align: right;
            font-size: 0.93rem;
        }

        .status-strip {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 10px;
        }

        .pill {
            padding: 10px 12px;
            border-radius: 12px;
            border: 1px solid var(--line);
            background: rgba(20, 36, 57, 0.9);
            font-size: 0.86rem;
            color: var(--ink-mid);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .pill strong { color: var(--ink-strong); }

        .kpis {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 12px;
        }

        .kpi {
            border: 1px solid var(--line);
            border-radius: 14px;
            background: linear-gradient(180deg, #13233a, #101c2f);
            padding: 16px;
            min-height: 102px;
        }

        .kpi-label {
            font-size: 0.83rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--ink-mid);
        }

        .kpi-value {
            margin-top: 8px;
            font-size: clamp(1.4rem, 2vw, 2.1rem);
            font-weight: 700;
        }

        .http { color: var(--http); }
        .https { color: var(--https); }
        .accent { color: var(--accent); }

        .grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 14px;
        }

        .chart-wrap {
            min-height: 280px;
        }

        .chart-title {
            margin: 0 0 10px;
            font-size: 0.95rem;
            letter-spacing: 0.03em;
            color: var(--ink-mid);
            text-transform: uppercase;
        }

        .endpoint-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.92rem;
        }

        .endpoint-table th,
        .endpoint-table td {
            padding: 10px 8px;
            border-bottom: 1px solid var(--line);
            text-align: left;
            vertical-align: top;
        }

        .endpoint-table th {
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--ink-mid);
        }

        .badge {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 999px;
            font-weight: 700;
            font-size: 0.78rem;
        }

        .badge-ok {
            background: rgba(77, 214, 160, 0.16);
            color: var(--ok);
            border: 1px solid rgba(77, 214, 160, 0.38);
        }

        .badge-down {
            background: rgba(255, 123, 114, 0.12);
            color: var(--danger);
            border: 1px solid rgba(255, 123, 114, 0.35);
        }

        .codeish {
            font-family: "Source Code Pro", Consolas, monospace;
            font-size: 0.82rem;
            color: var(--ink-mid);
        }

        .alert-box {
            border: 1px dashed #3a5d86;
            background: rgba(18, 31, 50, 0.95);
            border-radius: 12px;
            padding: 12px;
            color: #c8daef;
            font-size: 0.89rem;
        }

        @keyframes fade-slide {
            from {
                opacity: 0;
                transform: translateY(14px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        @media (max-width: 1100px) {
            .hero,
            .kpis,
            .grid,
            .status-strip {
                grid-template-columns: 1fr 1fr;
            }
        }

        @media (max-width: 760px) {
            body { padding: 12px; }
            .hero,
            .kpis,
            .grid,
            .status-strip {
                grid-template-columns: 1fr;
            }
            .timestamp { text-align: left; }
            .panel { padding: 14px; }
        }
    </style>
</head>
<body>
    <main class="shell">
        <section class="panel hero">
            <div>
                <h1 class="title">CCEN356 Performance Command Center</h1>
                <p class="subtitle">Real-time HTTP/HTTPS observability for benchmark runs and live lab demos.</p>
            </div>
            <div>
                <div class="timestamp" id="clock">Loading...</div>
            </div>
        </section>

        <section class="panel status-strip">
            <div class="pill"><strong>HTTP Target:</strong> <span id="httpTarget">-</span></div>
            <div class="pill"><strong>HTTPS Target:</strong> <span id="httpsTarget">-</span></div>
            <div class="pill"><strong>Poll Interval:</strong> <span id="pollRate">-</span></div>
            <div class="pill"><strong>Dashboard Uptime:</strong> <span id="dashUptime">-</span></div>
        </section>

        <section class="panel kpis">
            <article class="kpi">
                <div class="kpi-label">HTTP Average Latency</div>
                <div class="kpi-value http" id="httpAvg">0.0 ms</div>
            </article>
            <article class="kpi">
                <div class="kpi-label">HTTPS Average Latency</div>
                <div class="kpi-value https" id="httpsAvg">0.0 ms</div>
            </article>
            <article class="kpi">
                <div class="kpi-label">TLS Overhead Delta</div>
                <div class="kpi-value accent" id="deltaAvg">0.0 ms</div>
            </article>
            <article class="kpi">
                <div class="kpi-label">Fastest Protocol</div>
                <div class="kpi-value" id="fastestProtocol">N/A</div>
            </article>
        </section>

        <section class="grid">
            <article class="panel chart-wrap">
                <h3 class="chart-title">Latency Timeline</h3>
                <canvas id="latencyChart"></canvas>
            </article>
            <article class="panel chart-wrap">
                <h3 class="chart-title">Average vs Tail Latency</h3>
                <canvas id="percentileChart"></canvas>
            </article>
            <article class="panel chart-wrap">
                <h3 class="chart-title">Reliability and Failures</h3>
                <canvas id="reliabilityChart"></canvas>
            </article>
            <article class="panel chart-wrap">
                <h3 class="chart-title">Performance Profile Score</h3>
                <canvas id="scoreChart"></canvas>
            </article>
        </section>

        <section class="panel">
            <h3 class="chart-title">Endpoint Status Matrix</h3>
            <table class="endpoint-table">
                <thead>
                    <tr>
                        <th>Protocol</th>
                        <th>Live Status</th>
                        <th>Target</th>
                        <th>Last Check</th>
                        <th>Status Code</th>
                        <th>Last Latency</th>
                        <th>Uptime</th>
                        <th>Checks / Failures</th>
                        <th>Last Error</th>
                    </tr>
                </thead>
                <tbody id="statusRows"></tbody>
            </table>
        </section>

        <section class="panel alert-box" id="noteBox">
            Waiting for first samples...
        </section>
    </main>

    <script>
        const palette = {
            http: '#4ca5ff',
            https: '#38d7a3',
            accent: '#ffb44d',
            ink: '#e8efff',
            muted: '#9eb1cb',
            grid: 'rgba(65, 93, 128, 0.45)'
        };

        const chartLibraryAvailable = typeof Chart !== 'undefined';

        if (!chartLibraryAvailable) {
            document.querySelectorAll('.chart-wrap').forEach((panel) => {
                const canvas = panel.querySelector('canvas');
                if (canvas) {
                    canvas.style.display = 'none';
                }
                const hint = document.createElement('p');
                hint.className = 'codeish';
                hint.textContent = 'Chart.js unavailable (offline/CDN blocked). Metrics table and KPI cards remain live.';
                panel.appendChild(hint);
            });
        }

        const latencyChart = chartLibraryAvailable ? new Chart(document.getElementById('latencyChart'), {
            type: 'line',
            data: {
                labels: [],
                datasets: [
                    {
                        label: 'HTTP (ms)',
                        data: [],
                        borderColor: palette.http,
                        backgroundColor: 'rgba(76, 165, 255, 0.18)',
                        pointRadius: 2,
                        tension: 0.28,
                        spanGaps: true,
                    },
                    {
                        label: 'HTTPS (ms)',
                        data: [],
                        borderColor: palette.https,
                        backgroundColor: 'rgba(56, 215, 163, 0.18)',
                        pointRadius: 2,
                        tension: 0.28,
                        spanGaps: true,
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { labels: { color: palette.ink } } },
                scales: {
                    x: { ticks: { color: palette.muted, maxTicksLimit: 12 }, grid: { color: palette.grid } },
                    y: { beginAtZero: true, ticks: { color: palette.muted }, grid: { color: palette.grid } }
                }
            }
        }) : null;

        const percentileChart = chartLibraryAvailable ? new Chart(document.getElementById('percentileChart'), {
            type: 'bar',
            data: {
                labels: ['Average', 'P95', 'P99'],
                datasets: [
                    { label: 'HTTP', data: [0, 0, 0], backgroundColor: 'rgba(76, 165, 255, 0.8)' },
                    { label: 'HTTPS', data: [0, 0, 0], backgroundColor: 'rgba(56, 215, 163, 0.8)' }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { labels: { color: palette.ink } } },
                scales: {
                    x: { ticks: { color: palette.muted }, grid: { color: palette.grid } },
                    y: { beginAtZero: true, ticks: { color: palette.muted }, grid: { color: palette.grid } }
                }
            }
        }) : null;

        const reliabilityChart = chartLibraryAvailable ? new Chart(document.getElementById('reliabilityChart'), {
            data: {
                labels: ['HTTP', 'HTTPS'],
                datasets: [
                    {
                        type: 'bar',
                        label: 'Uptime %',
                        data: [0, 0],
                        backgroundColor: ['rgba(76, 165, 255, 0.82)', 'rgba(56, 215, 163, 0.82)'],
                        yAxisID: 'uptimeAxis',
                    },
                    {
                        type: 'line',
                        label: 'Failures',
                        data: [0, 0],
                        borderColor: '#ff7b72',
                        backgroundColor: '#ff7b72',
                        yAxisID: 'failureAxis',
                        tension: 0.1,
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { labels: { color: palette.ink } } },
                scales: {
                    uptimeAxis: {
                        position: 'left',
                        min: 0,
                        max: 100,
                        ticks: { color: palette.muted },
                        grid: { color: palette.grid }
                    },
                    failureAxis: {
                        position: 'right',
                        beginAtZero: true,
                        ticks: { color: palette.muted },
                        grid: { drawOnChartArea: false }
                    },
                    x: { ticks: { color: palette.muted }, grid: { color: palette.grid } }
                }
            }
        }) : null;

        const scoreChart = chartLibraryAvailable ? new Chart(document.getElementById('scoreChart'), {
            type: 'radar',
            data: {
                labels: ['Latency', 'Tail', 'Jitter', 'Availability', 'Consistency'],
                datasets: [
                    {
                        label: 'HTTP score',
                        data: [0, 0, 0, 0, 0],
                        borderColor: palette.http,
                        backgroundColor: 'rgba(76, 165, 255, 0.22)',
                    },
                    {
                        label: 'HTTPS score',
                        data: [0, 0, 0, 0, 0],
                        borderColor: palette.https,
                        backgroundColor: 'rgba(56, 215, 163, 0.22)',
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    r: {
                        min: 0,
                        max: 100,
                        ticks: { color: palette.muted, backdropColor: 'rgba(16, 27, 45, 0.7)' },
                        angleLines: { color: palette.grid },
                        grid: { color: palette.grid },
                        pointLabels: { color: palette.muted },
                    }
                },
                plugins: { legend: { labels: { color: palette.ink } } }
            }
        }) : null;

        const toFixedSafe = (value, digits = 1) => Number.isFinite(value) ? value.toFixed(digits) : '0.0';

        function formatDuration(seconds) {
            const total = Math.max(0, Math.floor(seconds || 0));
            const h = Math.floor(total / 3600);
            const m = Math.floor((total % 3600) / 60);
            const s = total % 60;
            return `${h}h ${m}m ${s}s`;
        }

        function protocolBadge(isUp) {
            if (isUp) {
                return '<span class="badge badge-ok">UP</span>';
            }
            return '<span class="badge badge-down">DOWN</span>';
        }

        function fillStatusTable(data) {
            const rows = [
                { label: 'HTTP', payload: data.http },
                { label: 'HTTPS', payload: data.https },
            ];
            const tbody = document.getElementById('statusRows');
            tbody.innerHTML = rows.map(row => {
                const p = row.payload;
                const errorText = p.last_error && p.last_error.trim() ? p.last_error : 'none';
                const statusCode = p.last_status_code === null ? '-' : p.last_status_code;
                const lastLatency = p.last_latency_ms === null ? '-' : `${toFixedSafe(p.last_latency_ms, 2)} ms`;
                const checks = `${p.checks} / ${p.failures}`;
                return `
                    <tr>
                        <td><strong>${row.label}</strong></td>
                        <td>${protocolBadge(p.is_up)}</td>
                        <td class="codeish">${p.target}</td>
                        <td>${p.last_check_at || '-'}</td>
                        <td>${statusCode}</td>
                        <td>${lastLatency}</td>
                        <td>${toFixedSafe(p.uptime_pct, 1)}%</td>
                        <td>${checks}</td>
                        <td class="codeish">${errorText}</td>
                    </tr>
                `;
            }).join('');
        }

        function updateNote(data) {
            const note = document.getElementById('noteBox');
            if (!data.http.is_up || !data.https.is_up) {
                const httpTried = (data.targets.http_candidates || []).join(', ');
                const httpsTried = (data.targets.https_candidates || []).join(', ');
                note.textContent = `One or more targets are down. HTTP tried: [${httpTried}] | HTTPS tried: [${httpsTried}]`;
                return;
            }
            note.textContent = `Both targets are reachable. Current avg delta (HTTPS - HTTP): ${toFixedSafe(data.comparison.avg_delta_ms, 2)} ms.`;
        }

        function updateDashboard(data) {
            document.getElementById('clock').textContent = `Last refresh: ${data.generated_at}`;
            document.getElementById('httpTarget').textContent = data.targets.http;
            document.getElementById('httpsTarget').textContent = data.targets.https;
            document.getElementById('pollRate').textContent = `${toFixedSafe(data.dashboard.poll_interval_sec, 1)}s`;
            document.getElementById('dashUptime').textContent = formatDuration(data.dashboard.uptime_sec);

            document.getElementById('httpAvg').textContent = `${toFixedSafe(data.http.avg_ms, 1)} ms`;
            document.getElementById('httpsAvg').textContent = `${toFixedSafe(data.https.avg_ms, 1)} ms`;
            document.getElementById('deltaAvg').textContent = `${toFixedSafe(data.comparison.avg_delta_ms, 1)} ms`;
            document.getElementById('fastestProtocol').textContent = data.comparison.faster_protocol;

            if (latencyChart) {
                latencyChart.data.labels = data.timeline.labels;
                latencyChart.data.datasets[0].data = data.timeline.http_ms;
                latencyChart.data.datasets[1].data = data.timeline.https_ms;
                latencyChart.update();
            }

            if (percentileChart) {
                percentileChart.data.datasets[0].data = [data.http.avg_ms, data.http.p95_ms, data.http.p99_ms];
                percentileChart.data.datasets[1].data = [data.https.avg_ms, data.https.p95_ms, data.https.p99_ms];
                percentileChart.update();
            }

            if (reliabilityChart) {
                reliabilityChart.data.datasets[0].data = [data.http.uptime_pct, data.https.uptime_pct];
                reliabilityChart.data.datasets[1].data = [data.http.failures, data.https.failures];
                reliabilityChart.update();
            }

            if (scoreChart) {
                const httpScore = data.http.profile_scores;
                const httpsScore = data.https.profile_scores;
                scoreChart.data.datasets[0].data = [
                    httpScore.latency,
                    httpScore.tail,
                    httpScore.jitter,
                    httpScore.availability,
                    httpScore.consistency,
                ];
                scoreChart.data.datasets[1].data = [
                    httpsScore.latency,
                    httpsScore.tail,
                    httpsScore.jitter,
                    httpsScore.availability,
                    httpsScore.consistency,
                ];
                scoreChart.update();
            }

            fillStatusTable(data);
            updateNote(data);
        }

        async function fetchMetrics() {
            try {
                const response = await fetch('/api/metrics');
                const payload = await response.json();
                updateDashboard(payload);
            } catch (error) {
                document.getElementById('noteBox').textContent = `Failed to fetch metrics: ${error}`;
            }
        }

        fetchMetrics();
        setInterval(fetchMetrics, 3000);
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/metrics")
def metrics_api():
    return jsonify(_build_payload())


@app.route("/api/health")
def health_api():
    payload = _build_payload()
    healthy = payload["http"]["is_up"] or payload["https"]["is_up"]
    return jsonify({"ok": healthy, "generated_at": payload["generated_at"]})


if __name__ == "__main__":
    collector = threading.Thread(target=background_collector, daemon=True)
    collector.start()

    print(f"Dashboard listening on http://{DASHBOARD_HOST}:{DASHBOARD_PORT}")
    print(f"Monitoring targets: HTTP={HTTP_TARGET} HTTPS={HTTPS_TARGET}")
    print(f"HTTP candidates: {', '.join(HTTP_CANDIDATES)}")
    print(f"HTTPS candidates: {', '.join(HTTPS_CANDIDATES)}")
    print(f"Poll interval: {POLL_INTERVAL_SEC}s | Timeout: {REQUEST_TIMEOUT_SEC}s")

    app.run(host=DASHBOARD_HOST, port=DASHBOARD_PORT, debug=False)
