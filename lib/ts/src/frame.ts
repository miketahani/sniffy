/** 802.11 frame class with lazy parsing of header fields and IEs. */

// metadata struct: <IHBbbBBBHH  (16 bytes)
//   u32 timestamp_us, u16 frame_len, u8 channel, i8 rssi, i8 noise_floor,
//   u8 pkt_type, u8 rx_state, u8 rate, u16 seq_num, u16 reserved
export const META_SIZE = 16;

// 802.11 frame types
export const FRAME_TYPE_MGMT = 0;
export const FRAME_TYPE_CTRL = 1;
export const FRAME_TYPE_DATA = 2;

// management subtypes
export const SUBTYPE_ASSOC_REQ = 0;
export const SUBTYPE_ASSOC_RESP = 1;
export const SUBTYPE_PROBE_REQ = 4;
export const SUBTYPE_PROBE_RESP = 5;
export const SUBTYPE_BEACON = 8;
export const SUBTYPE_DEAUTH = 12;

const FrameTypeName = {
  [FRAME_TYPE_MGMT]: "mgmt",
  [FRAME_TYPE_CTRL]: "ctrl",
  [FRAME_TYPE_DATA]: "data",
};

const SubTypeName = {
  [SUBTYPE_ASSOC_REQ]: "assoc_req",
  [SUBTYPE_ASSOC_RESP]: "assoc_resp",
  [SUBTYPE_PROBE_REQ]: "probe_req",
  [SUBTYPE_PROBE_RESP]: "probe_resp",
  [SUBTYPE_BEACON]: "beacon",
  [SUBTYPE_DEAUTH]: "deauth",
};

export class Frame {
  // metadata (eagerly unpacked)
  readonly timestampUs: number;
  readonly frameLen: number;
  readonly channel: number;
  readonly rssi: number;
  readonly noiseFloor: number;
  readonly pktType: number;
  readonly rxState: number;
  readonly rate: number;
  readonly seqNum: number;
  readonly raw: Uint8Array;

  // lazy cache
  private _cache = new Map<string, unknown>();

  constructor(meta: Uint8Array, raw: Uint8Array) {
    const v = new DataView(meta.buffer, meta.byteOffset, meta.byteLength);
    this.timestampUs = v.getUint32(0, true);
    this.frameLen = v.getUint16(4, true);
    this.channel = v.getUint8(6);
    this.rssi = v.getInt8(7);
    this.noiseFloor = v.getInt8(8);
    this.pktType = v.getUint8(9);
    this.rxState = v.getUint8(10);
    this.rate = v.getUint8(11);
    this.seqNum = v.getUint16(12, true);
    // bytes 14-15: reserved
    this.raw = raw;
  }

  // helpers for lazy properties

  private _lazy<T>(key: string, fn: () => T): T {
    if (this._cache.has(key)) return this._cache.get(key) as T;
    const val = fn();
    this._cache.set(key, val);
    return val;
  }

  // 802.11 MAC header (lazy)

  get frameControl(): number {
    return this._lazy("fc", () => {
      if (this.raw.length < 2) return 0;
      return new DataView(this.raw.buffer, this.raw.byteOffset).getUint16(
        0,
        true
      );
    });
  }

  get frameType(): number {
    return this._lazy("ft", () => (this.frameControl >> 2) & 0x03);
  }

  get frameSubtype(): number {
    return this._lazy("fst", () => (this.frameControl >> 4) & 0x0f);
  }

  get toDs(): boolean {
    return this._lazy("tds", () => !!(this.frameControl & (1 << 8)));
  }

  get fromDs(): boolean {
    return this._lazy("fds", () => !!(this.frameControl & (1 << 9)));
  }

  get duration(): number {
    return this._lazy("dur", () => {
      if (this.raw.length < 4) return 0;
      return new DataView(this.raw.buffer, this.raw.byteOffset).getUint16(
        2,
        true
      );
    });
  }

  get addr1(): Uint8Array | null {
    return this._lazy("a1", () =>
      this.raw.length < 10 ? null : this.raw.slice(4, 10)
    );
  }

  get addr2(): Uint8Array | null {
    return this._lazy("a2", () =>
      this.raw.length < 16 ? null : this.raw.slice(10, 16)
    );
  }

  get addr3(): Uint8Array | null {
    return this._lazy("a3", () =>
      this.raw.length < 22 ? null : this.raw.slice(16, 22)
    );
  }

  get sequenceControl(): number | null {
    return this._lazy("sc", () => {
      if (this.raw.length < 24) return null;
      return new DataView(this.raw.buffer, this.raw.byteOffset).getUint16(
        22,
        true
      );
    });
  }

  get sequenceNumber(): number | null {
    return this._lazy("sn", () => {
      const sc = this.sequenceControl;
      return sc === null ? null : sc >> 4;
    });
  }

  get fragmentNumber(): number | null {
    return this._lazy("fn", () => {
      const sc = this.sequenceControl;
      return sc === null ? null : sc & 0x0f;
    });
  }

  //  derived addresses

  get bssid(): Uint8Array | null {
    return this._lazy("bssid", () => {
      if (this.frameType === FRAME_TYPE_MGMT) return this.addr3;
      if (!this.toDs && !this.fromDs) return this.addr3;
      if (!this.toDs && this.fromDs) return this.addr2;
      if (this.toDs && !this.fromDs) return this.addr1;
      return null;
    });
  }

  get src(): Uint8Array | null {
    return this._lazy("src", () => {
      if (this.frameType === FRAME_TYPE_MGMT) return this.addr2;
      if (!this.toDs && !this.fromDs) return this.addr2;
      if (!this.toDs && this.fromDs) return this.addr3;
      if (this.toDs && !this.fromDs) return this.addr2;
      // WDS: addr4 at offset 24
      if (this.raw.length >= 30) return this.raw.slice(24, 30);
      return null;
    });
  }

  get dst(): Uint8Array | null {
    return this._lazy("dst", () => {
      if (this.frameType === FRAME_TYPE_MGMT) return this.addr1;
      if (!this.toDs && !this.fromDs) return this.addr1;
      if (!this.toDs && this.fromDs) return this.addr1;
      if (this.toDs && !this.fromDs) return this.addr3;
      return this.addr3;
    });
  }

  //  information elements

  private get _ieOffset(): number {
    if (this.frameType !== FRAME_TYPE_MGMT) return -1;
    const st = this.frameSubtype;
    if (st === SUBTYPE_BEACON || st === SUBTYPE_PROBE_RESP) return 24 + 12;
    if (st === SUBTYPE_PROBE_REQ) return 24;
    if (st === SUBTYPE_ASSOC_REQ) return 24 + 4;
    return 24;
  }

  *iterIes(): Generator<[number, Uint8Array]> {
    const offset = this._ieOffset;
    if (offset < 0) return;
    let pos = offset;
    const data = this.raw;
    while (pos + 2 <= data.length) {
      const ieId = data[pos];
      const ieLen = data[pos + 1];
      if (pos + 2 + ieLen > data.length) break;
      yield [ieId, data.slice(pos + 2, pos + 2 + ieLen)];
      pos += 2 + ieLen;
    }
  }

  get ssid(): string | null {
    return this._lazy("ssid", () => {
      for (const [ieId, ieData] of this.iterIes()) {
        if (ieId === 0) {
          if (ieData.length === 0) return "";
          return new TextDecoder("utf-8", { fatal: false }).decode(ieData);
        }
      }
      return null;
    });
  }

  //  convenience

  get isBeacon(): boolean {
    return (
      this.frameType === FRAME_TYPE_MGMT && this.frameSubtype === SUBTYPE_BEACON
    );
  }

  get isProbeReq(): boolean {
    return (
      this.frameType === FRAME_TYPE_MGMT &&
      this.frameSubtype === SUBTYPE_PROBE_REQ
    );
  }

  get isProbeResp(): boolean {
    return (
      this.frameType === FRAME_TYPE_MGMT &&
      this.frameSubtype === SUBTYPE_PROBE_RESP
    );
  }

  static frameTypeName(frameType: number): string {
    return FrameTypeName[frameType as keyof typeof FrameTypeName] ?? frameType;
  }

  static subTypeName(subType: number): string {
    return SubTypeName[subType as keyof typeof SubTypeName] ?? subType;
  }

  static macStr(addr: Uint8Array | null): string {
    if (addr === null) return "??:??:??:??:??:??";
    return Array.from(addr)
      .map((b) => b.toString(16).padStart(2, "0"))
      .join(":");
  }

  toString(): string {
    const frameTypeName = Frame.frameTypeName(this.frameType);
    const subtypeName = Frame.subTypeName(this.frameSubtype);
    const parts = [
      `ch=${this.channel}`,
      `rssi=${this.rssi}`,
      `type=${frameTypeName}/${subtypeName}`,
      `src=${Frame.macStr(this.addr2)}`,
      `dst=${Frame.macStr(this.addr1)}`,
      `len=${this.raw.length}`,
    ];
    const ssid = this.ssid;
    if (ssid !== null) parts.push(`ssid='${ssid}'`);
    return `Frame(${parts.join(", ")})`;
  }
}
