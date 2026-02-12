# sniffy

TypeScript library for communicating with the ESP32-C6 WiFi sniffer firmware via [Web Serial API](https://developer.chrome.com/docs/capabilities/serial).

## Install

```bash
npm install
npm run build
```

## Usage

```ts
import { SnifferClient, Frame } from "sniffy";

const client = new SnifferClient({
  onFrame(frame: Frame) {
    console.log(frame.toString());
  },
  onDisconnect() {
    console.log("device disconnected");
  },
});

// must be called from a user gesture (click, keypress, etc.)
button.onclick = async () => {
  await client.connect();
  await client.scan(6); // scan channel 6
};

// later...
await client.stop();
await client.disconnect();
```

## API

### `SnifferClient`

```ts
new SnifferClient(options?)
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `baudRate` | `number` | `115200` | Baud rate (ignored for USB CDC-ACM) |
| `onFrame` | `(frame: Frame) => void` | no-op | Called for each captured WiFi frame |
| `onDisconnect` | `() => void` | no-op | Called on unexpected disconnect |
| `filters` | `SerialPortFilter[]` | `[]` | USB vendor/product filters for port picker |

#### Methods

| Method | Description |
|--------|-------------|
| `connect(port?)` | Open the serial port. Triggers the browser port picker if no port is passed. |
| `scan(channel?)` | Start scanning. Omit channel to cycle all channels. |
| `stop()` | Stop scanning. |
| `promiscOn()` | Enable promiscuous mode. |
| `promiscOff()` | Disable promiscuous mode. |
| `promiscStatus()` | Returns `true` if promiscuous mode is enabled. |
| `disconnect()` | Close the serial connection. |

All methods are async. `connect()` must be called from a user gesture.

#### Properties

| Property | Type | Description |
|----------|------|-------------|
| `connected` | `boolean` | Whether a serial port is open |
| `frameCount` | `number` | Total frames received |
| `dropped` | `number` | Estimated dropped frames (via sequence number gaps) |

### `Frame`

Captured 802.11 frame with metadata. Metadata fields are unpacked eagerly; MAC header fields are parsed lazily on first access.

#### Metadata

| Property | Type | Description |
|----------|------|-------------|
| `timestampUs` | `number` | Microsecond timestamp |
| `channel` | `number` | WiFi channel |
| `rssi` | `number` | Signal strength (dBm) |
| `noiseFloor` | `number` | Noise floor (dBm) |
| `pktType` | `number` | Packet type |
| `rxState` | `number` | Receiver state |
| `rate` | `number` | Data rate |
| `seqNum` | `number` | Sequence number (for drop detection) |
| `raw` | `Uint8Array` | Raw 802.11 frame bytes |

#### MAC Header (lazy)

`frameControl`, `frameType`, `frameSubtype`, `toDs`, `fromDs`, `duration`, `addr1`, `addr2`, `addr3`, `sequenceControl`, `sequenceNumber`, `fragmentNumber`

#### Derived Addresses (lazy)

`bssid`, `src`, `dst` — resolved based on To-DS/From-DS flags.

#### Information Elements

| Member | Description |
|--------|-------------|
| `iterIes()` | Generator yielding `[ieId, ieData]` tuples |
| `ssid` | Extracted SSID string, `""` for hidden, `null` if absent |

#### Convenience

`isBeacon`, `isProbeReq`, `isProbeResp`, `Frame.macStr(addr)`

### `SnifferError`

Thrown when a command fails. Has `.cmd` and `.code` properties.
