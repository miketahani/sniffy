# sniffy
Forked and greatly expanded version of [Flock Safety Trap Shooter v0.3](https://github.com/GainSec/Flock-Safety-Trap-Shooter-Sniffer-Alarm) by [John Gaines](https://gainsec.com/).

Custom firmware for the [M5NanoC6](ttps://shop.m5stack.com/products/m5stack-nanoc6-dev-kit) (ESP32-C6) that sniffs and then alerts you of nearby Flock Safety devices.

Includes client libraries for [Python](lib/py/) and [TypeScript](lib/ts/) (Web Serial).

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

## Client Libraries

| Library | Path | Description |
|---------|------|-------------|
| [Python](lib/py/) | `lib/py/` | USB serial client via `pyserial` |
| [TypeScript](lib/ts/) | `lib/ts/` | Browser client via Web Serial API |

See each library's README for installation, API docs, and usage examples.

## Serial Protocol

The device communicates over USB Serial CDC-ACM (115200 baud). Messages are binary, COBS-encoded, and delimited by `0x00` bytes.

### Message Format

Every message (command, response, or event) starts with a 4-byte header:

```
offset  size  field        description
0       1     msg_type     message type (see tables below)
1       1     flags        status flags
2       2     payload_len  payload length (little-endian)
```

Followed by `payload_len` bytes of type-specific payload. The entire header+payload is then COBS-encoded and wrapped in `0x00` delimiters before being sent over the wire:

```
0x00 <COBS-encoded header+payload> 0x00
```

### Commands (Client → Device)

#### `0x01` — Scan Start

Start WiFi scanning.

| Payload | Size | Description |
|---------|------|-------------|
| channel | 1 byte | Channel to scan. `0` = cycle through all channels. |

Valid channels: 1–13 (2.4 GHz), 36, 40, 44, 48, 149, 153, 157, 161, 165 (5 GHz).

In all-channel mode the firmware dwells ~2.5 seconds per channel.

**Response:** ACK (`0x81`)

#### `0x02` — Scan Stop

Stop WiFi scanning.

**Payload:** none

**Response:** ACK (`0x81`)

#### `0x03` — Promiscuous Mode On

Enable promiscuous mode.

**Payload:** none

**Response:** ACK (`0x81`)

#### `0x04` — Promiscuous Mode Off

Disable promiscuous mode.

**Payload:** none

**Response:** ACK (`0x81`)

#### `0x05` — Promiscuous Mode Query

Query whether promiscuous mode is active.

**Payload:** none

**Response:** Promiscuous Status (`0x83`)

### Responses (Device → Client)

#### `0x81` — ACK

Acknowledges a command was processed successfully.

| Payload | Size | Description |
|---------|------|-------------|
| cmd_type | 1 byte | The command type that was acknowledged |

#### `0x82` — Error

A command failed.

| Payload | Size | Description |
|---------|------|-------------|
| cmd_type | 1 byte | The command type that failed |
| error_code | 1 byte | Error code (see below) |

**Error Codes:**

| Code | Name | Description |
|------|------|-------------|
| `0x01` | `ERR_UNKNOWN_CMD` | Unknown command type |
| `0x02` | `ERR_INVALID_CHANNEL` | Invalid WiFi channel number |
| `0x03` | `ERR_WIFI_FAIL` | WiFi subsystem error |
| `0x04` | `ERR_SCAN_ACTIVE` | Scan already active (stop first) |

#### `0x83` — Promiscuous Status

Reports whether promiscuous mode is enabled.

| Payload | Size | Description |
|---------|------|-------------|
| enabled | 1 byte | `1` = on, `0` = off |

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

### COBS Framing

All messages are encoded with [Consistent Overhead Byte Stuffing (COBS)](https://en.wikipedia.org/wiki/Consistent_Overhead_Byte_Stuffing) before transmission. COBS eliminates `0x00` bytes from the encoded output, allowing `0x00` to be used as an unambiguous message delimiter.

To send a message:
1. Build the raw message (4-byte header + payload)
2. COBS-encode the raw message
3. Transmit: `0x00` + encoded bytes + `0x00`

To receive a message:
1. Accumulate bytes until a `0x00` delimiter
2. COBS-decode the bytes between delimiters
3. Parse the 4-byte header and payload from the decoded result
