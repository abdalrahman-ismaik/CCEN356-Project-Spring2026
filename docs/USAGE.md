# Usage

This page explains the main scripts and the expected execution flow.

## 1. Start The Web Servers

Run these commands on the server PC.

HTTP:

```powershell
python server\http_server.py
```

HTTPS:

```powershell
python server\secured_server.py
```

Default ports are 80 and 443. Override them with:

```powershell
$env:CCEN356_HTTP_PORT="8080"
$env:CCEN356_HTTPS_PORT="8443"
```

## 2. Router SSH Automation With Netmiko

`scripts/ssh_connect.py` connects to a Cisco IOS router and runs operational checks:

- `show ip interface brief`
- `show ip route`
- `show access-lists`
- `show policy-map interface GigabitEthernet0/0`

Example:

```powershell
$env:CCEN356_ROUTER_HOST="192.165.10.37"
$env:CCEN356_ROUTER_USERNAME="admin"
$env:CCEN356_ROUTER_PASSWORD="<local-password>"
python scripts\ssh_connect.py
```

You can also run a custom command:

```powershell
python scripts\ssh_connect.py --command "show version"
```

The script intentionally does not store router passwords in source code.

## 3. HTTP/HTTPS Performance Measurement

`scripts/performance_metrics.py` sends requests to the HTTP and HTTPS endpoints and writes `data/performance_results.csv`.

```powershell
python scripts\performance_metrics.py --requests 50 --timeout 10 --interval 0.1
```

Override endpoints:

```powershell
python scripts\performance_metrics.py `
  --http-url http://192.165.20.79 `
  --https-url https://192.165.20.79
```

Metrics include average latency, median, min, max, standard deviation, p90, p95, p99, jitter, status-code buckets, success/error rate, requests per second, and throughput.

## 4. Scapy Packet Capture

`scripts/capture_traffic.py` captures TCP traffic involving ports 80 and 443 and writes `data/traffic_log.csv`.

Run as Administrator on Windows or with root privileges on Linux:

```powershell
python scripts\capture_traffic.py --duration 60 --output data\traffic_log.csv
```

If auto-detection picks the wrong interface, provide it explicitly:

```powershell
python scripts\capture_traffic.py --iface "Ethernet"
```

CSV columns:

```text
timestamp,src_ip,dst_ip,src_port,dst_port,protocol,length
```

## 5. Matplotlib Chart Generation

`scripts/visualize_traffic.py` reads the generated CSV files and writes charts under `charts/`.

```powershell
python scripts\visualize_traffic.py
```

Expected outputs:

- `charts/performance_comparison.png`
- `charts/traffic_analysis.png`

These generated charts are ignored by git. Curated report/README figures live under `docs/assets/`.

## 6. Flask Dashboard

`scripts/dashboard.py` runs a live monitoring dashboard on port 5000 by default.

```powershell
python scripts\dashboard.py
```

Open:

```text
http://localhost:5000
```

or, if running on the server PC and reachable from the clients:

```text
http://192.165.20.79:5000
```

Useful variables:

```powershell
$env:CCEN356_DASHBOARD_PORT="5000"
$env:CCEN356_POLL_INTERVAL_SEC="0.5"
$env:CCEN356_REQUEST_TIMEOUT_SEC="1.5"
$env:CCEN356_DASHBOARD_MAX_SAMPLES="240"
```

The dashboard probes both baseline and QoS-priority profiles, tracks endpoint availability, and exposes JSON at:

```text
http://localhost:5000/api/metrics
http://localhost:5000/api/health
```

## 7. QoS And Congestion Experiments

`scripts/congestion_test.py` generates sustained concurrent HTTP/HTTPS traffic:

```powershell
python scripts\congestion_test.py --duration 90 --concurrency 80 --priority https
```

`scripts/qos_ab_compare.py` runs an isolated two-phase comparison:

```powershell
python scripts\qos_ab_compare.py --packets 200
```

Expected generated files:

- `data/qos_ab_metrics.csv`
- `data/qos_ab_isolated_packets.csv`, when packet capture succeeds
- `data/qos_ab_packet_summary.csv`, when packet capture succeeds
- `charts/qos_ab_comparison.png`

## Recommended Experiment Order

1. Confirm interface status and static routes on R1 and R2.
2. Confirm the server responds over HTTP and HTTPS.
3. Start packet capture on a client.
4. Run the benchmark.
5. Generate charts.
6. Start the dashboard.
7. Repeat with QoS enabled and compare results.
