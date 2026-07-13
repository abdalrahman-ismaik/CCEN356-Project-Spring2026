"""
Script 1 - SSH Connection and Device Info via Netmiko.

Connects to a Cisco router via SSH, runs show commands, and prints output.
Credentials are read from environment variables or prompted at runtime.
"""

import argparse
import getpass
import os

from netmiko import ConnectHandler


DEFAULT_ROUTER_HOST = os.getenv("CCEN356_ROUTER_HOST", "192.165.10.37")
DEFAULT_ROUTER_USERNAME = os.getenv("CCEN356_ROUTER_USERNAME", "admin")

DEFAULT_COMMANDS = [
    "show ip interface brief",
    "show ip route",
    "show access-lists",
    "show policy-map interface GigabitEthernet0/0",
]


def connect_to_device(host, username, password, secret=None, commands=None):
    """Connect to a Cisco IOS device and collect show command outputs."""
    if not password:
        raise ValueError(
            "Router password was not provided. Set CCEN356_ROUTER_PASSWORD "
            "or run this script interactively."
        )

    device = {
        'device_type': 'cisco_ios',
        'host': host,
        'username': username,
        'password': password,
        'secret': secret or password,
    }

    print(f"Connecting to {host}...")
    connection = ConnectHandler(**device)
    connection.enable()
    print(f"Connected to {host} - privileged exec mode.\n")

    results = {}
    for cmd in commands or DEFAULT_COMMANDS:
        output = connection.send_command(cmd)
        results[cmd] = output
        print(f"--- {cmd} ---")
        print(output)
        print()

    connection.disconnect()
    print(f"Disconnected from {host}.")
    return results


def parse_args():
    parser = argparse.ArgumentParser(description="Collect Cisco IOS show output over SSH.")
    parser.add_argument("--host", default=DEFAULT_ROUTER_HOST, help="Router management IP or hostname")
    parser.add_argument("--username", default=DEFAULT_ROUTER_USERNAME, help="Router SSH username")
    parser.add_argument(
        "--password",
        default=os.getenv("CCEN356_ROUTER_PASSWORD"),
        help="Router SSH password. Prefer CCEN356_ROUTER_PASSWORD to avoid shell history.",
    )
    parser.add_argument(
        "--secret",
        default=os.getenv("CCEN356_ROUTER_SECRET"),
        help="Enable secret. Defaults to the SSH password when omitted.",
    )
    parser.add_argument(
        "--command",
        dest="commands",
        action="append",
        help="Additional/alternate show command. Repeat to run multiple commands.",
    )
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    password = args.password or getpass.getpass(f"Password for {args.username}@{args.host}: ")
    secret = args.secret or os.getenv("CCEN356_ROUTER_SECRET") or password
    connect_to_device(
        host=args.host,
        username=args.username,
        password=password,
        secret=secret,
        commands=args.commands or DEFAULT_COMMANDS,
    )
