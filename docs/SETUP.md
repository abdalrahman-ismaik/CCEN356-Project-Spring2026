# Setup

This guide prepares the Python environment and local lab configuration for the CCEN 356 HTTP/HTTPS performance and visibility project.

## Python Version

Python 3.8 or newer is required. Python 3.10+ is recommended for a clean experience with current versions of Netmiko, Scapy, Flask, Pandas, and Matplotlib.

Check your version:

```powershell
python --version
```

## Virtual Environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Linux or macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Dependencies

The direct Python dependencies are listed in `requirements.txt`:

- `flask` for the HTTP server, HTTPS server, and dashboard
- `requests` and `urllib3` for endpoint probing and benchmarks
- `netmiko` for Cisco IOS SSH automation
- `scapy` for packet capture
- `matplotlib`, `numpy`, and `pandas` for chart generation and data analysis

## Local Configuration

Use `.env.example` as the public template for local values:

```powershell
Copy-Item .env.example .env
```

Edit `.env` locally if your lab addresses, ports, usernames, or QoS parameters differ. Do not commit `.env`.

Important variables:

```text
CCEN356_SERVER_HOST=192.165.20.79
CCEN356_HTTP_URL=http://192.165.20.79
CCEN356_HTTPS_URL=https://192.165.20.79
CCEN356_ROUTER_HOST=192.165.10.37
CCEN356_ROUTER_USERNAME=admin
CCEN356_ROUTER_PASSWORD=change-me
CCEN356_TLS_CERT_FILE=server/cert.pem
CCEN356_TLS_KEY_FILE=server/key.pem
```

PowerShell does not automatically load `.env` files. Either set variables manually in the shell or use your preferred local `.env` loader.

Example:

```powershell
$env:CCEN356_ROUTER_PASSWORD="<local-password>"
python scripts\ssh_connect.py
```

## HTTPS Certificate

The public repository intentionally does not include certificates or private keys. Generate them locally on the server PC.

OpenSSL:

```powershell
openssl req -x509 -newkey rsa:2048 -sha256 -days 365 -nodes `
  -keyout server/key.pem -out server/cert.pem `
  -subj "/CN=192.165.20.79/O=CCEN356Lab" `
  -addext "subjectAltName=IP:192.165.20.79"
```

If your server IP is different, update both `CN` and `subjectAltName`.

For browser testing, import `server/cert.pem` into the client machine's trusted certificate store. For command-line tests, `curl -k` or the Python scripts' default `verify=False` behavior can be used in this isolated lab.

## Windows Notes

- Run Scapy captures from an Administrator PowerShell window.
- Binding Flask directly to ports 80 and 443 may require Administrator privileges.
- Windows Defender Firewall must allow inbound TCP 80, TCP 443, and TCP 5000 if clients need remote access to the web services or dashboard.

Example firewall rules:

```powershell
New-NetFirewallRule -DisplayName "CCEN356 HTTP" -Direction Inbound -LocalPort 80 -Protocol TCP -Action Allow
New-NetFirewallRule -DisplayName "CCEN356 HTTPS" -Direction Inbound -LocalPort 443 -Protocol TCP -Action Allow
New-NetFirewallRule -DisplayName "CCEN356 Dashboard" -Direction Inbound -LocalPort 5000 -Protocol TCP -Action Allow
```

## Linux Notes

- Run Scapy with `sudo` or give Python the required capture capability.
- Binding to ports below 1024 may require `sudo`. For development, set non-privileged ports:

```bash
export CCEN356_HTTP_PORT=8080
export CCEN356_HTTPS_PORT=8443
python server/http_server.py
python server/secured_server.py
```

Update `CCEN356_HTTP_URL` and `CCEN356_HTTPS_URL` to match any alternate ports.
