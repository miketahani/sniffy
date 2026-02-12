/** Web Serial client for the ESP32-C6 WiFi sniffer firmware. */

import { encode, decode } from "./cobs.js";
import { Frame, META_SIZE } from "./frame.js";

// protocol constants (must match firmware protocol.h)
const MSG_CMD_SCAN_START = 0x01;
const MSG_CMD_SCAN_STOP = 0x02;
const MSG_CMD_PROMISC_ON = 0x03;
const MSG_CMD_PROMISC_OFF = 0x04;
const MSG_CMD_PROMISC_QUERY = 0x05;

const MSG_RSP_ACK = 0x81;
const MSG_RSP_ERROR = 0x82;
const MSG_RSP_PROMISC_STATUS = 0x83;

const MSG_EVT_FRAME = 0xc0;

const HDR_SIZE = 4; // <BBH: msg_type(1) + flags(1) + payload_len(2)

const ERROR_NAMES: Record<number, string> = {
  0x01: "unknown command",
  0x02: "invalid channel",
  0x03: "wifi failure",
  0x04: "scan active (stop scan first)",
};

export class SnifferError extends Error {
  readonly cmd: number;
  readonly code: number;

  constructor(cmd: number, code: number) {
    const name = ERROR_NAMES[code] ?? `0x${code.toString(16).padStart(2, "0")}`;
    super(`command 0x${cmd.toString(16).padStart(2, "0")} failed: ${name}`);
    this.cmd = cmd;
    this.code = code;
  }
}

export interface SnifferClientOptions {
  baudRate?: number;
  onFrame?: (frame: Frame) => void;
  onDisconnect?: () => void;
  /** USB vendor/product filter for requestPort(). */
  filters?: SerialPortFilter[];
}

export class SnifferClient {
  static readonly TIMEOUT = 3000; // ms

  frameCount = 0;
  dropped = 0;

  private _port: SerialPort | null = null;
  private _reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
  private _writer: WritableStreamDefaultWriter<Uint8Array> | null = null;
  private _running = false;
  private _buf = new Uint8Array(0);
  private _seqExpect = 0;
  private _firstSeq = true;

  private _onFrame: (frame: Frame) => void;
  private _onDisconnect: () => void;
  private _baudRate: number;
  private _filters: SerialPortFilter[];

  // command response signaling
  private _respResolve: ((data: Uint8Array | null) => void) | null = null;

  constructor(options: SnifferClientOptions = {}) {
    this._onFrame = options.onFrame ?? (() => {});
    this._onDisconnect = options.onDisconnect ?? (() => {});
    this._baudRate = options.baudRate ?? 115200;
    this._filters = options.filters ?? [];
  }

  /** Whether the client is currently connected to a serial port. */
  get connected(): boolean {
    return this._running && this._port !== null;
  }

  /**
   * Request a serial port from the user and open it.
   * Must be called from a user gesture (click, keypress, etc.).
   */
  async connect(existingPort?: SerialPort): Promise<void> {
    if (this._running) throw new Error("already connected");

    const port =
      existingPort ??
      (await navigator.serial.requestPort(
        this._filters.length > 0 ? { filters: this._filters } : undefined
      ));

    await port.open({ baudRate: this._baudRate });
    this._port = port;
    this._running = true;
    this._buf = new Uint8Array(0);
    this._firstSeq = true;
    this._seqExpect = 0;
    this.frameCount = 0;
    this.dropped = 0;

    this._readLoop();
  }

  async scan(channel: number = 0): Promise<void> {
    await this._sendCmd(MSG_CMD_SCAN_START, new Uint8Array([channel]));
  }

  async stop(): Promise<void> {
    await this._sendCmd(MSG_CMD_SCAN_STOP);
  }

  async promiscOn(): Promise<void> {
    await this._sendCmd(MSG_CMD_PROMISC_ON);
  }

  async promiscOff(): Promise<void> {
    await this._sendCmd(MSG_CMD_PROMISC_OFF);
  }

  async promiscStatus(): Promise<boolean> {
    const resp = await this._sendCmd(MSG_CMD_PROMISC_QUERY);
    return resp !== null && resp.length > 0 && resp[0] !== 0;
  }

  async disconnect(): Promise<void> {
    this._running = false;

    // reject any pending command
    if (this._respResolve) {
      this._respResolve(null);
      this._respResolve = null;
    }

    try {
      if (this._reader) {
        await this._reader.cancel();
        this._reader.releaseLock();
        this._reader = null;
      }
    } catch {
      // ignore
    }

    try {
      if (this._writer) {
        this._writer.releaseLock();
        this._writer = null;
      }
    } catch {
      // ignore
    }

    try {
      if (this._port) {
        await this._port.close();
        this._port = null;
      }
    } catch {
      // ignore
    }
  }

  private async _sendCmd(
    msgType: number,
    payload: Uint8Array = new Uint8Array(0)
  ): Promise<Uint8Array | null> {
    if (!this._port?.writable) throw new Error("not connected");

    // build header: <BBH (little-endian)
    const hdr = new Uint8Array(HDR_SIZE);
    const hdrView = new DataView(hdr.buffer);
    hdrView.setUint8(0, msgType);
    hdrView.setUint8(1, 0); // flags
    hdrView.setUint16(2, payload.length, true);

    const raw = new Uint8Array(HDR_SIZE + payload.length);
    raw.set(hdr);
    raw.set(payload, HDR_SIZE);

    const encoded = encode(raw);
    const packet = new Uint8Array(encoded.length + 2);
    packet[0] = 0x00;
    packet.set(encoded, 1);
    packet[packet.length - 1] = 0x00;

    // set up response promise before writing
    const respPromise = new Promise<Uint8Array | null>((resolve) => {
      this._respResolve = resolve;
    });

    // write
    if (!this._writer && this._port.writable) {
      this._writer = this._port.writable.getWriter();
    }
    await this._writer!.write(packet);

    // wait for response or timeout
    let timer: ReturnType<typeof setTimeout>;
    const resp = await Promise.race([
      respPromise,
      new Promise<never>((_, reject) => {
        timer = setTimeout(
          () => reject(new SnifferError(msgType, 0xff)),
          SnifferClient.TIMEOUT
        );
      }),
    ]).finally(() => {
      clearTimeout(timer);
      this._respResolve = null;
    });

    if (resp === null) return null;

    // parse response header
    if (resp.length < HDR_SIZE) return null;
    const rv = new DataView(resp.buffer, resp.byteOffset, resp.byteLength);
    const rtype = rv.getUint8(0);
    const rplen = rv.getUint16(2, true);
    const rpayload = resp.slice(HDR_SIZE, HDR_SIZE + rplen);

    if (rtype === MSG_RSP_ERROR && rpayload.length >= 2) {
      throw new SnifferError(rpayload[0], rpayload[1]);
    }

    return rpayload;
  }

  private async _readLoop(): Promise<void> {
    const port = this._port;
    if (!port?.readable) return;

    while (this._running && port.readable) {
      this._reader = port.readable.getReader();
      try {
        while (this._running) {
          const { value, done } = await this._reader.read();
          if (done) break;
          if (value) {
            this._appendBuf(value);
            this._process();
          }
        }
      } catch {
        // serial error — will retry if port still readable
      } finally {
        try {
          this._reader.releaseLock();
        } catch {
          // ignore
        }
        this._reader = null;
      }
    }

    if (this._running) {
      // disconnected unexpectedly
      this._running = false;
      this._onDisconnect();
    }
  }

  private _appendBuf(chunk: Uint8Array): void {
    const combined = new Uint8Array(this._buf.length + chunk.length);
    combined.set(this._buf);
    combined.set(chunk, this._buf.length);
    this._buf = combined;
  }

  private _process(): void {
    while (true) {
      const idx = this._buf.indexOf(0x00);
      if (idx === -1) break;

      if (idx === 0) {
        this._buf = this._buf.slice(1);
        continue;
      }

      const encodedSlice = this._buf.slice(0, idx);
      this._buf = this._buf.slice(idx + 1);

      let decoded: Uint8Array;
      try {
        decoded = decode(encodedSlice);
      } catch {
        continue;
      }

      if (decoded.length < HDR_SIZE) continue;

      const msgType = decoded[0];

      if (msgType === MSG_EVT_FRAME) {
        this._handleFrame(decoded);
      } else if (
        msgType === MSG_RSP_ACK ||
        msgType === MSG_RSP_ERROR ||
        msgType === MSG_RSP_PROMISC_STATUS
      ) {
        if (this._respResolve) {
          this._respResolve(decoded);
          this._respResolve = null;
        }
      }
    }
  }

  private _handleFrame(data: Uint8Array): void {
    if (data.length < HDR_SIZE) return;
    const v = new DataView(data.buffer, data.byteOffset, data.byteLength);
    const payloadLen = v.getUint16(2, true);
    const payload = data.slice(HDR_SIZE, HDR_SIZE + payloadLen);

    if (payload.length < META_SIZE) return;

    const meta = payload.slice(0, META_SIZE);
    const frameLen = new DataView(
      meta.buffer,
      meta.byteOffset,
      meta.byteLength
    ).getUint16(4, true);
    const frameData = payload.slice(META_SIZE, META_SIZE + frameLen);

    if (frameData.length < frameLen) return;

    const frame = new Frame(meta, frameData);

    // drop detection
    if (this._firstSeq) {
      this._seqExpect = frame.seqNum;
      this._firstSeq = false;
    } else if (frame.seqNum !== this._seqExpect) {
      const gap = (frame.seqNum - this._seqExpect) & 0xffff;
      if (gap < 0x8000) this.dropped += gap;
    }
    this._seqExpect = (frame.seqNum + 1) & 0xffff;

    this.frameCount++;
    this._onFrame(frame);
  }
}
