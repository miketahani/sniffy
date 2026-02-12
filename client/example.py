#!/usr/bin/env python3
"""Example: scan for WiFi frames and print them."""

import sys
import time
from client import SnifferClient

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyACM0"


def on_frame(frame):
    print(frame)


with SnifferClient(PORT, on_frame=on_frame) as s:
    # check promiscuous mode status
    print(f"Promiscuous mode: {s.promisc_status()}")

    # start scanning all channels
    print("Scanning all channels...")
    s.scan()
    time.sleep(15)

    # switch to single channel
    print("Switching to channel 6...")
    s.scan(channel=6)
    time.sleep(10)

    # stop
    print("Stopping scan...")
    s.stop()

    print(f"Total frames captured: {len(s.frames)}")
    print(f"Frames dropped (estimated): {s.dropped}")
