"""
Script 2 — HTTP/HTTPS Traffic Capture with Scapy

Captures HTTP (port 80) and HTTPS (port 443) packets for 60 seconds, logs to CSV.
Run from Client PC as Administrator (Windows):
    python capture_traffic.py
"""

from scapy.all import sniff, TCP, IP, get_if_list
import csv
import os
from datetime import datetime

captured_packets = []


def packet_callback(packet):
    """Process each captured packet — filter for HTTP/HTTPS traffic."""
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
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, 'w', newline='') as f:
        if captured_packets:
            writer = csv.DictWriter(f, fieldnames=captured_packets[0].keys())
            writer.writeheader()
            writer.writerows(captured_packets)
    print(f"\nSaved {len(captured_packets)} packets to {filename}")


if __name__ == '__main__':
    output_file = os.path.join(os.path.dirname(__file__), '..', 'data', 'traffic_log.csv')

    # Auto-detect interface: prefer Ethernet, fall back to first available
    ifaces = get_if_list()
    iface = None
    for name in ifaces:
        if 'ethernet' in name.lower() or 'eth' in name.lower():
            iface = name
            break
    if iface is None:
        iface = ifaces[0] if ifaces else 'Ethernet'

    print(f"Starting capture on interface '{iface}' for 60 seconds...")
    print("Filtering HTTP (port 80) and HTTPS (port 443)\n")

    sniff(iface=iface, prn=packet_callback, timeout=60)
    save_to_csv(output_file)
