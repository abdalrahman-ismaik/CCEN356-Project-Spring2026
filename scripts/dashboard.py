"""
Script 5 - Flask Live Dashboard (Advanced)

Professional real-time dashboard for HTTP/HTTPS monitoring.
Recommended run location: Server PC (so all clients can open it).

Examples:
    python scripts/dashboard.py
    set CCEN356_DASHBOARD_PORT=5000 && python scripts/dashboard.py
"""

from collections import deque
from concurrent.futures import ThreadPoolExecutor
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
POLL_INTERVAL_SEC = float(os.getenv("CCEN356_POLL_INTERVAL_SEC", "0.1"))
REQUEST_TIMEOUT_SEC = float(os.getenv("CCEN356_REQUEST_TIMEOUT_SEC", "1.5"))
MAX_SAMPLES = int(os.getenv("CCEN356_DASHBOARD_MAX_SAMPLES", "240"))
ML_FORECAST_HORIZON = max(1, int(os.getenv("CCEN356_ML_FORECAST_HORIZON", "5")))
ML_MIN_POINTS = max(4, int(os.getenv("CCEN356_ML_MIN_POINTS", "8")))
ML_HIGH_LATENCY_MS = max(1.0, float(os.getenv("CCEN356_ML_HIGH_LATENCY_MS", "120")))
ML_HIGH_JITTER_MS = max(0.5, float(os.getenv("CCEN356_ML_HIGH_JITTER_MS", "20")))

QOS_MODE_HEADER = os.getenv("CCEN356_QOS_MODE_HEADER", "X-CCEN356-QOS-MODE")
QOS_MODE_VALUE = os.getenv("CCEN356_QOS_MODE_VALUE", "on")
DEFAULT_VIEW_MODE = os.getenv("CCEN356_DASHBOARD_VIEW_MODE", "without_qos").strip().lower()

DASHBOARD_MODES = {
    "without_qos": {
        "label": "Without QoS",
        "qos_enabled": False,
    },
    "with_qos": {
        "label": "With QoS",
        "qos_enabled": True,
    },
}

if DEFAULT_VIEW_MODE not in DASHBOARD_MODES:
    DEFAULT_VIEW_MODE = "without_qos"


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

    # If the dashboard runs on the same server as the monitored endpoints, loopback
    # addresses are often the most reliable way to reach the local Flask servers.
    add_candidate("127.0.0.1", port=None)
    add_candidate("localhost", port=None)

    add_candidate(host, port=None)
    for port in candidate_ports:
        add_candidate(host, port=port)

    return candidates


HTTP_FALLBACK_PORTS = _safe_parse_ports(
    os.getenv("CCEN356_HTTP_FALLBACK_PORTS", "80"),
    defaults=[80],
)
HTTPS_FALLBACK_PORTS = _safe_parse_ports(
    os.getenv("CCEN356_HTTPS_FALLBACK_PORTS", "443"),
    defaults=[443, 8443],
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


def _new_profile_state():
    return {
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


METRICS_LOCK = threading.Lock()
PROBE_EXECUTOR = ThreadPoolExecutor(max_workers=max(4, len(DASHBOARD_MODES) * 2))
DASHBOARD_STATE = {
    "started_at": time.time(),
    "profiles": {
        key: _new_profile_state() for key in DASHBOARD_MODES
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


def _clamp(value, lower, upper):
    return max(lower, min(upper, value))


def _clean_numeric(values):
    return [float(v) for v in values if v is not None and not math.isnan(v)]


def _linear_forecast(values, horizon):
    cleaned = _clean_numeric(values)
    if not cleaned:
        return [0.0] * horizon, 0.0, 0.0
    if len(cleaned) == 1:
        return [cleaned[0]] * horizon, 0.0, 0.2

    n = len(cleaned)
    xs = list(range(n))
    mean_x = (n - 1) / 2.0
    mean_y = sum(cleaned) / n

    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, cleaned))
    denominator = sum((x - mean_x) ** 2 for x in xs)
    slope = numerator / denominator if denominator else 0.0
    intercept = mean_y - (slope * mean_x)

    forecast = []
    for step in range(1, horizon + 1):
        x = n - 1 + step
        forecast.append(max(0.0, (slope * x) + intercept))

    volatility = statistics.stdev(cleaned) if len(cleaned) > 1 else 0.0
    confidence = 1.0 / (1.0 + (volatility / max(mean_y, 1.0)))
    confidence = _clamp(confidence, 0.2, 0.98)

    return forecast, slope, confidence


def _protocol_ml_analysis(label, endpoint_summary, endpoint_snapshot):
    history = endpoint_snapshot.get("latencies", [])[-60:]
    forecast, slope, confidence = _linear_forecast(history, ML_FORECAST_HORIZON)
    predicted_next = forecast[0] if forecast else 0.0

    trend = "stable"
    if slope > 0.6:
        trend = "degrading"
    elif slope < -0.6:
        trend = "improving"

    checks = endpoint_summary.get("checks", 0)
    failures = endpoint_summary.get("failures", 0)
    failure_rate = (failures / checks * 100.0) if checks else 0.0

    risk_score = 0.0
    issues = []

    if endpoint_summary.get("p95_ms", 0.0) >= ML_HIGH_LATENCY_MS:
        risk_score += 35
        issues.append(f"{label} tail latency above {ML_HIGH_LATENCY_MS:.0f}ms")
    if endpoint_summary.get("jitter_ms", 0.0) >= ML_HIGH_JITTER_MS:
        risk_score += 20
        issues.append(f"{label} jitter above {ML_HIGH_JITTER_MS:.0f}ms")
    if failure_rate >= 5.0:
        risk_score += 30
        issues.append(f"{label} failure rate >= 5%")
    elif failure_rate > 0.0:
        risk_score += 15
        issues.append(f"{label} has intermittent failures")
    if trend == "degrading":
        risk_score += 20
        issues.append(f"{label} trend is degrading")

    baseline = endpoint_summary.get("avg_ms", 0.0)
    if baseline > 0 and predicted_next >= (baseline * 1.2):
        risk_score += 10
        issues.append(f"{label} next sample predicted above current baseline")

    risk_score = _clamp(risk_score, 0.0, 100.0)

    if risk_score >= 75:
        risk_level = "critical"
    elif risk_score >= 50:
        risk_level = "high"
    elif risk_score >= 25:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "trend": trend,
        "slope_ms_per_sample": _round_or_zero(slope, 3),
        "confidence": _round_or_zero(confidence * 100.0, 1),
        "predicted_next_ms": _round_or_zero(predicted_next, 2),
        "forecast_ms": [_round_or_zero(v, 2) for v in forecast],
        "risk_score": _round_or_zero(risk_score, 1),
        "risk_level": risk_level,
        "issue_predicted": risk_score >= 50.0,
        "issues": issues,
    }


def _ml_analysis(http_summary, https_summary, endpoint_snapshot):
    http_ml = _protocol_ml_analysis("HTTP", http_summary, endpoint_snapshot["http"])
    https_ml = _protocol_ml_analysis("HTTPS", https_summary, endpoint_snapshot["https"])

    combined_risk = _round_or_zero(max(http_ml["risk_score"], https_ml["risk_score"]), 1)
    risk_shift = _round_or_zero(https_ml["predicted_next_ms"] - http_ml["predicted_next_ms"], 2)

    summary = (
        f"Forecast next latency: HTTP {http_ml['predicted_next_ms']}ms, "
        f"HTTPS {https_ml['predicted_next_ms']}ms."
    )
    if http_ml["issue_predicted"] or https_ml["issue_predicted"]:
        summary += " Potential performance issue detected; review jitter/tail latency and failure spikes."
    else:
        summary += " No immediate performance issue predicted."

    return {
        "http": http_ml,
        "https": https_ml,
        "combined_risk": combined_risk,
        "predicted_delta_ms": risk_shift,
        "summary": summary,
    }


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


def _probe_target(url, verify_tls, qos_enabled):
    start = time.perf_counter()
    try:
        headers = {QOS_MODE_HEADER: QOS_MODE_VALUE} if qos_enabled else None
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SEC, verify=verify_tls, headers=headers)
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


def _probe_endpoint(endpoint_state, qos_enabled):
    """Probe the active target first, then fallback candidates until one succeeds."""
    ordered_candidates = [endpoint_state["target"]] + [
        url for url in endpoint_state["candidates"] if url != endpoint_state["target"]
    ]

    errors = []
    for index, candidate in enumerate(ordered_candidates):
        result = _probe_target(candidate, verify_tls=endpoint_state["verify_tls"], qos_enabled=qos_enabled)
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
    """Continuously probe baseline and QoS-priority profiles for HTTP/HTTPS targets."""
    while True:
        timestamp_label = datetime.now().strftime("%H:%M:%S")
        future_map = {}
        for mode_key, mode_meta in DASHBOARD_MODES.items():
            profile = DASHBOARD_STATE["profiles"][mode_key]
            for protocol_key in ("http", "https"):
                future_map[(mode_key, protocol_key)] = PROBE_EXECUTOR.submit(
                    _probe_endpoint,
                    profile["endpoints"][protocol_key],
                    mode_meta["qos_enabled"],
                )

        cycle = {
            key: future_map[key].result() for key in future_map
        }

        with METRICS_LOCK:
            for mode_key in DASHBOARD_MODES:
                profile = DASHBOARD_STATE["profiles"][mode_key]
                profile["timeline"]["labels"].append(timestamp_label)
                profile["timeline"]["http_ms"].append(cycle[(mode_key, "http")]["latency_ms"])
                profile["timeline"]["https_ms"].append(cycle[(mode_key, "https")]["latency_ms"])

                for protocol_key in ("http", "https"):
                    endpoint = profile["endpoints"][protocol_key]
                    result = cycle[(mode_key, protocol_key)]
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
        profiles = {}
        for mode_key, profile in DASHBOARD_STATE["profiles"].items():
            timeline = {
                "labels": list(profile["timeline"]["labels"]),
                "http_ms": [x if x is not None else None for x in profile["timeline"]["http_ms"]],
                "https_ms": [x if x is not None else None for x in profile["timeline"]["https_ms"]],
            }

            endpoints = {}
            for protocol_key, endpoint in profile["endpoints"].items():
                endpoints[protocol_key] = {
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

            profiles[mode_key] = {
                "timeline": timeline,
                "endpoints": endpoints,
            }

    return profiles


def _build_profile_payload(mode_key, profile_snapshot):
    timeline = profile_snapshot["timeline"]
    endpoints = profile_snapshot["endpoints"]

    http_summary = _summarize(endpoints["http"])
    https_summary = _summarize(endpoints["https"])

    avg_delta = _round_or_zero(https_summary["avg_ms"] - http_summary["avg_ms"], 2)
    p95_delta = _round_or_zero(https_summary["p95_ms"] - http_summary["p95_ms"], 2)
    jitter_delta = _round_or_zero(https_summary["jitter_ms"] - http_summary["jitter_ms"], 2)

    if http_summary["avg_ms"] == 0 and https_summary["avg_ms"] == 0:
        faster_protocol = "N/A"
    else:
        faster_protocol = "HTTP" if http_summary["avg_ms"] <= https_summary["avg_ms"] else "HTTPS"

    ml_analysis = _ml_analysis(http_summary, https_summary, endpoints)

    return {
        "mode": mode_key,
        "label": DASHBOARD_MODES[mode_key]["label"],
        "qos_enabled": DASHBOARD_MODES[mode_key]["qos_enabled"],
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
        "ml_analysis": ml_analysis,
    }


def _build_payload():
    profile_snapshots = _snapshot_state()
    profiles = {
        mode_key: _build_profile_payload(mode_key, profile_snapshots[mode_key])
        for mode_key in DASHBOARD_MODES
    }

    without_qos = profiles["without_qos"]
    with_qos = profiles["with_qos"]

    mode_comparison = {
        "http_avg_change_ms": _round_or_zero(with_qos["http"]["avg_ms"] - without_qos["http"]["avg_ms"], 2),
        "https_avg_change_ms": _round_or_zero(with_qos["https"]["avg_ms"] - without_qos["https"]["avg_ms"], 2),
        "delta_shift_ms": _round_or_zero(with_qos["comparison"]["avg_delta_ms"] - without_qos["comparison"]["avg_delta_ms"], 2),
        "combined_risk_shift": _round_or_zero(
            with_qos["ml_analysis"]["combined_risk"] - without_qos["ml_analysis"]["combined_risk"], 2
        ),
        "without_qos_faster_protocol": without_qos["comparison"]["faster_protocol"],
        "with_qos_faster_protocol": with_qos["comparison"]["faster_protocol"],
    }

    active_mode = DEFAULT_VIEW_MODE if DEFAULT_VIEW_MODE in profiles else "without_qos"
    active_profile = profiles[active_mode]

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dashboard": {
            "poll_interval_sec": POLL_INTERVAL_SEC,
            "max_samples": MAX_SAMPLES,
            "uptime_sec": int(time.time() - DASHBOARD_STATE["started_at"]),
            "host": DASHBOARD_HOST,
            "port": DASHBOARD_PORT,
            "default_view_mode": active_mode,
            "available_modes": list(DASHBOARD_MODES.keys()),
            "qos_mode_header": QOS_MODE_HEADER,
            "qos_mode_value": QOS_MODE_VALUE,
        },
        "profiles": profiles,
        "mode_comparison": mode_comparison,
        "targets": active_profile["targets"],
        "timeline": active_profile["timeline"],
        "http": active_profile["http"],
        "https": active_profile["https"],
        "comparison": active_profile["comparison"],
        "ml_analysis": active_profile["ml_analysis"],
        # Backward-compatible keys for existing integrations.
        "http_avg_ms": active_profile["http"]["avg_ms"],
        "https_avg_ms": active_profile["https"]["avg_ms"],
        "http_samples": active_profile["http"]["samples"],
        "https_samples": active_profile["https"]["samples"],
        "http_status": {
            "ok": active_profile["http"]["is_up"],
            "last_error": active_profile["http"]["last_error"],
            "last_status_code": active_profile["http"]["last_status_code"],
        },
        "https_status": {
            "ok": active_profile["https"]["is_up"],
            "last_error": active_profile["https"]["last_error"],
            "last_status_code": active_profile["https"]["last_status_code"],
        },
        "http_target": active_profile["http"]["target"],
        "https_target": active_profile["https"]["target"],
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

        .hero-tools {
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 10px;
        }

        .mode-toggle {
            display: inline-flex;
            align-items: center;
            gap: 10px;
            border: 1px solid var(--line);
            border-radius: 999px;
            background: rgba(20, 36, 57, 0.9);
            padding: 8px 12px;
            color: var(--ink-mid);
            font-size: 0.85rem;
        }

        .mode-toggle input {
            accent-color: var(--https);
            width: 16px;
            height: 16px;
        }

        .mode-toggle strong {
            color: var(--ink-strong);
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
            display: flex;
            flex-direction: column;
            gap: 10px;
            min-height: 320px;
            height: 320px;
            overflow: hidden;
        }

        .chart-wrap canvas {
            display: block;
            width: 100% !important;
            height: 100% !important;
            max-width: 100%;
            max-height: 100%;
            min-height: 0;
            flex: 1 1 auto;
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
            .chart-wrap {
                height: 300px;
                min-height: 300px;
            }
            .hero-tools { align-items: flex-start; }
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
            <div class="hero-tools">
                <label class="mode-toggle" for="qosModeToggle">
                    <input type="checkbox" id="qosModeToggle" />
                    <span><strong>QoS Priority Mode</strong> • <span id="qosModeState">Without QoS</span></span>
                </label>
                <div class="timestamp" id="clock">Loading...</div>
            </div>
        </section>

        <section class="panel status-strip">
            <div class="pill"><strong>HTTP Target:</strong> <span id="httpTarget">-</span></div>
            <div class="pill"><strong>HTTPS Target:</strong> <span id="httpsTarget">-</span></div>
            <div class="pill"><strong>View Mode:</strong> <span id="viewMode">-</span></div>
            <div class="pill"><strong>Poll Interval:</strong> <span id="pollRate">-</span></div>
            <div class="pill"><strong>Dashboard Uptime:</strong> <span id="dashUptime">-</span></div>
            <div class="pill"><strong>QoS Impact:</strong> <span id="qosImpact">-</span></div>
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

        <section class="panel status-strip">
            <div class="pill"><strong>ML HTTP Next:</strong> <span id="mlHttpNext">-</span></div>
            <div class="pill"><strong>ML HTTPS Next:</strong> <span id="mlHttpsNext">-</span></div>
            <div class="pill"><strong>ML Risk:</strong> <span id="mlRisk">-</span></div>
            <div class="pill"><strong>ML Trend:</strong> <span id="mlTrend">-</span></div>
        </section>

        <section class="panel alert-box" id="mlSummary">
            ML analysis warming up. Collecting baseline samples for prediction.
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
        const fallbackCanvases = {
            latency: document.getElementById('latencyChart'),
            percentile: document.getElementById('percentileChart'),
            reliability: document.getElementById('reliabilityChart'),
            score: document.getElementById('scoreChart'),
        };

        const modeToggle = document.getElementById('qosModeToggle');
        const modeText = document.getElementById('qosModeState');
        let dashboardModeReady = false;

        if (!chartLibraryAvailable) {
            const note = document.getElementById('noteBox');
            note.textContent = 'Chart.js unavailable from CDN. Using built-in offline canvas renderer with live updates.';
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

        function setupCanvas(canvas) {
            const dpr = window.devicePixelRatio || 1;
            const rect = canvas.getBoundingClientRect();
            const width = Math.max(280, rect.width || 280);
            const height = Math.max(220, rect.height || 260);
            canvas.width = Math.floor(width * dpr);
            canvas.height = Math.floor(height * dpr);
            const ctx = canvas.getContext('2d');
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            ctx.clearRect(0, 0, width, height);
            ctx.fillStyle = '#0f1b2f';
            ctx.fillRect(0, 0, width, height);
            return { ctx, width, height };
        }

        function drawPlotArea(ctx, width, height, maxY, yTicks = 4) {
            const plot = {
                left: 42,
                right: width - 12,
                top: 16,
                bottom: height - 26,
            };
            const plotW = Math.max(1, plot.right - plot.left);
            const plotH = Math.max(1, plot.bottom - plot.top);

            ctx.strokeStyle = palette.grid;
            ctx.lineWidth = 1;
            ctx.beginPath();
            for (let i = 0; i <= yTicks; i++) {
                const y = plot.bottom - (plotH * (i / yTicks));
                ctx.moveTo(plot.left, y);
                ctx.lineTo(plot.right, y);
            }
            ctx.stroke();

            ctx.fillStyle = palette.muted;
            ctx.font = '11px "Source Code Pro", Consolas, monospace';
            for (let i = 0; i <= yTicks; i++) {
                const y = plot.bottom - (plotH * (i / yTicks));
                const value = ((maxY * i) / yTicks).toFixed(0);
                ctx.fillText(value, 6, y + 3);
            }

            return { plot, plotW, plotH };
        }

        function toY(value, maxY, plot) {
            const normalized = maxY > 0 ? (value / maxY) : 0;
            return plot.bottom - (Math.max(0, Math.min(1, normalized)) * (plot.bottom - plot.top));
        }

        function drawSeries(ctx, values, color, maxY, plot) {
            let started = false;
            const stepX = values.length > 1 ? (plot.right - plot.left) / (values.length - 1) : 0;
            ctx.strokeStyle = color;
            ctx.lineWidth = 2;
            ctx.beginPath();
            values.forEach((raw, idx) => {
                if (raw === null || raw === undefined || Number.isNaN(raw)) {
                    started = false;
                    return;
                }
                const x = plot.left + stepX * idx;
                const y = toY(raw, maxY, plot);
                if (!started) {
                    ctx.moveTo(x, y);
                    started = true;
                } else {
                    ctx.lineTo(x, y);
                }
            });
            ctx.stroke();
        }

        function renderLatencyFallback(data) {
            const canvas = fallbackCanvases.latency;
            const { ctx, width, height } = setupCanvas(canvas);
            const values = [...(data.timeline.http_ms || []), ...(data.timeline.https_ms || [])].filter(v => Number.isFinite(v));
            const maxY = Math.max(10, ...values, 0) * 1.2;
            const { plot } = drawPlotArea(ctx, width, height, maxY, 5);
            drawSeries(ctx, data.timeline.http_ms || [], palette.http, maxY, plot);
            drawSeries(ctx, data.timeline.https_ms || [], palette.https, maxY, plot);
        }

        function renderPercentileFallback(data) {
            const canvas = fallbackCanvases.percentile;
            const { ctx, width, height } = setupCanvas(canvas);
            const httpVals = [data.http.avg_ms, data.http.p95_ms, data.http.p99_ms].map(v => Number(v) || 0);
            const httpsVals = [data.https.avg_ms, data.https.p95_ms, data.https.p99_ms].map(v => Number(v) || 0);
            const maxY = Math.max(10, ...httpVals, ...httpsVals) * 1.2;
            const { plot, plotW, plotH } = drawPlotArea(ctx, width, height, maxY, 5);

            const categories = 3;
            const groupW = plotW / categories;
            const barW = Math.max(8, Math.min(20, (groupW - 14) / 2));
            const labels = ['AVG', 'P95', 'P99'];
            for (let i = 0; i < categories; i++) {
                const gx = plot.left + i * groupW + (groupW / 2);
                const h1 = (httpVals[i] / maxY) * plotH;
                const h2 = (httpsVals[i] / maxY) * plotH;
                ctx.fillStyle = 'rgba(76,165,255,0.82)';
                ctx.fillRect(gx - barW - 2, plot.bottom - h1, barW, h1);
                ctx.fillStyle = 'rgba(56,215,163,0.82)';
                ctx.fillRect(gx + 2, plot.bottom - h2, barW, h2);
                ctx.fillStyle = palette.muted;
                ctx.font = '11px "Source Code Pro", Consolas, monospace';
                ctx.fillText(labels[i], gx - 12, plot.bottom + 14);
            }
        }

        function renderReliabilityFallback(data) {
            const canvas = fallbackCanvases.reliability;
            const { ctx, width, height } = setupCanvas(canvas);
            const uptimes = [Number(data.http.uptime_pct) || 0, Number(data.https.uptime_pct) || 0];
            const failures = [Number(data.http.failures) || 0, Number(data.https.failures) || 0];
            const maxFailures = Math.max(1, ...failures);
            const { plot, plotW, plotH } = drawPlotArea(ctx, width, height, 100, 5);

            const x1 = plot.left + plotW * 0.25;
            const x2 = plot.left + plotW * 0.75;
            const barW = Math.max(20, Math.min(44, plotW * 0.14));

            [x1, x2].forEach((x, i) => {
                const h = (uptimes[i] / 100) * plotH;
                ctx.fillStyle = i === 0 ? 'rgba(76,165,255,0.82)' : 'rgba(56,215,163,0.82)';
                ctx.fillRect(x - (barW / 2), plot.bottom - h, barW, h);
                ctx.fillStyle = palette.muted;
                ctx.font = '11px "Source Code Pro", Consolas, monospace';
                ctx.fillText(i === 0 ? 'HTTP' : 'HTTPS', x - 18, plot.bottom + 14);
            });

            ctx.strokeStyle = '#ff7b72';
            ctx.fillStyle = '#ff7b72';
            ctx.lineWidth = 2;
            ctx.beginPath();
            const y1 = plot.bottom - ((failures[0] / maxFailures) * plotH);
            const y2 = plot.bottom - ((failures[1] / maxFailures) * plotH);
            ctx.moveTo(x1, y1);
            ctx.lineTo(x2, y2);
            ctx.stroke();
            ctx.beginPath();
            ctx.arc(x1, y1, 3, 0, Math.PI * 2);
            ctx.arc(x2, y2, 3, 0, Math.PI * 2);
            ctx.fill();

            ctx.fillStyle = palette.muted;
            ctx.font = '11px "Source Code Pro", Consolas, monospace';
            ctx.fillText(`Failures axis max: ${maxFailures}`, plot.left + 4, plot.top + 12);
        }

        function renderScoreFallback(data) {
            const canvas = fallbackCanvases.score;
            const { ctx, width, height } = setupCanvas(canvas);
            const centerX = width / 2;
            const centerY = height / 2;
            const radius = Math.min(width, height) * 0.33;
            const labels = ['Latency', 'Tail', 'Jitter', 'Availability', 'Consistency'];
            const http = data.http.profile_scores || {};
            const https = data.https.profile_scores || {};
            const httpVals = [http.latency, http.tail, http.jitter, http.availability, http.consistency].map(v => Number(v) || 0);
            const httpsVals = [https.latency, https.tail, https.jitter, https.availability, https.consistency].map(v => Number(v) || 0);

            for (let ring = 1; ring <= 5; ring++) {
                const r = (radius * ring) / 5;
                ctx.strokeStyle = palette.grid;
                ctx.beginPath();
                for (let i = 0; i < labels.length; i++) {
                    const angle = (-Math.PI / 2) + ((Math.PI * 2 * i) / labels.length);
                    const x = centerX + Math.cos(angle) * r;
                    const y = centerY + Math.sin(angle) * r;
                    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
                }
                ctx.closePath();
                ctx.stroke();
            }

            labels.forEach((label, i) => {
                const angle = (-Math.PI / 2) + ((Math.PI * 2 * i) / labels.length);
                const x = centerX + Math.cos(angle) * (radius + 18);
                const y = centerY + Math.sin(angle) * (radius + 18);
                ctx.fillStyle = palette.muted;
                ctx.font = '11px "Source Code Pro", Consolas, monospace';
                ctx.fillText(label, x - 22, y + 3);
            });

            function drawRadar(values, stroke, fill) {
                ctx.strokeStyle = stroke;
                ctx.fillStyle = fill;
                ctx.lineWidth = 2;
                ctx.beginPath();
                values.forEach((v, i) => {
                    const angle = (-Math.PI / 2) + ((Math.PI * 2 * i) / labels.length);
                    const r = radius * (Math.max(0, Math.min(100, v)) / 100);
                    const x = centerX + Math.cos(angle) * r;
                    const y = centerY + Math.sin(angle) * r;
                    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
                });
                ctx.closePath();
                ctx.fill();
                ctx.stroke();
            }

            drawRadar(httpVals, palette.http, 'rgba(76,165,255,0.22)');
            drawRadar(httpsVals, palette.https, 'rgba(56,215,163,0.22)');
        }

        function renderFallbackCharts(data) {
            renderLatencyFallback(data);
            renderPercentileFallback(data);
            renderReliabilityFallback(data);
            renderScoreFallback(data);
        }

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

        function selectedModeKey() {
            return modeToggle.checked ? 'with_qos' : 'without_qos';
        }

        function selectedModeLabel(modeKey) {
            return modeKey === 'with_qos' ? 'With QoS' : 'Without QoS';
        }

        function activeProfile(payload) {
            const modeKey = selectedModeKey();
            if (payload.profiles && payload.profiles[modeKey]) {
                return payload.profiles[modeKey];
            }
            return payload;
        }

        function fillStatusTable(profileData) {
            const rows = [
                { label: 'HTTP', payload: profileData.http },
                { label: 'HTTPS', payload: profileData.https },
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

        function updateNote(profileData, payload) {
            const note = document.getElementById('noteBox');
            const modeKey = selectedModeKey();
            const modeLabel = selectedModeLabel(modeKey);

            if (!profileData.http.is_up || !profileData.https.is_up) {
                const httpTried = (profileData.targets.http_candidates || []).join(', ');
                const httpsTried = (profileData.targets.https_candidates || []).join(', ');
                note.textContent = `${modeLabel}: one or more targets are down. HTTP tried: [${httpTried}] | HTTPS tried: [${httpsTried}]`;
                return;
            }

            const shift = Number(payload.mode_comparison && payload.mode_comparison.delta_shift_ms);
            const trend = Number.isFinite(shift)
                ? (shift < 0 ? 'HTTPS gained priority' : (shift > 0 ? 'HTTPS lost priority' : 'no priority shift'))
                : 'no comparison yet';
            note.textContent = `${modeLabel}: avg delta (HTTPS - HTTP) is ${toFixedSafe(profileData.comparison.avg_delta_ms, 2)} ms. QoS shift: ${toFixedSafe(shift, 2)} ms (${trend}).`;
        }

        function updateMlPanel(profileData) {
            const ml = profileData.ml_analysis || {};
            const httpMl = ml.http || {};
            const httpsMl = ml.https || {};

            const httpNext = Number(httpMl.predicted_next_ms);
            const httpsNext = Number(httpsMl.predicted_next_ms);
            const risk = Number(ml.combined_risk);

            document.getElementById('mlHttpNext').textContent = Number.isFinite(httpNext)
                ? `${toFixedSafe(httpNext, 2)} ms`
                : 'n/a';
            document.getElementById('mlHttpsNext').textContent = Number.isFinite(httpsNext)
                ? `${toFixedSafe(httpsNext, 2)} ms`
                : 'n/a';

            const riskText = Number.isFinite(risk)
                ? `${toFixedSafe(risk, 1)} / 100`
                : 'n/a';
            document.getElementById('mlRisk').textContent = riskText;

            const trendText = `HTTP ${httpMl.trend || 'n/a'} • HTTPS ${httpsMl.trend || 'n/a'}`;
            document.getElementById('mlTrend').textContent = trendText;

            const summary = ml.summary || 'ML analysis warming up. Collecting baseline samples for prediction.';
            const mlSummary = document.getElementById('mlSummary');

            const risks = [];
            if (Array.isArray(httpMl.issues) && httpMl.issues.length) {
                risks.push(...httpMl.issues);
            }
            if (Array.isArray(httpsMl.issues) && httpsMl.issues.length) {
                risks.push(...httpsMl.issues);
            }

            if (risks.length > 0) {
                mlSummary.textContent = `${summary} Signals: ${risks.slice(0, 3).join(' | ')}`;
            } else {
                mlSummary.textContent = summary;
            }
        }

        function updateDashboard(payload) {
            window.__lastPayload = payload;

            if (!dashboardModeReady && payload.dashboard && payload.dashboard.default_view_mode) {
                modeToggle.checked = payload.dashboard.default_view_mode === 'with_qos';
                dashboardModeReady = true;
            }

            const modeKey = selectedModeKey();
            const modeLabel = selectedModeLabel(modeKey);
            modeText.textContent = modeLabel;

            const data = activeProfile(payload);

            document.getElementById('clock').textContent = `Last refresh: ${payload.generated_at}`;
            document.getElementById('httpTarget').textContent = data.targets.http;
            document.getElementById('httpsTarget').textContent = data.targets.https;
            document.getElementById('viewMode').textContent = modeLabel;
            document.getElementById('pollRate').textContent = `${toFixedSafe(payload.dashboard.poll_interval_sec, 1)}s`;
            document.getElementById('dashUptime').textContent = formatDuration(payload.dashboard.uptime_sec);

            const deltaShift = Number(payload.mode_comparison && payload.mode_comparison.delta_shift_ms);
            const shiftText = Number.isFinite(deltaShift)
                ? `${toFixedSafe(deltaShift, 2)} ms`
                : 'n/a';
            document.getElementById('qosImpact').textContent = shiftText;

            refreshMs = Math.max(300, Math.round((payload.dashboard.poll_interval_sec || 1) * 1000));

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

            if (!chartLibraryAvailable) {
                renderFallbackCharts(data);
            }

            fillStatusTable(data);
            updateMlPanel(data);
            updateNote(data, payload);
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

        let refreshMs = 500;

        async function runLoop() {
            await fetchMetrics();
            window.setTimeout(runLoop, refreshMs);
        }

        modeToggle.addEventListener('change', () => {
            if (window.__lastPayload) {
                updateDashboard(window.__lastPayload);
            } else {
                modeText.textContent = selectedModeLabel(selectedModeKey());
            }
        });

        runLoop();

        window.addEventListener('resize', () => {
            if (!chartLibraryAvailable && window.__lastPayload) {
                updateDashboard(window.__lastPayload);
            }
        });
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
    print(f"QoS comparison modes: {', '.join(DASHBOARD_MODES.keys())}")
    print(f"QoS probe header: {QOS_MODE_HEADER}={QOS_MODE_VALUE}")

    app.run(host=DASHBOARD_HOST, port=DASHBOARD_PORT, debug=False)
