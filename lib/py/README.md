# sniffy

Python library for communicating with the ESP32-C6 WiFi sniffer firmware over USB serial.

## Install

```bash
pip install pyserial

# or install from the requirements file
pip install -r lib/py/requirements.txt
```

## Usage

```python
import threading
from lib.py import SnifferClient

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

### Flock Detection Example

```python
import threading
from lib.py import SnifferClient, Frame

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

See `examples/py/example.py` for a full working example.

## API

### `SnifferClient`

```python
SnifferClient(port, baudrate=115200, on_frame=None)
```

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `port` | `str` | — | Serial port path (e.g. `/dev/ttyACM0`, `COM3`) |
| `baudrate` | `int` | `115200` | Baud rate (ignored for USB CDC-ACM) |
| `on_frame` | `(Frame) -> None` | no-op | Called for each captured WiFi frame |

Supports context manager (`with SnifferClient(...) as s:`).

#### Methods

| Method | Description |
|--------|-------------|
| `scan(channel=None)` | Start scanning. Omit channel to cycle all channels. |
| `stop()` | Stop scanning. |
| `promisc_on()` | Enable promiscuous mode. |
| `promisc_off()` | Disable promiscuous mode. |
| `promisc_status()` | Returns `True` if promiscuous mode is enabled. |
| `close()` | Close the serial connection and stop background threads. |

#### Properties

| Property | Type | Description |
|----------|------|-------------|
| `frame_count` | `int` | Total frames received |
| `dropped` | `int` | Estimated dropped frames (via sequence number gaps) |

### `Frame`

Captured 802.11 frame with metadata. Metadata fields are unpacked eagerly; MAC header fields are parsed lazily on first access.

#### Metadata

| Property | Type | Description |
|----------|------|-------------|
| `timestamp_us` | `int` | Microsecond timestamp |
| `channel` | `int` | WiFi channel |
| `rssi` | `int` | Signal strength (dBm) |
| `noise_floor` | `int` | Noise floor (dBm) |
| `pkt_type` | `int` | Packet type |
| `rx_state` | `int` | Receiver state |
| `rate` | `int` | Data rate |
| `seq_num` | `int` | Sequence number (for drop detection) |
| `raw` | `bytes` | Raw 802.11 frame bytes |

#### MAC Header (lazy)

| Property | Type | Description |
|----------|------|-------------|
| `frame_control` | `int` | Raw frame control field |
| `frame_type` | `int` | 802.11 type (0=Mgmt, 1=Ctrl, 2=Data) |
| `frame_subtype` | `int` | 802.11 subtype |
| `to_ds` / `from_ds` | `bool` | DS flags |
| `duration` | `int` | Duration/ID field |
| `addr1` / `addr2` / `addr3` | `bytes \| None` | Raw MAC addresses |
| `sequence_control` | `int \| None` | Sequence control field |
| `sequence_number` | `int \| None` | 802.11 sequence number |
| `fragment_number` | `int \| None` | Fragment number |

#### Derived Addresses (lazy)

| Property | Description |
|----------|-------------|
| `bssid` | BSSID, resolved based on To-DS/From-DS flags |
| `src` | Source address |
| `dst` | Destination address |

#### Information Elements

| Member | Description |
|--------|-------------|
| `iter_ies()` | Generator yielding `(ie_id, ie_data)` tuples |
| `ssid` | Extracted SSID string, `""` for hidden, `None` if absent |

#### Convenience

| Member | Description |
|--------|-------------|
| `is_beacon` | `True` if management beacon frame |
| `is_probe_req` | `True` if probe request |
| `is_probe_resp` | `True` if probe response |
| `Frame.mac_str(addr)` | Format MAC bytes as `"aa:bb:cc:dd:ee:ff"` |

### `SnifferError`

Raised when a command fails. Has `.cmd` and `.code` properties.

## CLI

The library includes a command-line interface:

| Command | Description |
|---------|-------------|
| `python -m lib.py PORT scan` | Scan all channels, print frames live (Ctrl+C to stop) |
| `python -m lib.py PORT scan -c 6` | Scan only channel 6 |
| `python -m lib.py PORT stop` | Stop scanning |
| `python -m lib.py PORT status` | Show whether promiscuous mode is on or off |
| `python -m lib.py PORT promisc` | Query promiscuous mode status |
| `python -m lib.py PORT promisc on` | Enable promiscuous mode |
| `python -m lib.py PORT promisc off` | Disable promiscuous mode |

The `scan` command streams captured frames to the terminal with human-readable output (channel, RSSI, frame type, MACs, SSID). Lines containing "flock" are highlighted in red.
