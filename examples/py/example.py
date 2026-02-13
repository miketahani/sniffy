#!/usr/bin/env python3
"""Example: scan for WiFi frames and print them."""

import sys
import threading
from lib.py import SnifferClient, FILTER_MGMT, FILTER_DATA

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyACM0"


def on_frame(frame):
    print(frame)


with SnifferClient(PORT, on_frame=on_frame) as s:
    # check promiscuous mode status
    print(f"Promiscuous mode: {s.promisc_status()}")

    done = threading.Event()

    # start scanning all channels (all frame types)
    print("Scanning all channels (all frame types)...")
    s.scan()
    done.wait(timeout=15)

    # switch to single channel with management + data frames only
    print("Switching to channel 6 (mgmt + data frames)...")
    s.scan(channel=6, frame_filter=FILTER_MGMT | FILTER_DATA)
    done.wait(timeout=10)

    # stop
    print("Stopping scan...")
    s.stop()

    print(f"Total frames captured: {s.frame_count}")
    print(f"Frames dropped (estimated): {s.dropped}")
