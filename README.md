# CCEN356 Project — HTTP/HTTPS Performance & Visibility

Compare HTTP vs HTTPS performance using physical Cisco networking equipment, Python automation, Scapy capture, and data visualization.

## Team

- 2 members
- Spring 2026

---

## Network Topology

```
[Client 1: 192.165.10.92] ──┐
[Client 2: 192.165.10.79] ──┤── [SW1 (2960)] ── [R1 (2901)] ── [R2 (2901)] ── [Server: 192.165.20.79]
```

## IP Addressing Quick Reference

| Device | IP Address | Subnet Mask | Default Gateway | DNS |
|---|---|---|---|---|
| **Server** | 192.165.20.79 | 255.255.255.0 | 192.165.20.37 | 8.8.8.8 |
| **Client 1** | 192.165.10.92 | 255.255.255.0 | 192.165.10.37 | 8.8.8.8 |
| **Client 2** | 192.165.10.79 | 255.255.255.0 | 192.165.10.37 | 8.8.8.8 |
| **R1 Gi0/0** (WAN) | 10.1.5.21 | 255.255.255.252 | — | — |
| **R1 Gi0/1** (LAN) | 192.165.10.37 | 255.255.255.0 | — | — |
| **R2 Gi0/0** (WAN) | 10.1.5.22 | 255.255.255.252 | — | — |
| **R2 Gi0/1** (LAN) | 192.165.20.37 | 255.255.255.0 | — | — |

---

## Project Structure

```
├── scripts/
│   ├── ssh_connect.py            # Netmiko SSH to routers
│   ├── capture_traffic.py        # Scapy packet capture
│   ├── performance_metrics.py    # HTTP vs HTTPS benchmarking
│   ├── visualize_traffic.py      # Matplotlib charts
│   └── dashboard.py              # Flask live dashboard
├── server/
│   ├── http_server.py            # Flask HTTP (port 80)
│   ├── secured_server.py         # Flask HTTPS (port 443)
│   └── templates/
│       ├── index.html
│       └── show.html
├── configs/                      # Router config exports
├── data/                         # Generated CSV data
├── charts/                       # Generated PNG charts
├── requirements.txt
├── REFERENCE_PROMPT.md           # Full project reference
└── project_description.md        # Original project guide
```

---

## Step-by-Step Lab Guide

Follow these steps in order. Each step includes what to expect so you can confirm it worked before moving on.

---

### STEP 1 — Cable and power on all devices

Connect the physical hardware:
- Clients 1 and 2 → SW1 (any access port)
- SW1 uplink → R1 Gi0/1
- R1 Gi0/0 ↔ R2 Gi0/0 (crossover or via patch panel)
- R2 Gi0/1 → Server PC
- Console cables from your laptop to R1 and R2 (for initial config)

> **No dedicated monitor PC needed.** The Scapy capture script runs directly on Client 2, recording its own NIC traffic during the benchmark (Step 12).

**Expected:** All link LEDs on the switch and router interfaces are green (amber during negotiation is normal — wait 30 seconds).

---

### STEP 2 — Configure R1 via console cable

Open PuTTY, select **Serial**, choose the correct COM port, speed **9600**. Connect to R1 and paste the block below:

```
enable
configure terminal

hostname R1
ip domain-name lab.local
crypto key generate rsa modulus 2048
ip ssh version 2
enable secret cisco123
username admin privilege 15 secret admin123

line vty 0 4
 transport input ssh
 login local
 exit

interface GigabitEthernet0/0
 ip address 10.1.5.21 255.255.255.252
 no shutdown
 exit

interface GigabitEthernet0/1
 ip address 192.165.10.37 255.255.255.0
 no shutdown
 exit

ip route 192.165.20.0 255.255.255.0 10.1.5.22

ip access-list extended HTTP_HTTPS_ONLY
 permit tcp any any eq 80
 permit tcp any any eq 443
 permit tcp any eq 80 any established
 permit tcp any eq 443 any established
 permit icmp any any
 exit

interface GigabitEthernet0/0
 ip access-group HTTP_HTTPS_ONLY in
 exit

ip access-list extended HTTPS_ONLY
 permit tcp any any eq 443
 permit tcp any eq 443 any
 exit

ip access-list extended HTTP_ONLY
 permit tcp any any eq 80
 permit tcp any eq 80 any
 exit

class-map match-any CM_HTTPS
 match access-group name HTTPS_ONLY
 exit

class-map match-any CM_HTTP
 match access-group name HTTP_ONLY
 exit

policy-map WEB_QOS
 class CM_HTTPS
  priority percent 30
  ! If your IOS image rejects the line above, use: priority 1000
 class CM_HTTP
  bandwidth percent 10
 class class-default
  fair-queue
 exit

interface GigabitEthernet0/0
 service-policy output WEB_QOS
 exit

end
write memory
```

**Expected:** No error messages during paste. Final line should say `Building configuration... [OK]`. Verify with:

```
show ip interface brief
```
Both `GigabitEthernet0/0` and `GigabitEthernet0/1` should show **up/up**.

```
show ip ssh
```
Should say `SSH Enabled - version 2.0`.

Run QoS verification commands:

```
show policy-map interface GigabitEthernet0/0
show access-lists HTTPS_ONLY
show access-lists HTTP_ONLY
show running-config | section policy-map|class-map|access-list|service-policy
```

**Expected:**
- `show policy-map interface GigabitEthernet0/0` shows `Service-policy output: WEB_QOS` with `Class-map: CM_HTTPS` and `Class-map: CM_HTTP`.
- `show access-lists HTTPS_ONLY` and `show access-lists HTTP_ONLY` return the two permit lines for ports 443 and 80 respectively.
- `show running-config | section policy-map|class-map|access-list|service-policy` shows the QoS/ACL wiring (`HTTPS_ONLY`, `HTTP_ONLY`, `CM_HTTPS`, `CM_HTTP`, and `service-policy output WEB_QOS`).
- During active client traffic, packet counters for both classes/ACLs should increase.

If you see `how access-lists ...`, that is a typo; use `show access-lists ...`.

---

### STEP 3 — Configure R2 via console cable

Open a second PuTTY session on the R2 COM port and paste:

```
enable
configure terminal

hostname R2
ip domain-name lab.local
crypto key generate rsa modulus 2048
ip ssh version 2
enable secret cisco123
username admin privilege 15 secret admin123

line vty 0 4
 transport input ssh
 login local
 exit

interface GigabitEthernet0/0
 ip address 10.1.5.22 255.255.255.252
 no shutdown
 exit

interface GigabitEthernet0/1
 ip address 192.165.20.37 255.255.255.0
 no shutdown
 exit

ip route 192.165.10.0 255.255.255.0 10.1.5.21

end
write memory
```

**Expected:** Same as R2 — `Building configuration... [OK]`. Verify:

```
show ip interface brief
show ip ssh
```
Both interfaces **up/up**, SSH version 2.0 enabled.

---

### STEP 4 — Verify SW1 (no configuration needed)

SW1 requires no configuration — it operates as a basic Layer 2 switch out of the box. Simply confirm all ports have link (green LEDs) after connecting the cables from Step 1.

Optionally connect a console cable and run:
```
show interfaces status
```

**Expected:** Ports connected to Client 1, Client 2, and R1 Gi0/1 should show **connected** status. Ports with nothing plugged in will show **notconnect** — that is normal.

---

### STEP 5 — Set static IPs on all PCs

On each PC, open **PowerShell as Administrator** and run the appropriate block.

**Server PC (192.165.20.79):**
```powershell
Remove-NetIPAddress -InterfaceAlias "Ethernet" -Confirm:$false -ErrorAction SilentlyContinue
Remove-NetRoute -InterfaceAlias "Ethernet" -Confirm:$false -ErrorAction SilentlyContinue
New-NetIPAddress -InterfaceAlias "Ethernet" -IPAddress 192.165.20.79 -PrefixLength 24 -DefaultGateway 192.165.20.37
Set-DnsClientServerAddress -InterfaceAlias "Ethernet" -ServerAddresses 8.8.8.8
```

**Client 1 PC (192.165.10.92):**
```powershell
Get-NetAdapter | Select-Object Name, InterfaceDescription, Status
$iface = "Ethernet 5"   # replace with the adapter alias shown above

Remove-NetIPAddress -InterfaceAlias $iface -Confirm:$false -ErrorAction SilentlyContinue
Remove-NetRoute -InterfaceAlias $iface -Confirm:$false -ErrorAction SilentlyContinue
New-NetIPAddress -InterfaceAlias $iface -IPAddress 192.165.10.92 -PrefixLength 24 -DefaultGateway 192.165.10.37
Set-DnsClientServerAddress -InterfaceAlias $iface -ServerAddresses 8.8.8.8
```

**Client 2 PC (192.165.10.79):**
```powershell
Remove-NetIPAddress -InterfaceAlias "Ethernet" -Confirm:$false -ErrorAction SilentlyContinue
Remove-NetRoute -InterfaceAlias "Ethernet" -Confirm:$false -ErrorAction SilentlyContinue
New-NetIPAddress -InterfaceAlias "Ethernet" -IPAddress 192.165.10.79 -PrefixLength 24 -DefaultGateway 192.165.10.37
Set-DnsClientServerAddress -InterfaceAlias "Ethernet" -ServerAddresses 8.8.8.8
```

**Expected:** No red errors. Confirm IP was applied with:
```powershell
ipconfig
```
You should see the correct IP under the Ethernet adapter.

---

### STEP 6 — Test network connectivity end-to-end

From **Client 1 or Client 2**, run:

```powershell
ping 192.165.10.37   # R1 LAN gateway — same subnet, should reply instantly
ping 10.1.5.21       # R1 WAN — tests R1 is up
ping 10.1.5.22       # R2 WAN — tests WAN link between routers
ping 192.165.20.37   # R2 LAN gateway — tests full path
ping 192.165.20.79   # Server — tests full end-to-end path
```

**Expected:** All 5 pings return replies with no timeouts (TTL values around 126–254). If any ping fails, re-check the `ip route` statements on the corresponding router and confirm `no shutdown` was applied on the interfaces.

Also test SSH from a client to R1:
```powershell
ssh -o "KexAlgorithms=+diffie-hellman-group14-sha1" -o "HostKeyAlgorithms=+ssh-rsa" -o "Ciphers=+aes128-cbc,aes192-cbc,aes256-cbc,3des-cbc" -o "MACs=+hmac-sha1" admin@192.165.10.37
# password: admin123
```

> **Why the extra flags?** The Cisco 2901 commonly advertises legacy SSH algorithms only: key exchange (`diffie-hellman-group14-sha1`, sometimes `group1-sha1`), host key type (`ssh-rsa`), older ciphers (CBC), and older MACs (`hmac-sha1`). Modern Windows OpenSSH disables these by default. The quoted `-o` options re-enable compatible algorithms and avoid PowerShell parsing issues with comma-separated lists.

**Expected:** You land at `R1#` prompt. Type `exit` to disconnect.

---

### STEP 7 — Install Python dependencies (on all client PCs)

From the project root folder on each client:

```powershell
pip install -r requirements.txt
```

**Expected:** All packages install without errors. Key packages that must succeed: `flask`, `netmiko`, `scapy`, `matplotlib`, `pandas`, `requests`, `pyopenssl`. If a package fails, try `pip install <package>` individually to see the error.

---

### STEP 8 — Generate SSL certificates (on Server PC)

Run this from the project root on the **Server PC**:

**Option A — Python (SAN-enabled for modern browsers):**
```powershell
cd server
python -c "
from OpenSSL import crypto
k = crypto.PKey(); k.generate_key(crypto.TYPE_RSA, 2048)
c = crypto.X509()
c.set_version(2)
c.get_subject().CN = '192.165.20.79'; c.get_subject().O = 'CCEN356Lab'
c.set_serial_number(1000); c.gmtime_adj_notBefore(0); c.gmtime_adj_notAfter(365*24*60*60)
c.set_issuer(c.get_subject()); c.set_pubkey(k)
c.add_extensions([
    crypto.X509Extension(b'basicConstraints', True, b'CA:FALSE'),
    crypto.X509Extension(b'keyUsage', True, b'digitalSignature,keyEncipherment'),
    crypto.X509Extension(b'extendedKeyUsage', False, b'serverAuth'),
    crypto.X509Extension(b'subjectAltName', False, b'IP:192.165.20.79')
])
c.sign(k, 'sha256')
open('cert.pem','wb').write(crypto.dump_certificate(crypto.FILETYPE_PEM, c))
open('key.pem','wb').write(crypto.dump_privatekey(crypto.FILETYPE_PEM, k))
print('Generated SAN-enabled cert.pem and key.pem')
"
```

**Option B — OpenSSL CLI (SAN-enabled, Git Bash/WSL/OpenSSL for Windows):**
```bash
cd server
openssl req -x509 -newkey rsa:2048 -sha256 -days 365 -nodes \
  -keyout key.pem -out cert.pem \
  -subj "/CN=192.165.20.79/O=CCEN356Lab" \
  -addext "subjectAltName=IP:192.165.20.79" \
  -addext "extendedKeyUsage=serverAuth"
```

**Expected:** The message `Generated SAN-enabled cert.pem and key.pem` (Option A) or a key generation progress line (Option B). Two files must exist afterward:
```powershell
Test-Path server\cert.pem   # should print True
Test-Path server\key.pem    # should print True
```

Then restart the HTTPS server so it loads the new files:
```powershell
python server\secured_server.py
```

### STEP 8.1 — Trust the server certificate on each Client PC (for browser lock icon)

Copy `server\cert.pem` from the Server PC to each Client PC (or use the shared project folder if both clients already have it).

On each Client PC, run one of the following PowerShell commands:

**Option A — Current user trust store (no Administrator required):**
```powershell
certutil -user -addstore -f Root "C:\Users\narut\Downloads\CCEN356-Project-Spring2026\server\cert.pem"
```

**Option B — Local machine trust store (Administrator PowerShell):**
```powershell
certutil -addstore -f Root "C:\Users\narut\Downloads\CCEN356-Project-Spring2026\server\cert.pem"
```

Verify the cert is present:
```powershell
certutil -store -user Root | findstr /i "CCEN356 192.165.20.79"
```

Then fully close and reopen the browser before testing `https://192.165.20.79` again. If you previously clicked "Proceed (unsafe)", click "Turn on warnings" first, then reload.

---

### STEP 9 — Open Windows Firewall ports (on Server PC)

Run **PowerShell as Administrator** on the Server PC:

```powershell
New-NetFirewallRule -DisplayName "CCEN356 HTTP" -Direction Inbound -LocalPort 80 -Protocol TCP -Action Allow
New-NetFirewallRule -DisplayName "CCEN356 HTTPS" -Direction Inbound -LocalPort 443 -Protocol TCP -Action Allow
New-NetFirewallRule -DisplayName "CCEN356 Allow Ping" -Direction Inbound -Protocol ICMPv4 -IcmpType 8 -Action Allow
```

**Expected:** Each command outputs a rule object with `Enabled: True`. Verify:
```powershell
Get-NetFirewallRule -DisplayName "CCEN356*" | Select-Object DisplayName, Enabled
```
All three rules should show `Enabled: True`.

---

### STEP 10 — Start the HTTP and HTTPS servers (on Server PC)

Open **two separate PowerShell terminals** on the Server PC and run one command in each.

**Terminal 1 — HTTP server (run as Administrator for port 80):**
```powershell
set CCEN356_QOS_HTTP_DELAY_MS=75
set CCEN356_QOS_HTTP_DELAY_JITTER_MS=10
python server\http_server.py
```

**Terminal 2 — HTTPS server (run as Administrator for port 443):**
```powershell
set CCEN356_QOS_HTTPS_DELAY_MS=0
python server\secured_server.py
```

**Expected:** Each terminal should print something like:
```
* Running on http://0.0.0.0:80
* Running on https://0.0.0.0:443
```
Both servers stay running — do not close these terminals.

---

### STEP 11 — Verify servers are reachable (from Client PCs)

From **Client 1 or Client 2**, test both protocols:

```powershell
# HTTP
curl http://192.165.20.79

# HTTPS (self-signed cert — -k skips verification)
curl -k https://192.165.20.79
```

Or using PowerShell's `Invoke-WebRequest`:
```powershell
Invoke-WebRequest -Uri http://192.165.20.79 -UseBasicParsing
Invoke-WebRequest -Uri https://192.165.20.79 -SkipCertificateCheck -UseBasicParsing
```

**Expected:** Both return `StatusCode: 200` and an HTML body. If HTTP times out, re-check the firewall rule from Step 9. If HTTPS fails with a connection error, confirm `secured_server.py` is still running and `cert.pem`/`key.pem` exist.

---

### STEP 12 — Start Scapy capture (on Client 2 — before running the benchmark)

Client 2 will both generate the benchmark traffic (Step 15) and capture it with Scapy at the same time.

1. Open an Administrator PowerShell window on Client 2.
2. Run `python scripts/capture_traffic.py`.
3. Leave it running through Steps 13–15.

**Expected:** Once `performance_metrics.py` starts in Step 15, the Scapy script will log HTTP and HTTPS packets to `data/traffic_log.csv`. HTTP packets (port 80) remain readable at the application layer, while HTTPS packets (port 443) are encrypted and should be analyzed through the CSV and the generated charts.

---

### STEP 13 — Collect router show outputs (Client 1 or Client 2)

From the project root on a client PC:

```powershell
python scripts/ssh_connect.py
```

**Expected:** The script connects to R1 via SSH and prints the output of 4 commands in labeled sections:

```
========== show ip interface brief ==========
Interface              IP-Address      OK? Method Status  Protocol
GigabitEthernet0/0    10.1.5.21       YES NVRAM  up      up
GigabitEthernet0/1    192.165.10.37   YES NVRAM  up      up
...

========== show ip route ==========
...

========== show access-lists ==========
Extended IP access list HTTP_HTTPS_ONLY
    10 permit tcp any any eq www
...

========== show policy-map interface GigabitEthernet0/0 ==========
...
```

If the script hangs or times out, verify SSH connectivity with `ssh admin@192.165.10.37` manually.

---

### STEP 14 — Capture traffic (Client 1 — run as Administrator)

> **This must run as Administrator.** Right-click PowerShell → **Run as Administrator**.

```powershell
python scripts/capture_traffic.py
```

The capture runs for **60 seconds**. While it is running, immediately start Step 15 on Client 2.

**Expected:** The script runs silently for 60 seconds, then prints a summary and saves:
```
Capture complete. X packets saved to data/traffic_log.csv
```
Open `data/traffic_log.csv` to confirm rows with columns: `timestamp, src_ip, dst_ip, src_port, dst_port, protocol, length`.

---

### STEP 15 — Run performance benchmark (Client 2 — while Step 14 is active)

On Client 2, immediately after starting the capture on Client 1:

```powershell
python scripts/performance_metrics.py
```


This sends 20 HTTP and 20 HTTPS requests to the server and measures timing.

**Expected output (example values):**
```
--- HTTP Results ---
Requests: 20  Errors: 0  Avg: 12.4ms  Min: 9.1ms  Max: 18.3ms
Throughput: 85.2 kbps  Error rate: 0.0%

--- HTTPS Results ---
Requests: 20  Errors: 0  Avg: 31.7ms  Min: 24.5ms  Max: 45.2ms
Throughput: 62.1 kbps  Error rate: 0.0%

Saved to data/performance_results.csv
```
HTTPS average should be noticeably higher than HTTP due to the TLS handshake overhead. If error count is > 0, re-check that both servers are still running (Step 10).

---

### STEP 16 — Generate charts

After the capture in Step 14 completes and Step 15 is done:

```powershell
python scripts/visualize_traffic.py
```

**Expected:** Two advanced, publication-ready PNG files are created:
```
charts/performance_comparison.png   (executive storyboard: latency+stdev, reliability, throughput, latency envelope, tail/jitter indicators)
charts/traffic_analysis.png         (capture intelligence: packets/s timeline, protocol share donut, size histogram, CDF, top conversations)
```
Open both files and verify the following quality checks:

- Clear distinction between HTTP and HTTPS in all panels
- Axis titles, legends, and value annotations are readable
- No empty panels (unless one protocol genuinely has zero packets)
- Key conclusions are visible without manual calculation (for example, average latency delta and reliability trend)

If charts are blank or incomplete, confirm both source files exist and are populated:

```powershell
Get-Item data\performance_results.csv, data\traffic_log.csv | Select-Object FullName, Length
```

---

### STEP 17 — Launch the live dashboard

You can run the dashboard in either mode. For demos and team monitoring, **Mode A (Server PC)** is recommended.

**Mode A - Run on Server PC (shared dashboard for all clients):**

1. Open port 5000 on the Server PC (Administrator PowerShell):

```powershell
New-NetFirewallRule -DisplayName "CCEN356 Dashboard" -Direction Inbound -LocalPort 5000 -Protocol TCP -Action Allow
```

2. Start the dashboard on the Server PC:

```powershell
python scripts/dashboard.py
```

3. From any client PC browser, open:

```text
http://192.165.20.79:5000
```

**Mode B - Run on a Client PC (local-only view on that machine):**

```powershell
python scripts/dashboard.py
```

Then open: **http://localhost:5000** on that same client.

**Real-time defaults (current):**

- Poll interval: **0.5s**
- Request timeout: **1.5s**
- Dashboard continuously samples **two profiles** each cycle:
  - `without_qos` (baseline)
  - `with_qos` (sends `X-CCEN356-QOS-MODE: on` to both servers)

**Expected (advanced dashboard):**

- Top-right toggle to switch **Without QoS** vs **With QoS** view instantly
- KPI cards for HTTP avg, HTTPS avg, latency delta, and fastest protocol
- Built-in **ML Insights (MVP)**: next-latency prediction, trend detection, and performance-issue risk score from recent historical samples
- Real-time latency timeline
- Avg/P95/P99 comparison chart
- Reliability chart (uptime + failures)
- Performance profile radar (latency, tail, jitter, availability, consistency)
- Endpoint status matrix with last status code, last latency, checks/failures, and last error
- Status strip includes live **QoS Impact** (delta shift between with/without QoS)
- If internet/CDN access is blocked, charts still render using the built-in offline canvas renderer (no external Chart.js dependency required)

- If both monitored targets are reachable, status badges show **UP**.
- If a target is unreachable, it shows **DOWN** plus last error details in the status matrix.

The `/api/metrics` endpoint returns JSON like:

```powershell
curl http://localhost:5000/api/metrics
```
```json
{
  "http": {
    "avg_ms": 12.4,
    "p95_ms": 18.8,
    "p99_ms": 21.1,
    "jitter_ms": 1.7,
    "uptime_pct": 100.0,
    "is_up": true
  },
  "https": {
    "avg_ms": 31.7,
    "p95_ms": 44.3,
    "p99_ms": 48.2,
    "jitter_ms": 3.9,
    "uptime_pct": 100.0,
    "is_up": true
  },
  "comparison": {
    "avg_delta_ms": 19.3,
    "faster_protocol": "HTTP"
  },
  "timeline": {
    "labels": ["11:10:21", "11:10:24"],
    "http_ms": [12.0, 12.9],
    "https_ms": [30.4, 32.7]
  }
}
```

If Step 17 shows **DOWN** after Steps 14/15, verify Step 10 servers are still running on the Server PC.

If the dashboard is slow or appears stale, make sure only one instance is bound to port 5000 (close older dashboard terminals before launching a new one).

Optional target override from the Client PC (PowerShell):
```powershell
$env:CCEN356_HTTP_URL="http://192.165.20.79"
$env:CCEN356_HTTPS_URL="https://192.165.20.79"
$env:CCEN356_DASHBOARD_PORT="5000"
python scripts/dashboard.py
```

Optional real-time tuning (PowerShell):
```powershell
$env:CCEN356_POLL_INTERVAL_SEC="0.1"
$env:CCEN356_REQUEST_TIMEOUT_SEC="1.2"
$env:CCEN356_DASHBOARD_MAX_SAMPLES="1000"
python scripts/dashboard.py
```

Optional ML analysis tuning (PowerShell):
```powershell
$env:CCEN356_ML_FORECAST_HORIZON="5"     # predicted points ahead
$env:CCEN356_ML_MIN_POINTS="8"            # minimum samples before stronger signal
$env:CCEN356_ML_HIGH_LATENCY_MS="120"     # high-latency threshold
$env:CCEN356_ML_HIGH_JITTER_MS="20"       # high-jitter threshold
python scripts/dashboard.py
```

Optional QoS-priority tuning (set these before starting Step 10 servers):
```powershell
# HTTP server terminal (plain HTTP gets extra delay when QoS mode is ON)
$env:CCEN356_QOS_HTTP_DELAY_MS="75"
$env:CCEN356_QOS_HTTP_DELAY_JITTER_MS="1"
python server\http_server.py

# HTTPS server terminal (keep at 0 for priority, or tune if needed)
$env:CCEN356_QOS_HTTPS_DELAY_MS="0"
python server\secured_server.py
```

For a stronger QoS demonstration where HTTPS clearly becomes faster, increase
`CCEN356_QOS_HTTP_DELAY_MS` into the `90-120` range.

Optional high-load QoS proof test (run from a Client PC):
```powershell
python scripts/congestion_test.py --duration 90 --concurrency 80 --with-qos
```

Expected: the script stresses both protocols in parallel and writes `data/congestion_results.csv`.
When QoS and server delay tuning are active, HTTPS average latency should trend lower than HTTP.

If your HTTPS server is running on **8443** instead of **443**, set fallback ports before launch:
```powershell
$env:CCEN356_HTTPS_FALLBACK_PORTS="443,8443"
python scripts/dashboard.py
```

Important: The live dashboard measures endpoint latency and health only. Packet capture is still performed by `scripts/capture_traffic.py` (Step 14, Administrator PowerShell).

---

### STEP 18 — Save Scapy capture and screenshots

Stop the Scapy capture (started in Step 12).

1. **Confirm** `data/traffic_log.csv` was created in the `data/` folder.
2. Review the CSV for HTTP and HTTPS packet entries and save any relevant screenshots from your analysis tools.
3. Export the generated charts from `visualize_traffic.py` for the report.
4. Use the dashboard screenshot to show live latency and health monitoring.

**Expected:** HTTP traffic should show readable application-layer data in the CSV and charts. HTTPS traffic should appear as encrypted TLS traffic and be summarized through the capture log, performance results, and visualization outputs.

---

### STEP 19 — Export router running configs

SSH to each router and save the running configuration to the `configs/` folder.

**From Client 1:**
```powershell
ssh -o "KexAlgorithms=+diffie-hellman-group14-sha1" -o "HostKeyAlgorithms=+ssh-rsa" -o "Ciphers=+aes128-cbc,aes192-cbc,aes256-cbc,3des-cbc" -o "MACs=+hmac-sha1" admin@192.165.10.37
# password: admin123
# at the R1# prompt:
show running-config
```
Copy the full output and paste into `configs/R1_config.txt`.

Repeat for R2:
```powershell
ssh -o "KexAlgorithms=+diffie-hellman-group14-sha1" -o "HostKeyAlgorithms=+ssh-rsa" -o "Ciphers=+aes128-cbc,aes192-cbc,aes256-cbc,3des-cbc" -o "MACs=+hmac-sha1" admin@192.165.20.37
# at the R2# prompt:
show running-config
```
Paste into `configs/R2_config.txt`.

**Expected:** Both files contain the full `show running-config` output including interface IPs, route statements, ACL, and QoS policy (R1 only). Verify ACL hit counters are non-zero:
```
show access-lists
```
You should see match counts like `(20 matches)` next to the HTTP and HTTPS permit lines.

---

## Final Output Checklist

Confirm all expected outputs exist before writing the report:

| File | Created by | Check |
|---|---|---|
| `data/traffic_log.csv` | `capture_traffic.py` | Rows with HTTP/HTTPS packets |
| `data/performance_results.csv` | `performance_metrics.py` | 2 rows (HTTP, HTTPS) with timing stats |
| `charts/performance_comparison.png` | `visualize_traffic.py` | 3-panel bar chart |
| `charts/traffic_analysis.png` | `visualize_traffic.py` | Packet count + histogram |
| `configs/R1_config.txt` | Manual export | Includes ACL + QoS |
| `configs/R2_config.txt` | Manual export | Includes routes |
| `data/traffic_log.csv` | `capture_traffic.py` | HTTP and HTTPS packet entries captured |
| Dashboard screenshot | Browser | Advanced dashboard at 192.165.20.79:5000 (or localhost:5000 in local mode) |
