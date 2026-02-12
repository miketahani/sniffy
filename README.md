# sniffy
Forked and greatly expanded version of [Flock Safety Trap Shooter v0.3](https://github.com/GainSec/Flock-Safety-Trap-Shooter-Sniffer-Alarm) by [John Gaines](https://gainsec.com/). Includes a basic Python-based client library.

Custom firmware for the [M5NanoC6](ttps://shop.m5stack.com/products/m5stack-nanoc6-dev-kit) (ESP32-C6) that sniffs and then alerts you of nearby Flock Safety devices.

![M5NanoC6](https://gainsec.com/wp-content/uploads/2025/06/nanoc6.jpg)

## Features

Sniffings Client Probes and Broadcast Beacons looking for 'flock' case insensitive. Then alerts you of the SSID and stops sniffing. Suports WiFI 2.4/5/6.

![Probe Alert](https://gainsec.com/wp-content/uploads/2025/06/image-46.png)

![SSID Alert](https://gainsec.com/wp-content/uploads/2025/06/image-48.png)

## Setup & Installation

### Prerequisites

- [ESP-IDF](https://docs.espressif.com/projects/esp-idf/en/latest/esp32c6/get-started/) (v5.x)
- Python 3.8+
- An M5NanoC6 (or any ESP32-C6 board) connected via USB

### Build & Flash

```bash
# activate the ESP-IDF environment
source ~/path/to/esp-idf/export.sh

# set target (only needed once)
idf.py set-target esp32c6

# build
idf.py build

# flash (replace PORT with your device, e.g. /dev/ttyACM0 or /dev/cu.usbmodem*)
idf.py -p PORT flash

# optional: monitor raw serial output for debugging
idf.py -p PORT monitor
```

### Python Client Library

The `client/` directory contains a Python library for controlling the sniffer over USB serial.

```bash
# install pyserial
pip install pyserial

# or install from the requirements file
pip install -r client/requirements.txt
```

#### Quick Start

```python
import threading
from client import SnifferClient

def on_frame(frame):
    print(frame)
    print(f"  SSID: {frame.ssid}, RSSI: {frame.rssi}, Channel: {frame.channel}")

with SnifferClient("/dev/ttyACM0", on_frame=on_frame) as s:
    # start scanning all channels
    s.scan()

    # or scan a specific channel
    s.scan(channel=6)

    # block until you're ready to stop
    threading.Event().wait(timeout=60)

    # stop scanning
    s.stop()

    # check promiscuous mode
    print(s.promisc_status())  # True / False

    # enable/disable promiscuous mode directly
    s.promisc_on()
    s.promisc_off()

    print(f"Frames: {s.frame_count}, Dropped: ~{s.dropped}")
```

#### Captured Frame Fields

Each `Frame` object provides lazy-parsed 802.11 fields:

| Field | Description |
|-------|-------------|
| `channel` | Channel the frame was captured on |
| `rssi` | Signal strength (dBm) |
| `noise_floor` | Noise floor (dBm) |
| `timestamp_us` | Capture timestamp (microseconds) |
| `ssid` | SSID (from beacons/probes, `None` otherwise) |
| `src` / `dst` / `bssid` | MAC addresses (bytes) |
| `frame_type` / `frame_subtype` | 802.11 type/subtype |
| `is_beacon` / `is_probe_req` / `is_probe_resp` | Convenience booleans |
| `raw` | Raw 802.11 frame bytes |

Use `Frame.mac_str(frame.src)` to format a MAC address as `"aa:bb:cc:dd:ee:ff"`.

#### Flock Detection Example

```python
import threading
from client import SnifferClient, Frame

done = threading.Event()

def on_frame(frame):
    if frame.ssid and "flock" in frame.ssid.lower():
        print(f"ALERT: {frame.ssid} on ch {frame.channel} from {Frame.mac_str(frame.src)}")
        done.set()

with SnifferClient("/dev/ttyACM0", on_frame=on_frame) as s:
    s.scan()
    done.wait()
    s.stop()
```

See `client/example.py` for a full working example.

#### CLI

The client also includes a command-line interface. Run it with `python -m client`:

| Command | Description |
|---------|-------------|
| `python -m client /dev/ttyACM0 scan` | Scan all channels, print frames live (Ctrl+C to stop) |
| `python -m client /dev/ttyACM0 scan -c 6` | Scan only channel 6 |
| `python -m client /dev/ttyACM0 stop` | Stop scanning |
| `python -m client /dev/ttyACM0 status` | Show whether promiscuous mode is on or off |
| `python -m client /dev/ttyACM0 promisc` | Query promiscuous mode status |
| `python -m client /dev/ttyACM0 promisc on` | Enable promiscuous mode |
| `python -m client /dev/ttyACM0 promisc off` | Disable promiscuous mode |

The `scan` command streams captured frames to the terminal with human-readable output (channel, RSSI, frame type, MACs, SSID). Lines containing "flock" are highlighted in red.
