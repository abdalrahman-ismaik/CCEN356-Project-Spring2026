"""
Script 2 - HTTP/HTTPS Traffic Capture with Scapy.

Captures HTTP (port 80) and HTTPS (port 443) packets, then logs them to CSV.
Run from a Client PC as Administrator on Windows or with sudo/root on Linux.
"""

import argparse
import csv
import os
from datetime import datetime
from pathlib import Path

from scapy.all import IFACES, IP, TCP, get_if_list, sniff

captured_packets = []
FIELDNAMES = ["timestamp", "src_ip", "dst_ip", "src_port", "dst_port", "protocol", "length"]
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_FILE = BASE_DIR / "data" / "traffic_log.csv"
DEFAULT_CLIENT_IPS = os.getenv("CCEN356_CAPTURE_CLIENT_IPS", "192.165.10.92,192.165.10.79")
DEFAULT_CAPTURE_TIMEOUT = int(os.getenv("CCEN356_CAPTURE_TIMEOUT_SEC", "60"))


def parse_client_ips(raw_value):
    """Parse comma-separated client IPs used for interface auto-selection."""
    return [item.strip() for item in str(raw_value).split(",") if item.strip()]


def packet_callback(packet):
    """Process each captured packet and filter for HTTP/HTTPS traffic."""
    if packet.haslayer(TCP) and packet.haslayer(IP):
        src_ip = packet[IP].src
        dst_ip = packet[IP].dst
        src_port = packet[TCP].sport
        dst_port = packet[TCP].dport
        pkt_len = len(packet)
        timestamp = datetime.now().strftime('%H:%M:%S.%f')

        if dst_port in [80, 443] or src_port in [80, 443]:
            protocol = "HTTPS" if (dst_port == 443 or src_port == 443) else "HTTP"
            entry = {
                'timestamp': timestamp,
                'src_ip': src_ip,
                'dst_ip': dst_ip,
                'src_port': src_port,
                'dst_port': dst_port,
                'protocol': protocol,
                'length': pkt_len,
            }
            captured_packets.append(entry)
            print(f"[{timestamp}] {protocol} | {src_ip}:{src_port} -> {dst_ip}:{dst_port} | {pkt_len} bytes")


def save_to_csv(filename):
    """Save captured packets to a CSV file."""
    output_path = Path(filename)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(captured_packets)
    print(f"\nSaved {len(captured_packets)} packets to {filename}")


def select_interface(client_ips, requested_iface=None):
    """Select a capture interface from a requested name, client IP list, or NIC description."""
    if requested_iface:
        return requested_iface

    print("Available interfaces:")
    for i, (idx, iface_obj) in enumerate(IFACES.items()):
        print(f"  [{i}] {iface_obj.name} - {iface_obj.description} (IP: {iface_obj.ip})")
    print()

    for idx, iface_obj in IFACES.items():
        if iface_obj.ip in client_ips:
            print(f"Auto-selected interface: {iface_obj.name} (IP: {iface_obj.ip})")
            return iface_obj.name

    for idx, iface_obj in IFACES.items():
        desc = (iface_obj.description or '').lower()
        if 'ethernet' in desc or 'realtek' in desc or 'intel' in desc:
            if iface_obj.ip and iface_obj.ip not in ('0.0.0.0', '127.0.0.1'):
                print(f"Fallback-selected interface: {iface_obj.name} (IP: {iface_obj.ip}, {iface_obj.description})")
                return iface_obj.name

    ifaces = get_if_list()
    iface = ifaces[0] if ifaces else 'Ethernet'
    print(f"Warning: Could not auto-detect - using '{iface}'. Re-run with --iface if no packets are captured.")
    return iface


def parse_args():
    parser = argparse.ArgumentParser(description="Capture HTTP/HTTPS packets to CSV with Scapy.")
    parser.add_argument("--iface", help="Capture interface name. Overrides auto-detection.")
    parser.add_argument("--duration", type=int, default=DEFAULT_CAPTURE_TIMEOUT, help="Capture duration in seconds.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_FILE), help="CSV output path.")
    parser.add_argument(
        "--client-ips",
        default=DEFAULT_CLIENT_IPS,
        help="Comma-separated client IPs used to auto-select the capture interface.",
    )
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    client_ips = parse_client_ips(args.client_ips)
    iface = select_interface(client_ips=client_ips, requested_iface=args.iface)

    print(f"\nStarting capture on interface '{iface}' for {args.duration} seconds...")
    print("Filtering HTTP (port 80) and HTTPS (port 443)\n")

    sniff(iface=iface, prn=packet_callback, timeout=args.duration,
          filter="tcp port 80 or tcp port 443")
    save_to_csv(args.output)
