"""Pure-Python COBS (Consistent Overhead Byte Stuffing) encoder/decoder."""


def encode(data: bytes) -> bytes:
    out = bytearray()
    code_idx = len(out)
    out.append(0)  # placeholder for first code byte
    code = 1

    for b in data:
        if b == 0x00:
            out[code_idx] = code
            code_idx = len(out)
            out.append(0)  # placeholder for next code byte
            code = 1
        else:
            out.append(b)
            code += 1
            if code == 0xFF:
                out[code_idx] = code
                code_idx = len(out)
                out.append(0)
                code = 1

    out[code_idx] = code
    return bytes(out)


def decode(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    length = len(data)

    while i < length:
        code = data[i]
        i += 1
        if code == 0:
            raise ValueError("zero byte in COBS-encoded data")

        for _ in range(1, code):
            if i >= length:
                raise ValueError("truncated COBS data")
            out.append(data[i])
            i += 1

        if code < 0xFF and i < length:
            out.append(0x00)

    return bytes(out)
