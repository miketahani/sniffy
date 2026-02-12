/** COBS (Consistent Overhead Byte Stuffing) encoder/decoder. */
export function encode(data) {
    const out = [];
    let codeIdx = 0;
    out.push(0); // placeholder for first code byte
    let code = 1;
    for (const b of data) {
        if (b === 0x00) {
            out[codeIdx] = code;
            codeIdx = out.length;
            out.push(0); // placeholder
            code = 1;
        }
        else {
            out.push(b);
            code++;
            if (code === 0xff) {
                out[codeIdx] = code;
                codeIdx = out.length;
                out.push(0);
                code = 1;
            }
        }
    }
    out[codeIdx] = code;
    return new Uint8Array(out);
}
export function decode(data) {
    const out = [];
    let i = 0;
    const length = data.length;
    while (i < length) {
        const code = data[i];
        i++;
        if (code === 0) {
            throw new Error("zero byte in COBS-encoded data");
        }
        for (let j = 1; j < code; j++) {
            if (i >= length) {
                throw new Error("truncated COBS data");
            }
            out.push(data[i]);
            i++;
        }
        if (code < 0xff && i < length) {
            out.push(0x00);
        }
    }
    return new Uint8Array(out);
}
//# sourceMappingURL=cobs.js.map