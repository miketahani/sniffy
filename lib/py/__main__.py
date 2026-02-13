#!/usr/bin/env python3
"""CLI for the Flock Safety sniffer."""

import argparse
import signal
import sys
import threading

from .sniffer_client import SnifferClient, SnifferError, FILTER_MGMT, FILTER_CTRL, FILTER_DATA
from .frame import Frame

FILTER_NAMES = {
    "mgmt": FILTER_MGMT,
    "ctrl": FILTER_CTRL,
    "data": FILTER_DATA,
}

# frame type/subtype names for human-readable output
FRAME_TYPE_NAMES = {0: "Mgmt", 1: "Ctrl", 2: "Data", 3: "Misc"}
MGMT_SUBTYPE_NAMES = {
    0: "AssocReq",
    1: "AssocResp",
    2: "ReassocReq",
    3: "ReassocResp",
    4: "ProbeReq",
    5: "ProbeResp",
    8: "Beacon",
    9: "ATIM",
    10: "Disassoc",
    11: "Auth",
    12: "Deauth",
    13: "Action",
}


def frame_type_str(frame: Frame) -> str:
    tname = FRAME_TYPE_NAMES.get(frame.frame_type, f"T{frame.frame_type}")
    if frame.frame_type == 0:
        sname = MGMT_SUBTYPE_NAMES.get(frame.frame_subtype, f"S{frame.frame_subtype}")
        return f"{tname}/{sname}"
    return f"{tname}/S{frame.frame_subtype}"


def print_frame(frame: Frame) -> None:
    src = Frame.mac_str(frame.src)
    dst = Frame.mac_str(frame.dst)
    ftype = frame_type_str(frame)
    parts = [
        f"ch={frame.channel:<3d}",
        f"rssi={frame.rssi:<4d}",
        f"{ftype:<16s}",
        f"{src} -> {dst}",
    ]
    ssid = frame.ssid
    if ssid is not None and ssid != "":
        parts.append(f'ssid="{ssid}"')

    # highlight flock detections
    line = "  ".join(parts)
    if ssid and "flock" in ssid.lower():
        line = f"\033[1;31m*** ALERT ***  {line}\033[0m"

    print(line, flush=True)


def parse_filter(value: str) -> int:
    """Parse a comma-separated filter string into a bitmask."""
    if value == "all":
        return 0
    mask = 0
    for name in value.split(","):
        name = name.strip().lower()
        if name not in FILTER_NAMES:
            raise argparse.ArgumentTypeError(
                f"unknown filter {name!r} (choose from: all, mgmt, ctrl, data)"
            )
        mask |= FILTER_NAMES[name]
    return mask


def cmd_scan(client: SnifferClient, args: argparse.Namespace) -> None:
    channel = args.channel
    filt = parse_filter(args.filter)
    parts = []
    if channel:
        parts.append(f"channel {channel}")
    else:
        parts.append("all channels")
    if filt:
        names = [n for n, v in FILTER_NAMES.items() if filt & v]
        parts.append(f"filter={','.join(names)}")
    else:
        parts.append("filter=all")
    print(f"Scanning {', '.join(parts)}... (Ctrl+C to stop)")

    done = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: done.set())

    client.scan(channel=channel, frame_filter=filt)
    done.wait()

    client.stop()
    print(
        f"\nStopped. {client.frame_count} frames captured, ~{client.dropped} dropped."
    )


def cmd_stop(client: SnifferClient, args: argparse.Namespace) -> None:
    client.stop()
    print("Scan stopped.")


def cmd_status(client: SnifferClient, args: argparse.Namespace) -> None:
    enabled = client.promisc_status()
    print(f"Promiscuous mode: {'ON' if enabled else 'OFF'}")


def cmd_promisc(client: SnifferClient, args: argparse.Namespace) -> None:
    action = args.action
    if action is None:
        # query
        enabled = client.promisc_status()
        print(f"Promiscuous mode: {'ON' if enabled else 'OFF'}")
    elif action == "on":
        client.promisc_on()
        print("Promiscuous mode enabled.")
    elif action == "off":
        client.promisc_off()
        print("Promiscuous mode disabled.")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m lib.py",
        description="Flock Safety sniffer CLI",
    )
    parser.add_argument("port", help="Serial port (e.g. /dev/ttyACM0, COM3)")
    parser.add_argument(
        "--baud", type=int, default=115200, help="Baud rate (default: 115200)"
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="Start scanning for WiFi frames")
    p_scan.add_argument(
        "-c",
        "--channel",
        type=int,
        default=None,
        help="Channel to scan (omit for all channels)",
    )
    p_scan.add_argument(
        "-f",
        "--filter",
        type=str,
        default="all",
        help="Frame type filter: all, mgmt, ctrl, data (comma-separated, e.g. mgmt,data)",
    )

    sub.add_parser("stop", help="Stop scanning")
    sub.add_parser("status", help="Query promiscuous mode status")

    p_promisc = sub.add_parser("promisc", help="Control promiscuous mode")
    p_promisc.add_argument(
        "action",
        nargs="?",
        choices=["on", "off"],
        help="on/off (omit to query current status)",
    )

    args = parser.parse_args()

    on_frame = print_frame if args.command == "scan" else None

    try:
        client = SnifferClient(args.port, baudrate=args.baud, on_frame=on_frame)
    except Exception as e:
        print(f"Error opening {args.port}: {e}", file=sys.stderr)
        return 1

    try:
        if args.command == "scan":
            cmd_scan(client, args)
        elif args.command == "stop":
            cmd_stop(client, args)
        elif args.command == "status":
            cmd_status(client, args)
        elif args.command == "promisc":
            cmd_promisc(client, args)
    except SnifferError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        client.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
