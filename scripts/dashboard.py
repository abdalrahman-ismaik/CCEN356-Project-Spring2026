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

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# Shared metrics store (last 100 samples per protocol)
live_metrics = {"http": [], "https": []}

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
                document.getElementById('httpSamples').textContent = data.http_samples;
                document.getElementById('httpsSamples').textContent = data.https_samples;
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
        ("http://192.165.20.79", "http"),
        ("https://192.165.20.79", "https"),
    ]
    while True:
        for url, key in targets:
            try:
                start = time.time()
                r = requests.get(url, timeout=5, verify=False)
                elapsed = (time.time() - start) * 1000
                live_metrics[key].append({"ms": elapsed, "bytes": len(r.content)})
                if len(live_metrics[key]) > 100:
                    live_metrics[key].pop(0)
            except Exception:
                pass
        time.sleep(3)


@app.route('/')
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route('/api/metrics')
def metrics_api():
    def avg(lst, key):
        return round(sum(x[key] for x in lst) / len(lst), 2) if lst else 0

    return jsonify({
        "http_avg_ms": avg(live_metrics["http"], "ms"),
        "https_avg_ms": avg(live_metrics["https"], "ms"),
        "http_samples": len(live_metrics["http"]),
        "https_samples": len(live_metrics["https"]),
    })


if __name__ == '__main__':
    t = threading.Thread(target=background_collector, daemon=True)
    t.start()
    print("Dashboard running at http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)
