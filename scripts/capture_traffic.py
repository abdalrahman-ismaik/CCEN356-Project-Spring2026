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

    # Show all available interfaces so user can verify the correct one
    from scapy.all import conf, IFACES
    print("Available interfaces:")
    for i, (idx, iface_obj) in enumerate(IFACES.items()):
        print(f"  [{i}] {iface_obj.name} — {iface_obj.description} (IP: {iface_obj.ip})")
    print()

    # Pick the interface whose IP matches this client's address
    CLIENT_IPS = ['192.165.10.92', '192.165.10.79']
    iface = None
    for idx, iface_obj in IFACES.items():
        if iface_obj.ip in CLIENT_IPS:
            iface = iface_obj.name
            print(f"Auto-selected interface: {iface} (IP: {iface_obj.ip})")
            break

    # Fallback: try matching by description keywords
    if iface is None:
        for idx, iface_obj in IFACES.items():
            desc = (iface_obj.description or '').lower()
            if 'ethernet' in desc or 'realtek' in desc or 'intel' in desc:
                if iface_obj.ip and iface_obj.ip != '0.0.0.0' and iface_obj.ip != '127.0.0.1':
                    iface = iface_obj.name
                    print(f"Fallback-selected interface: {iface} (IP: {iface_obj.ip}, {iface_obj.description})")
                    break

    if iface is None:
        ifaces = get_if_list()
        iface = ifaces[0] if ifaces else 'Ethernet'
        print(f"Warning: Could not auto-detect — using '{iface}'. If 0 packets are captured, re-run with the correct interface name.")

    print(f"\nStarting capture on interface '{iface}' for 60 seconds...")
    print("Filtering HTTP (port 80) and HTTPS (port 443)\n")

    sniff(iface=iface, prn=packet_callback, timeout=60,
          filter="tcp port 80 or tcp port 443")
    save_to_csv(output_file)
