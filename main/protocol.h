#pragma once

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_wifi.h"

/* -------- message types -------- */

/* commands (client -> device) */
#define MSG_CMD_SCAN_START      0x01
#define MSG_CMD_SCAN_STOP       0x02
#define MSG_CMD_PROMISC_ON      0x03
#define MSG_CMD_PROMISC_OFF     0x04
#define MSG_CMD_PROMISC_QUERY   0x05

/* responses (device -> client) */
#define MSG_RSP_ACK             0x81
#define MSG_RSP_ERROR           0x82
#define MSG_RSP_PROMISC_STATUS  0x83

/* async events (device -> client) */
#define MSG_EVT_FRAME           0xC0

/* -------- flags -------- */
#define FLAG_ERR                (1 << 0)
#define FLAG_ACK                (1 << 1)

/* -------- error codes -------- */
#define ERR_UNKNOWN_CMD         0x01
#define ERR_INVALID_CHANNEL     0x02
#define ERR_WIFI_FAIL           0x03
#define ERR_SCAN_ACTIVE         0x04

/* -------- frame size limits -------- */
#define MAX_FRAME_LEN           2300
#define BUF_POOL_SIZE           8
#define BUF_SLOT_SIZE           (4 + 16 + MAX_FRAME_LEN)  /* hdr + meta + payload */

/* -------- protocol header (4 bytes) -------- */
typedef struct __attribute__((packed)) {
    uint8_t  msg_type;
    uint8_t  flags;
    uint16_t payload_len;
} proto_msg_hdr_t;

_Static_assert(sizeof(proto_msg_hdr_t) == 4, "proto_msg_hdr_t must be 4 bytes");

/* -------- frame metadata (16 bytes) -------- */
typedef struct __attribute__((packed)) {
    uint32_t timestamp;
    uint16_t frame_len;
    uint8_t  channel;
    int8_t   rssi;
    int8_t   noise_floor;
    uint8_t  pkt_type;
    uint8_t  rx_state;
    uint8_t  rate;
    uint16_t seq_num;
    uint16_t _reserved;
} frame_meta_t;

_Static_assert(sizeof(frame_meta_t) == 16, "frame_meta_t must be 16 bytes");

/* -------- shared state (owned by sniffer.c, used by protocol.c) -------- */
extern volatile bool     scanning;
extern volatile bool     promisc_on;
extern volatile int      scan_channel;    /* -1 = all, >0 = specific */
extern TaskHandle_t      scan_task_handle;

/* -------- protocol API -------- */

/* Initialize USB serial driver, buffer pool, and start TX/RX tasks. */
void proto_init(void);

/*
 * Called from the promiscuous callback to enqueue a captured frame.
 * Non-blocking: drops the frame if no buffer is available or TX queue is full.
 */
void proto_send_frame(const wifi_promiscuous_pkt_t *pkt,
                      wifi_promiscuous_pkt_type_t type);

/* Send an ACK response for the given command type. */
void proto_send_ack(uint8_t cmd_type);

/* Send an error response. */
void proto_send_error(uint8_t cmd_type, uint8_t error_code);

/* Send promiscuous mode status. */
void proto_send_promisc_status(bool enabled);

/* -------- COBS -------- */
size_t cobs_encode(const uint8_t *src, size_t len, uint8_t *dst);
int    cobs_decode(const uint8_t *src, size_t len, uint8_t *dst);
