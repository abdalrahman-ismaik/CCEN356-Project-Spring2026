# CCEN356 Project — HTTP/HTTPS Performance & Visibility

Compare HTTP vs HTTPS performance using physical Cisco networking equipment, Python automation, Wireshark analysis, and data visualization.

## Team

- 2 members
- Spring 2026

## Network Topology

```
[Client 1: 192.165.10.92] ──┐
[Client 2: 192.165.10.79] ──┤── [SW1 (2960)] ── [R1 (2901)] ── [R2 (2901)] ── [Server: 192.165.20.79]
                            └── (SPAN port)
```

## Setup

### 0. Configure Cisco Routers (via console cable)

Connect to each router with a console cable (PuTTY / terminal emulator) and paste the config below.

**R1 — SSH & Network Setup:**
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

end
write memory
```

**R2 — SSH & Network Setup:**
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

**Verify SSH is enabled on each router:**
```
show ip ssh
show ip interface brief
```
- `show ip ssh` should say `SSH Enabled - version 2.0`
- Interfaces should show `up/up`

**Test SSH from a client PC before running scripts:**
```bash
ssh admin@192.165.10.37
# Password: admin123
```

### 1. Install Python dependencies (on client PCs)

```bash
pip install -r requirements.txt
```

### 2. Generate SSL certificates (on Windows server)

**Option A — Python (recommended, works everywhere):**
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

### 3. Open Windows Firewall ports (run PowerShell as Administrator)

```powershell
New-NetFirewallRule -DisplayName "CCEN356 HTTP" -Direction Inbound -LocalPort 80 -Protocol TCP -Action Allow
New-NetFirewallRule -DisplayName "CCEN356 HTTPS" -Direction Inbound -LocalPort 443,8443 -Protocol TCP -Action Allow
New-NetFirewallRule -DisplayName "CCEN356 Allow Ping" -Direction Inbound -Protocol ICMPv4 -IcmpType 8 -Action Allow
```

### 4. Start servers (on Windows server — 192.165.20.79)

```powershell
# Terminal 1 (run as Administrator for port 80)
python server\http_server.py

# Terminal 2
python server\secured_server.py
```

### 5. Verify connectivity (from client PCs)

```bash
ping 192.165.20.79
curl http://192.165.20.79
curl -k https://192.165.20.79
```

## Running the Scripts

Execute from client PCs in order:

```bash
# 1. SSH to router and collect show commands
python3 scripts/ssh_connect.py

# 2. Capture traffic (requires sudo, run on Client 1)
sudo python3 scripts/capture_traffic.py

# 3. Performance benchmark (run on Client 2 while capture is active)
python3 scripts/performance_metrics.py

# 4. Generate charts (after capture completes) 
python3 scripts/visualize_traffic.py

# 5. Live dashboard
python3 scripts/dashboard.py
# Then visit http://localhost:5000
```

## Project Structure

```
├── scripts/
│   ├── ssh_connect.py            # Netmiko SSH to routers
│   ├── capture_traffic.py        # Scapy packet capture
│   ├── performance_metrics.py    # HTTP vs HTTPS benchmarking
│   ├── visualize_traffic.py      # Matplotlib charts
│   └── dashboard.py              # Flask live dashboard
├── server/
│   ├── http_server.py            # Flask HTTP (port 80) — primary HTTP server
│   ├── secured_server.py         # Flask HTTPS (port 8443) — primary HTTPS server
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

## Outputs

| File | Source |
|---|---|
| `data/traffic_log.csv` | `capture_traffic.py` |
| `data/performance_results.csv` | `performance_metrics.py` |
| `charts/performance_comparison.png` | `visualize_traffic.py` |
| `charts/traffic_analysis.png` | `visualize_traffic.py` |
| `configs/R1_config.txt` | `show running-config` from R1 |
| `configs/R2_config.txt` | `show running-config` from R2 |
