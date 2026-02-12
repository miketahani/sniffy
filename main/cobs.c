#include "protocol.h"

size_t cobs_encode(const uint8_t *src, size_t len, uint8_t *dst)
{
    uint8_t *code_ptr = dst++;
    uint8_t  code     = 1;
    size_t   out      = 1;

    for (size_t i = 0; i < len; i++) {
        if (src[i] == 0x00) {
            *code_ptr = code;
            code_ptr  = dst++;
            code      = 1;
            out++;
        } else {
            *dst++ = src[i];
            code++;
            out++;
            if (code == 0xFF) {
                *code_ptr = code;
                code_ptr  = dst++;
                code      = 1;
                out++;
            }
        }
    }
    *code_ptr = code;
    return out;
}

int cobs_decode(const uint8_t *src, size_t len, uint8_t *dst)
{
    size_t out = 0;
    size_t i   = 0;

    while (i < len) {
        uint8_t code = src[i++];
        if (code == 0) return -1; /* invalid */

        for (uint8_t j = 1; j < code; j++) {
            if (i >= len) return -1; /* truncated */
            dst[out++] = src[i++];
        }

        if (code < 0xFF && i < len) {
            dst[out++] = 0x00;
        }
    }

    return (int)out;
}
