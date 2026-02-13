# sniffy
Forked and greatly expanded version of [Flock Safety Trap Shooter v0.3](https://github.com/GainSec/Flock-Safety-Trap-Shooter-Sniffer-Alarm) by [John Gaines](https://gainsec.com/).

Custom firmware for the [M5NanoC6](ttps://shop.m5stack.com/products/m5stack-nanoc6-dev-kit) (ESP32-C6) that sniffs and then alerts you of nearby Flock Safety devices.

Includes client libraries for [Python](lib/py/) (`pyserial`) and [TypeScript](lib/ts/) (Web Serial API).

## Setup & Installation

### Prerequisites

- [ESP-IDF](https://docs.espressif.com/projects/esp-idf/en/latest/esp32c6/get-started/) (v5.x)
- Python 3.8+
- An M5NanoC6 (or any ESP32-C6 board) connected via USB

### Build & Flash

```bash
# install ESP-IDF (one-time setup); replace `~/esp` with any desired path

mkdir -p ~/esp && cd ~/esp
git clone --recursive https://github.com/espressif/esp-idf.git
cd esp-idf
./install.sh esp32c6
```

```bash
# activate the ESP-IDF environment
source ~/esp/esp-idf/export.sh

# set target (only needed once)
idf.py set-target esp32c6

# build
idf.py build

# flash (replace PORT with your device, e.g. /dev/ttyACM0 or /dev/cu.usbmodem*)
idf.py -p PORT flash

# optional: monitor raw serial output for debugging
idf.py -p PORT monitor
```

## Serial Protocol

The device communicates over USB Serial CDC-ACM (115200 baud). Messages are COBS-encoded binary.

### Message Format

Every message (command, response, or event) starts with a 4-byte header:

```
offset  size  field        description
0       1     msg_type     message type (see tables below)
1       1     flags        status flags
2       2     payload_len  payload length (little-endian)
```

Followed by `payload_len` bytes of type-specific payload. The entire header+payload is then COBS-encoded and wrapped in `0x00` delimiters before being sent.

### Commands (Client → Device)

| Type | Name | Payload | Response | Description |
|------|------|---------|----------|-------------|
| `0x01` | Scan Start | 2 bytes: channel + filter (see below) | ACK | Start WiFi scanning |
| `0x02` | Scan Stop | — | ACK | Stop WiFi scanning |
| `0x03` | Promisc On | — | ACK | Enable promiscuous mode |
| `0x04` | Promisc Off | — | ACK | Disable promiscuous mode |
| `0x05` | Promisc Query | — | Promisc Status | Query promiscuous mode state |

#### Scan Start payload

| Byte | Field | Values |
|------|-------|--------|
| 0 | channel | `0` = all channels, or a specific channel number |
| 1 | frame_filter | Bitmask of frame types to capture (see below) |

**Frame filter values:**

| Value | Name | Description |
|-------|------|-------------|
| `0x00` | All | Capture all frame types (management + control + data) |
| `0x01` | Management | Management frames (beacons, probes, auth, etc.) |
| `0x02` | Control | Control frames (RTS, CTS, ACK, etc.) |
| `0x04` | Data | Data frames (QoS data, null, EAPOL, etc.) |

Values can be OR'd together (e.g. `0x05` = management + data).

#### Valid channels

- `1–13` (2.4 GHz)

- `36`, `40`, `44`, `48`, `149`, `153`, `157`, `161`, `165` (5 GHz)

In all-channel mode the firmware dwells ~2.5 seconds per channel.

### Responses (Device → Client)

| Type | Name | Payload | Description |
|------|------|---------|-------------|
| `0x81` | ACK | 1 byte: echoed command type | Command processed successfully |
| `0x82` | Error | 1 byte: command type, 1 byte: error code | Command failed (see error codes) |
| `0x83` | Promisc Status | 1 byte: `1` = on, `0` = off | Promiscuous mode state |

**Error Codes:**

| Code | Name | Description |
|------|------|-------------|
| `0x01` | `ERR_UNKNOWN_CMD` | Unknown command type |
| `0x02` | `ERR_INVALID_CHANNEL` | Invalid WiFi channel number |
| `0x03` | `ERR_WIFI_FAIL` | WiFi subsystem error |
| `0x04` | `ERR_SCAN_ACTIVE` | Scan already active (stop first) |
| `0x05` | `ERR_INVALID_FILTER` | Invalid frame filter bitmask |

### Events (Device → Client)

#### `0xC0` — Frame

An asynchronous event sent for each captured WiFi frame. The payload is a 16-byte metadata header followed by the raw 802.11 frame bytes.

**Metadata (16 bytes, little-endian):**

```
offset  size  type    field        description
0       4     u32     timestamp    capture time (microseconds)
4       2     u16     frame_len    length of raw frame data
6       1     u8      channel      WiFi channel
7       1     i8      rssi         signal strength (dBm)
8       1     i8      noise_floor  noise floor (dBm)
9       1     u8      pkt_type     WiFi packet type
10      1     u8      rx_state     receiver state
11      1     u8      rate         data rate
12      2     u16     seq_num      sequence number (for drop detection)
14      2     u16     reserved     (unused)
```

The firmware increments `seq_num` for each frame it sends. Gaps in the sequence indicate dropped frames (due to full buffers or TX queue pressure). The counter is 16-bit and wraps around.

**Raw frame data** (`frame_len` bytes) follows the metadata. This is the raw 802.11 frame as captured by the radio.
