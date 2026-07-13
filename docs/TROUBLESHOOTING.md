# Troubleshooting

Use this guide when the lab does not behave as expected.

## Missing Static Routes

Symptoms:

- Clients can ping their default gateway but cannot reach the server.
- Server can ping R2 but cannot reach clients.
- HTTP/HTTPS requests time out.

Checks:

```text
show ip route
show ip interface brief
```

Expected routes:

```text
R1 -> ip route 192.165.20.0 255.255.255.0 10.1.5.22
R2 -> ip route 192.165.10.0 255.255.255.0 10.1.5.21
```

## Router SSH Connection Issues

Symptoms:

- `scripts/ssh_connect.py` times out.
- SSH client reports no matching key exchange, host key, cipher, or MAC.
- Netmiko authentication fails.

Checks:

```text
show ip ssh
show running-config | section line vty|username|ip ssh
show ip interface brief
```

Fixes:

- Confirm the router has an IP reachable from the client.
- Confirm `ip ssh version 2` is enabled.
- Confirm a local username exists.
- Use environment variables instead of hardcoding passwords:

```powershell
$env:CCEN356_ROUTER_PASSWORD="<local-password>"
python scripts\ssh_connect.py
```

Older Cisco IOS versions may require legacy SSH algorithms from a modern OpenSSH client. Use those only in the isolated lab.

## Interface Down Or Wrong Port

Symptoms:

- `show ip interface brief` shows `administratively down`.
- Pings fail at the first hop.
- Switch port LEDs are off or amber for a long time.

Fixes:

```text
configure terminal
interface GigabitEthernet0/0
 no shutdown
interface GigabitEthernet0/1
 no shutdown
end
write memory
```

Also confirm physical cabling and switch port status:

```text
show interfaces status
```

## HTTPS Self-Signed Certificate Warnings

Symptoms:

- Browser shows an untrusted certificate warning.
- `curl https://...` fails certificate verification.
- Python HTTPS requests fail when TLS verification is enabled.

Fixes:

- Generate a certificate with a Subject Alternative Name matching the server IP.
- For lab-only CLI tests, use `curl -k`.
- For browser demos, import `server/cert.pem` into the trusted certificate store.
- Keep `server/key.pem` private and never commit it.

## Python Dependency Issues

Symptoms:

- `ModuleNotFoundError` for `netmiko`, `scapy`, `flask`, `pandas`, or `matplotlib`.
- Packages install globally instead of inside the project.

Fix:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

On Linux/macOS, use `source .venv/bin/activate`.

## Scapy Permission Or Interface Issues

Symptoms:

- Permission denied during capture.
- Capture completes with zero packets.
- Wrong network adapter is selected.

Fixes:

- Run as Administrator on Windows or with `sudo` on Linux.
- Specify the interface:

```powershell
python scripts\capture_traffic.py --iface "Ethernet" --duration 60
```

- Confirm traffic is actually being generated while capture is running.

## Dashboard Not Updating

Symptoms:

- Dashboard shows stale values.
- Endpoints show DOWN even though the server is running.
- `/api/metrics` returns old-looking data.

Fixes:

- Restart old dashboard instances so only one process owns port 5000.
- Confirm the target URLs:

```powershell
$env:CCEN356_HTTP_URL="http://192.165.20.79"
$env:CCEN356_HTTPS_URL="https://192.165.20.79"
python scripts\dashboard.py
```

- Check that the HTTP and HTTPS servers are still running.
- Open firewall port 5000 if remote clients need dashboard access.

## QoS Verification Problems

Symptoms:

- QoS appears to have no effect.
- `show policy-map interface` counters stay at zero.
- ACL counters do not increase during tests.

Checks:

```text
show access-lists
show policy-map interface GigabitEthernet0/0
show running-config | section class-map|policy-map|service-policy|access-list
```

Fixes:

- Confirm traffic matches TCP/80 or TCP/443.
- Confirm the service policy is applied to the active outbound interface.
- Generate enough concurrent traffic to make queueing effects visible.
- Compare both router counters and endpoint latency, because QoS effects can be subtle in a small lab.
