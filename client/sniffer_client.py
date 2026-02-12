"""Python client for the ESP32-C6 WiFi sniffer firmware."""

import struct
import threading
from typing import Optional, Callable

import serial

from . import cobs
from .frame import Frame, META_SIZE

# protocol constants (must match firmware protocol.h)
MSG_CMD_SCAN_START = 0x01
MSG_CMD_SCAN_STOP = 0x02
MSG_CMD_PROMISC_ON = 0x03
MSG_CMD_PROMISC_OFF = 0x04
MSG_CMD_PROMISC_QUERY = 0x05

MSG_RSP_ACK = 0x81
MSG_RSP_ERROR = 0x82
MSG_RSP_PROMISC_STATUS = 0x83

MSG_EVT_FRAME = 0xC0

HDR_FMT = "<BBH"
HDR_SIZE = struct.calcsize(HDR_FMT)  # 4


class SnifferError(Exception):
    """Raised when the sniffer returns an error response."""

    ERROR_NAMES = {
        0x01: "unknown command",
        0x02: "invalid channel",
        0x03: "wifi failure",
        0x04: "scan active (stop scan first)",
    }

    def __init__(self, cmd: int, code: int):
        name = self.ERROR_NAMES.get(code, f"0x{code:02x}")
        super().__init__(f"command 0x{cmd:02x} failed: {name}")
        self.cmd = cmd
        self.code = code


class SnifferClient:
    """Client for the ESP32-C6 sniffer firmware over USB serial.

    Args:
        port: Serial port path (e.g. "/dev/ttyACM0" or "COM3").
        baudrate: Baud rate (default 115200, ignored for USB CDC-ACM).
        on_frame: Callback invoked for each received frame.
                  Signature: ``on_frame(frame: Frame) -> None``
    """

    TIMEOUT = 3.0  # seconds to wait for a command response

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        on_frame: Optional[Callable[["Frame"], None]] = None,
    ):
        self._ser = serial.Serial(port, baudrate, timeout=0.05)
        self._on_frame = on_frame or (lambda _: None)
        self.frame_count = 0
        self.dropped = 0

        self._buf = bytearray()
        self._seq_expect = 0
        self._first_seq = True

        self._resp_event = threading.Event()
        self._resp_data: Optional[bytes] = None
        self._lock = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    # ---- public API ----

    def scan(self, channel: Optional[int] = None) -> None:
        """Start scanning. If channel is None, cycle all channels."""
        ch = 0 if channel is None else channel
        self._send_cmd(MSG_CMD_SCAN_START, struct.pack("<B", ch))

    def stop(self) -> None:
        """Stop scanning."""
        self._send_cmd(MSG_CMD_SCAN_STOP)

    def promisc_on(self) -> None:
        """Enable promiscuous mode."""
        self._send_cmd(MSG_CMD_PROMISC_ON)

    def promisc_off(self) -> None:
        """Disable promiscuous mode."""
        self._send_cmd(MSG_CMD_PROMISC_OFF)

    def promisc_status(self) -> bool:
        """Query promiscuous mode status. Returns True if enabled."""
        resp = self._send_cmd(MSG_CMD_PROMISC_QUERY)
        return resp[0] != 0 if resp else False

    def close(self) -> None:
        """Close the serial connection and stop the reader thread."""
        self._running = False
        self._thread.join(timeout=2.0)
        self._ser.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ---- internal ----

    def _send_cmd(self, msg_type: int, payload: bytes = b"") -> Optional[bytes]:
        """Send a command and wait for the response."""
        raw = struct.pack(HDR_FMT, msg_type, 0, len(payload)) + payload
        encoded = cobs.encode(raw)
        with self._lock:
            self._resp_event.clear()
            self._resp_data = None
            self._ser.write(b"\x00" + encoded + b"\x00")
            self._ser.flush()

        if not self._resp_event.wait(timeout=self.TIMEOUT):
            raise SnifferError(msg_type, 0xFF)

        resp = self._resp_data
        if resp is None:
            return None

        rtype, rflags, rplen = struct.unpack_from(HDR_FMT, resp)
        rpayload = resp[HDR_SIZE : HDR_SIZE + rplen]

        if rtype == MSG_RSP_ERROR and len(rpayload) >= 2:
            raise SnifferError(rpayload[0], rpayload[1])

        if rtype == MSG_RSP_PROMISC_STATUS:
            return rpayload

        return rpayload

    def _reader(self) -> None:
        """Background thread: read serial, COBS-decode, dispatch."""
        while self._running:
            try:
                chunk = self._ser.read(4096)
            except serial.SerialException:
                break
            if not chunk:
                continue
            self._buf.extend(chunk)
            self._process()

    def _process(self) -> None:
        """Extract COBS-framed messages from the accumulation buffer."""
        while True:
            try:
                idx = self._buf.index(0x00)
            except ValueError:
                break

            if idx == 0:
                del self._buf[0]
                continue

            encoded = bytes(self._buf[:idx])
            del self._buf[: idx + 1]

            try:
                decoded = cobs.decode(encoded)
            except ValueError:
                continue

            if len(decoded) < HDR_SIZE:
                continue

            msg_type = decoded[0]

            if msg_type == MSG_EVT_FRAME:
                self._handle_frame(decoded)
            elif msg_type in (MSG_RSP_ACK, MSG_RSP_ERROR, MSG_RSP_PROMISC_STATUS):
                self._resp_data = decoded
                self._resp_event.set()

    def _handle_frame(self, data: bytes) -> None:
        """Parse a frame event and deliver it to the on_frame callback."""
        _, _, payload_len = struct.unpack_from(HDR_FMT, data)
        payload = data[HDR_SIZE : HDR_SIZE + payload_len]

        if len(payload) < META_SIZE:
            return

        meta = payload[:META_SIZE]
        frame_len = struct.unpack_from("<H", meta, 4)[0]
        frame_data = payload[META_SIZE : META_SIZE + frame_len]

        if len(frame_data) < frame_len:
            return

        frame = Frame(meta, frame_data)

        # drop detection
        if self._first_seq:
            self._seq_expect = frame.seq_num
            self._first_seq = False
        elif frame.seq_num != self._seq_expect:
            gap = (frame.seq_num - self._seq_expect) & 0xFFFF
            if gap < 0x8000:
                self.dropped += gap
        self._seq_expect = (frame.seq_num + 1) & 0xFFFF

        self.frame_count += 1
        self._on_frame(frame)
