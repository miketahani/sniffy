"""802.11 frame class with lazy parsing of header fields and IEs."""

import struct
from functools import cached_property
from typing import Optional, Iterator, Tuple

# metadata struct format (matches firmware frame_meta_t, 16 bytes)
META_FMT = "<IHBbbBBBHH"
META_SIZE = struct.calcsize(META_FMT)  # 16

# 802.11 frame types
FRAME_TYPE_MGMT = 0
FRAME_TYPE_CTRL = 1
FRAME_TYPE_DATA = 2

# management subtypes
SUBTYPE_ASSOC_REQ = 0
SUBTYPE_ASSOC_RESP = 1
SUBTYPE_PROBE_REQ = 4
SUBTYPE_PROBE_RESP = 5
SUBTYPE_BEACON = 8
SUBTYPE_DEAUTH = 12


class Frame:
    """Captured 802.11 frame with metadata.

    Metadata fields (timestamp, rssi, channel, etc.) are unpacked eagerly.
    802.11 header fields (addresses, SSID, etc.) are parsed lazily on access.
    """

    __slots__ = (
        "_ts", "_frame_len", "_channel", "_rssi", "_noise_floor",
        "_pkt_type", "_rx_state", "_rate", "_seq_num", "_raw",
        "__dict__",  # needed for cached_property
    )

    def __init__(self, meta: bytes, raw: bytes):
        (
            self._ts, self._frame_len, self._channel, self._rssi,
            self._noise_floor, self._pkt_type, self._rx_state,
            self._rate, self._seq_num, _,
        ) = struct.unpack_from(META_FMT, meta)
        self._raw = raw

    # ---- metadata (eager) ----

    @property
    def timestamp_us(self) -> int:
        return self._ts

    @property
    def channel(self) -> int:
        return self._channel

    @property
    def rssi(self) -> int:
        return self._rssi

    @property
    def noise_floor(self) -> int:
        return self._noise_floor

    @property
    def pkt_type(self) -> int:
        return self._pkt_type

    @property
    def rx_state(self) -> int:
        return self._rx_state

    @property
    def rate(self) -> int:
        return self._rate

    @property
    def seq_num(self) -> int:
        return self._seq_num

    @property
    def raw(self) -> bytes:
        return self._raw

    # ---- 802.11 MAC header (lazy) ----

    @cached_property
    def frame_control(self) -> int:
        if len(self._raw) < 2:
            return 0
        return struct.unpack_from("<H", self._raw, 0)[0]

    @cached_property
    def frame_type(self) -> int:
        return (self.frame_control >> 2) & 0x03

    @cached_property
    def frame_subtype(self) -> int:
        return (self.frame_control >> 4) & 0x0F

    @cached_property
    def to_ds(self) -> bool:
        return bool(self.frame_control & (1 << 8))

    @cached_property
    def from_ds(self) -> bool:
        return bool(self.frame_control & (1 << 9))

    @cached_property
    def duration(self) -> int:
        if len(self._raw) < 4:
            return 0
        return struct.unpack_from("<H", self._raw, 2)[0]

    @cached_property
    def addr1(self) -> Optional[bytes]:
        """Receiver / destination address."""
        if len(self._raw) < 10:
            return None
        return self._raw[4:10]

    @cached_property
    def addr2(self) -> Optional[bytes]:
        """Transmitter / source address."""
        if len(self._raw) < 16:
            return None
        return self._raw[10:16]

    @cached_property
    def addr3(self) -> Optional[bytes]:
        """BSSID (in most management/data frames)."""
        if len(self._raw) < 22:
            return None
        return self._raw[16:22]

    @cached_property
    def sequence_control(self) -> Optional[int]:
        if len(self._raw) < 24:
            return None
        return struct.unpack_from("<H", self._raw, 22)[0]

    @cached_property
    def sequence_number(self) -> Optional[int]:
        sc = self.sequence_control
        return None if sc is None else (sc >> 4)

    @cached_property
    def fragment_number(self) -> Optional[int]:
        sc = self.sequence_control
        return None if sc is None else (sc & 0x0F)

    # ---- derived addresses ----

    @cached_property
    def bssid(self) -> Optional[bytes]:
        if self.frame_type == FRAME_TYPE_MGMT:
            return self.addr3
        if not self.to_ds and not self.from_ds:
            return self.addr3
        if not self.to_ds and self.from_ds:
            return self.addr2
        if self.to_ds and not self.from_ds:
            return self.addr1
        return None

    @cached_property
    def src(self) -> Optional[bytes]:
        if self.frame_type == FRAME_TYPE_MGMT:
            return self.addr2
        if not self.to_ds and not self.from_ds:
            return self.addr2
        if not self.to_ds and self.from_ds:
            return self.addr3
        if self.to_ds and not self.from_ds:
            return self.addr2
        # WDS: addr4 at offset 24
        if len(self._raw) >= 30:
            return self._raw[24:30]
        return None

    @cached_property
    def dst(self) -> Optional[bytes]:
        if self.frame_type == FRAME_TYPE_MGMT:
            return self.addr1
        if not self.to_ds and not self.from_ds:
            return self.addr1
        if not self.to_ds and self.from_ds:
            return self.addr1
        if self.to_ds and not self.from_ds:
            return self.addr3
        return self.addr3

    # ---- information elements ----

    @cached_property
    def _ie_offset(self) -> int:
        if self.frame_type != FRAME_TYPE_MGMT:
            return -1
        st = self.frame_subtype
        if st in (SUBTYPE_BEACON, SUBTYPE_PROBE_RESP):
            return 24 + 12  # MAC hdr + fixed fields (timestamp+interval+capability)
        if st == SUBTYPE_PROBE_REQ:
            return 24
        if st == SUBTYPE_ASSOC_REQ:
            return 24 + 4
        return 24

    def iter_ies(self) -> Iterator[Tuple[int, bytes]]:
        """Yield (ie_id, ie_data) tuples from management frame IEs."""
        offset = self._ie_offset
        if offset < 0:
            return
        pos = offset
        data = self._raw
        while pos + 2 <= len(data):
            ie_id = data[pos]
            ie_len = data[pos + 1]
            if pos + 2 + ie_len > len(data):
                break
            yield ie_id, data[pos + 2 : pos + 2 + ie_len]
            pos += 2 + ie_len

    @cached_property
    def ssid(self) -> Optional[str]:
        """Extract SSID from IE 0 (beacons, probe req/resp)."""
        for ie_id, ie_data in self.iter_ies():
            if ie_id == 0:
                if len(ie_data) == 0:
                    return ""
                return ie_data.decode("utf-8", errors="replace")
        return None

    # ---- convenience ----

    @cached_property
    def is_beacon(self) -> bool:
        return self.frame_type == FRAME_TYPE_MGMT and self.frame_subtype == SUBTYPE_BEACON

    @cached_property
    def is_probe_req(self) -> bool:
        return self.frame_type == FRAME_TYPE_MGMT and self.frame_subtype == SUBTYPE_PROBE_REQ

    @cached_property
    def is_probe_resp(self) -> bool:
        return self.frame_type == FRAME_TYPE_MGMT and self.frame_subtype == SUBTYPE_PROBE_RESP

    @staticmethod
    def mac_str(addr: Optional[bytes]) -> str:
        if addr is None:
            return "??:??:??:??:??:??"
        return ":".join(f"{b:02x}" for b in addr)

    def __repr__(self) -> str:
        parts = [
            f"ch={self._channel}",
            f"rssi={self._rssi}",
            f"type={self.frame_type}/{self.frame_subtype}",
            f"src={self.mac_str(self.addr2)}",
            f"dst={self.mac_str(self.addr1)}",
            f"len={len(self._raw)}",
        ]
        ssid = self.ssid
        if ssid is not None:
            parts.append(f"ssid={ssid!r}")
        return f"Frame({', '.join(parts)})"
