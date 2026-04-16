"""
Script 1 — SSH Connection & Device Info via Netmiko

Connects to a Cisco router via SSH, runs show commands, and prints output.
Run from Client PC (192.165.10.92 or .79):
    python ssh_connect.py
"""

from netmiko import ConnectHandler


def connect_to_device(host, username='admin', password='admin123'):
    """Connect to a Cisco IOS device and collect show command outputs."""
    device = {
        'device_type': 'cisco_ios',
        'host': host,
        'username': username,
        'password': password,
        'secret': password,
    }

    print(f"Connecting to {host}...")
    connection = ConnectHandler(**device)
    connection.enable()
    print(f"Connected to {host} — privileged exec mode.\n")

    commands = [
        'show ip interface brief',
        'show ip route',
        'show access-lists',
        'show policy-map interface GigabitEthernet0/0',
    ]

    results = {}
    for cmd in commands:
        output = connection.send_command(cmd)
        results[cmd] = output
        print(f"--- {cmd} ---")
        print(output)
        print()

    connection.disconnect()
    print(f"Disconnected from {host}.")
    return results


if __name__ == '__main__':
    connect_to_device('192.165.10.37')
