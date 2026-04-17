# CCEN356 Project — HTTP/HTTPS Performance & Visibility

Compare HTTP vs HTTPS performance using physical Cisco networking equipment, Python automation, Wireshark analysis, and data visualization.

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
│   ├── secured_server.py         # Flask HTTPS (port 8443)
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

> **No dedicated monitor PC needed.** Wireshark will run directly on Client 2, capturing its own NIC traffic during the benchmark (Step 12).

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

ip access-list extended WEB_QOS_PORTS
 permit tcp any any eq 80
 permit tcp any any eq 443
 permit tcp any eq 80 any
 permit tcp any eq 443 any
 exit

class-map match-any HTTP_HTTPS
 match access-group name WEB_QOS_PORTS
 exit

policy-map WEB_QOS
 class HTTP_HTTPS
  no bandwidth
  no bandwidth percent
  priority percent 30
  ! If your IOS image rejects the line above, use: priority 1000
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
ssh -oKexAlgorithms=+diffie-hellman-group14-sha1 admin@192.165.10.37
# password: admin123
```

> **Why the extra flag?** The Cisco 2901 only advertises legacy key-exchange methods (`diffie-hellman-group14-sha1`, `group1-sha1`). Modern Windows OpenSSH disables these by default. The `-oKexAlgorithms=+diffie-hellman-group14-sha1` flag re-enables the safest of the three so the handshake succeeds. You need this flag every time you SSH to either router from a Windows client.

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

**Option A — Python (recommended, no extra tools needed):**
```powershell
cd server
python -c "
from OpenSSL import crypto
k = crypto.PKey(); k.generate_key(crypto.TYPE_RSA, 2048)
c = crypto.X509()
c.get_subject().CN = '192.165.20.79'; c.get_subject().O = 'CCEN356Lab'
c.set_serial_number(1000); c.gmtime_adj_notBefore(0); c.gmtime_adj_notAfter(365*24*60*60)
c.set_issuer(c.get_subject()); c.set_pubkey(k); c.sign(k, 'sha256')
open('cert.pem','wb').write(crypto.dump_certificate(crypto.FILETYPE_PEM, c))
open('key.pem','wb').write(crypto.dump_privatekey(crypto.FILETYPE_PEM, k))
print('Generated cert.pem and key.pem')
"
```

**Option B — OpenSSL CLI (Git Bash or WSL):**
```bash
cd server
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout key.pem -out cert.pem \
  -subj "/CN=192.165.20.79/O=CCEN356Lab"
```

**Expected:** The message `Generated cert.pem and key.pem` (Option A) or a key generation progress line (Option B). Two files must exist afterward:
```powershell
Test-Path server\cert.pem   # should print True
Test-Path server\key.pem    # should print True
```

---

### STEP 9 — Open Windows Firewall ports (on Server PC)

Run **PowerShell as Administrator** on the Server PC:

```powershell
New-NetFirewallRule -DisplayName "CCEN356 HTTP" -Direction Inbound -LocalPort 80 -Protocol TCP -Action Allow
New-NetFirewallRule -DisplayName "CCEN356 HTTPS" -Direction Inbound -LocalPort 443,8443 -Protocol TCP -Action Allow
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
python server\http_server.py
```

**Terminal 2 — HTTPS server:**
```powershell
python server\secured_server.py
```

**Expected:** Each terminal should print something like:
```
* Running on http://0.0.0.0:80
* Running on https://0.0.0.0:8443
```
Both servers stay running — do not close these terminals.

---

### STEP 11 — Verify servers are reachable (from Client PCs)

From **Client 1 or Client 2**, test both protocols:

```powershell
# HTTP
curl http://192.165.20.79

# HTTPS (self-signed cert — -k skips verification)
curl -k https://192.165.20.79:8443
```

Or using PowerShell's `Invoke-WebRequest`:
```powershell
Invoke-WebRequest -Uri http://192.165.20.79 -UseBasicParsing
Invoke-WebRequest -Uri https://192.165.20.79:8443 -SkipCertificateCheck -UseBasicParsing
```

**Expected:** Both return `StatusCode: 200` and an HTML body. If HTTP times out, re-check the firewall rule from Step 9. If HTTPS fails with a connection error, confirm `secured_server.py` is still running and `cert.pem`/`key.pem` exist.

---

### STEP 12 — Start Wireshark (on Client 2 — before running the benchmark)

Client 2 will both generate the benchmark traffic (Step 15) and capture it with Wireshark at the same time.

1. Open Wireshark on Client 2.
2. Select the **Ethernet** adapter (the one with IP `192.165.10.79`).
3. Apply the capture filter: `tcp port 80 or tcp port 443`
4. Click **Start** — leave it running through Steps 13–15.

**Expected:** Once `performance_metrics.py` starts in Step 15, you will immediately see TCP traffic appear. HTTP packets (port 80) will show readable request/response data in the packet details pane. HTTPS packets (port 443) will show encrypted `Application Data` records — no readable content visible. This contrast is the core observation for your report.

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

**Expected:** Two PNG files are created:
```
charts/performance_comparison.png   (bar charts: avg time, throughput, min/avg/max)
charts/traffic_analysis.png         (packet count by protocol, size distribution histogram)
```
Open both files to confirm they display readable charts with labeled axes and data for both HTTP and HTTPS.

---

### STEP 17 — Launch the live dashboard

```powershell
python scripts/dashboard.py
```

Then open a browser and go to: **http://localhost:5000**

**Expected:** A dark-themed web page with a real-time Chart.js line chart that updates every 3 seconds showing HTTP and HTTPS response times. The `/api/metrics` endpoint also returns JSON:

```powershell
curl http://localhost:5000/api/metrics
```
```json
{
  "http_avg_ms": 12.4,
  "https_avg_ms": 31.7,
  "http_samples": [...],
  "https_samples": [...]
}
```

---

### STEP 18 — Save Wireshark capture and screenshots

Stop the Wireshark capture (started in Step 12).

1. **Save as** `wireshark_capture.pcapng` in the project folder.
2. Apply filter `tcp.port == 80` — find and screenshot the **TCP 3-way handshake** (SYN, SYN-ACK, ACK).
3. Apply filter `tcp.port == 443` — find and screenshot the **TLS handshake** (ClientHello, ServerHello, Certificate).
4. Go to **Statistics → IO Graph** — screenshot the traffic rate chart.
5. Go to **Statistics → TCP Stream Graphs → Round Trip Time** — screenshot the RTT graph.

**Expected:** HTTP traffic should show plain-text data in packet details. HTTPS traffic should show encrypted TLS records (labeled `Application Data`) with no readable content — this is the visibility difference you are demonstrating.

---

### STEP 19 — Export router running configs

SSH to each router and save the running configuration to the `configs/` folder.

**From Client 1:**
```powershell
ssh -oKexAlgorithms=+diffie-hellman-group14-sha1 admin@192.165.10.37
# password: admin123
# at the R1# prompt:
show running-config
```
Copy the full output and paste into `configs/R1_config.txt`.

Repeat for R2:
```powershell
ssh -oKexAlgorithms=+diffie-hellman-group14-sha1 admin@192.165.20.37
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
| `wireshark_capture.pcapng` | Wireshark | Both HTTP and HTTPS traffic visible |
| Dashboard screenshot | Browser | Chart.js graph at localhost:5000 |
