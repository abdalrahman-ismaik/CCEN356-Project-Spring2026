"""
Script 5 — Flask Live Dashboard

Real-time web dashboard showing HTTP vs HTTPS response times updating every 3 seconds.
Run from Client PC:
    python3 dashboard.py
Then visit http://localhost:5000 in a browser.
"""

from flask import Flask, render_template_string, jsonify
import threading
import time
import requests
import urllib3
import os

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# Shared metrics store (last 100 samples per protocol)
live_metrics = {
    "http": [],
    "https": [],
    "status": {
        "http": {"ok": False, "last_error": "not sampled yet", "last_status_code": None},
        "https": {"ok": False, "last_error": "not sampled yet", "last_status_code": None},
    }
}

HTTP_TARGET = os.getenv("CCEN356_HTTP_URL", "http://192.165.20.79")
HTTPS_TARGET = os.getenv("CCEN356_HTTPS_URL", "https://192.165.20.79")

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Network Traffic Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { font-family: Arial, sans-serif; background: #1a1a2e; color: white; padding: 20px; margin: 0; }
        h1   { text-align: center; color: #e94560; margin-bottom: 5px; }
        .subtitle { text-align: center; color: #aaa; font-size: 14px; margin-bottom: 20px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 20px; }
        .status-bar { margin: 15px 0; padding: 10px 12px; border-radius: 8px; background: #242843; color: #d8d8d8; font-size: 13px; }
        .ok { color: #4CAF50; font-weight: bold; }
        .bad { color: #ff6b6b; font-weight: bold; }
        .card { background: #16213e; border-radius: 10px; padding: 20px; }
        .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-top: 20px; }
        .stat-card { background: #16213e; border-radius: 10px; padding: 15px; text-align: center; }
        .stat-value { font-size: 28px; font-weight: bold; }
        .stat-label { font-size: 12px; color: #aaa; margin-top: 5px; }
        .http-color { color: #2196F3; }
        .https-color { color: #4CAF50; }
        canvas { max-height: 300px; }
    </style>
</head>
<body>
    <h1>HTTP/HTTPS Live Performance Dashboard</h1>
    <p class="subtitle">CCEN356 Project &mdash; Auto-refreshes every 3 seconds</p>
    <div class="status-bar" id="statusBar">Checking server reachability...</div>

    <div class="stats">
        <div class="stat-card">
            <div class="stat-value http-color" id="httpAvg">--</div>
            <div class="stat-label">HTTP Avg Response (ms)</div>
        </div>
        <div class="stat-card">
            <div class="stat-value https-color" id="httpsAvg">--</div>
            <div class="stat-label">HTTPS Avg Response (ms)</div>
        </div>
        <div class="stat-card">
            <div class="stat-value http-color" id="httpSamples">0</div>
            <div class="stat-label">HTTP Samples</div>
        </div>
        <div class="stat-card">
            <div class="stat-value https-color" id="httpsSamples">0</div>
            <div class="stat-label">HTTPS Samples</div>
        </div>
    </div>

    <div class="grid">
        <div class="card"><canvas id="responseChart"></canvas></div>
        <div class="card"><canvas id="throughputChart"></canvas></div>
    </div>

    <script>
        const labels = [];
        const httpData = [], httpsData = [];

        const responseChart = new Chart(document.getElementById('responseChart'), {
            type: 'line',
            data: {
                labels,
                datasets: [
                    { label: 'HTTP (ms)',  data: httpData,  borderColor: '#2196F3', backgroundColor: 'rgba(33,150,243,0.1)', fill: true, tension: 0.3 },
                    { label: 'HTTPS (ms)', data: httpsData, borderColor: '#4CAF50', backgroundColor: 'rgba(76,175,80,0.1)',  fill: true, tension: 0.3 }
                ]
            },
            options: {
                plugins: { title: { display: true, text: 'Response Time (ms)', color: 'white' } },
                scales: {
                    x: { ticks: { color: '#aaa', maxTicksLimit: 10 } },
                    y: { ticks: { color: '#aaa' }, beginAtZero: true }
                }
            }
        });

        async function fetchData() {
            try {
                const res = await fetch('/api/metrics');
                const data = await res.json();
                const now = new Date().toLocaleTimeString();

                labels.push(now);
                if (labels.length > 20) labels.shift();

                httpData.push(data.http_avg_ms);
                if (httpData.length > 20) httpData.shift();

                httpsData.push(data.https_avg_ms);
                if (httpsData.length > 20) httpsData.shift();

                responseChart.update();

                document.getElementById('httpAvg').textContent = data.http_avg_ms.toFixed(1);
                document.getElementById('httpsAvg').textContent = data.https_avg_ms.toFixed(1);
                document.getElementById('httpSamples').textContent = data.http_samples.length;
                document.getElementById('httpsSamples').textContent = data.https_samples.length;

                const httpOk = data.http_status.ok;
                const httpsOk = data.https_status.ok;
                const httpState = httpOk ? '<span class="ok">HTTP OK</span>' : `<span class="bad">HTTP DOWN</span> (${data.http_status.last_error})`;
                const httpsState = httpsOk ? '<span class="ok">HTTPS OK</span>' : `<span class="bad">HTTPS DOWN</span> (${data.https_status.last_error})`;
                document.getElementById('statusBar').innerHTML = `${httpState} | ${httpsState}`;
            } catch (e) {
                console.error('Failed to fetch metrics:', e);
            }
        }
        setInterval(fetchData, 3000);
        fetchData();
    </script>
</body>
</html>
"""


def background_collector():
    """Background thread that continuously pings HTTP and HTTPS servers."""
    targets = [
        (HTTP_TARGET, "http"),
        (HTTPS_TARGET, "https"),
    ]
    while True:
        for url, key in targets:
            try:
                start = time.time()
                r = requests.get(url, timeout=5, verify=False)
                elapsed = (time.time() - start) * 1000
                live_metrics[key].append(round(elapsed, 2))
                if len(live_metrics[key]) > 100:
                    live_metrics[key].pop(0)
                live_metrics["status"][key]["ok"] = True
                live_metrics["status"][key]["last_status_code"] = r.status_code
                live_metrics["status"][key]["last_error"] = ""
            except Exception as e:
                live_metrics["status"][key]["ok"] = False
                live_metrics["status"][key]["last_status_code"] = None
                live_metrics["status"][key]["last_error"] = str(e)
        time.sleep(3)


@app.route('/')
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route('/api/metrics')
def metrics_api():
    def avg(lst):
        return round(sum(lst) / len(lst), 2) if lst else 0

    return jsonify({
        "http_avg_ms": avg(live_metrics["http"]),
        "https_avg_ms": avg(live_metrics["https"]),
        "http_samples": live_metrics["http"][-20:],
        "https_samples": live_metrics["https"][-20:],
        "http_status": live_metrics["status"]["http"],
        "https_status": live_metrics["status"]["https"],
        "http_target": HTTP_TARGET,
        "https_target": HTTPS_TARGET,
    })


if __name__ == '__main__':
    t = threading.Thread(target=background_collector, daemon=True)
    t.start()
    print("Dashboard running at http://0.0.0.0:5000")
    print(f"Monitoring targets: HTTP={HTTP_TARGET} HTTPS={HTTPS_TARGET}")
    app.run(host='0.0.0.0', port=5000, debug=False)
