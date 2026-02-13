#include "protocol.h"
#include "driver/usb_serial_jtag.h"
#include "freertos/queue.h"
#include <string.h>

/* -------- buffer pool -------- */

static uint8_t             buf_pool[BUF_POOL_SIZE][BUF_SLOT_SIZE];
static QueueHandle_t       pool_queue;   /* free-list: holds uint8_t* pointers */

/* -------- TX queue -------- */

typedef struct {
    uint8_t *buf;   /* pointer into buf_pool */
    size_t   len;   /* total message length (hdr + payload) */
} tx_item_t;

static QueueHandle_t       tx_queue;

/* -------- frame sequence counter -------- */
static volatile uint16_t   frame_seq = 0;

/* -------- COBS encode scratch buffer (stack of tx_task) -------- */
/* worst-case COBS output: input_len + input_len/254 + 1           */
#define COBS_MAX_OUT  (BUF_SLOT_SIZE + BUF_SLOT_SIZE / 254 + 2)

/* -------- valid channels -------- */

static const uint8_t valid_channels[] = {
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13,
    36, 40, 44, 48,
    149, 153, 157, 161, 165
};
static const int num_valid_channels =
    sizeof(valid_channels) / sizeof(valid_channels[0]);

static bool is_valid_channel(int ch)
{
    for (int i = 0; i < num_valid_channels; i++) {
        if (valid_channels[i] == (uint8_t)ch) return true;
    }
    return false;
}

/* -------- helpers: build & send small responses -------- */

static void send_raw(const uint8_t *data, size_t len)
{
    /* COBS encode into a stack buffer and write with delimiters */
    uint8_t enc[64 + 64 / 254 + 2]; /* small messages only */
    size_t enc_len = cobs_encode(data, len, enc);
    uint8_t delim = 0x00;
    usb_serial_jtag_write_bytes(&delim, 1, pdMS_TO_TICKS(50));
    usb_serial_jtag_write_bytes(enc, enc_len, pdMS_TO_TICKS(50));
    usb_serial_jtag_write_bytes(&delim, 1, pdMS_TO_TICKS(50));
}

void proto_send_ack(uint8_t cmd_type)
{
    uint8_t msg[4 + 1]; /* header + 1-byte payload */
    proto_msg_hdr_t *hdr = (proto_msg_hdr_t *)msg;
    hdr->msg_type    = MSG_RSP_ACK;
    hdr->flags       = FLAG_ACK;
    hdr->payload_len = 1;
    msg[4] = cmd_type;
    send_raw(msg, sizeof(msg));
}

void proto_send_error(uint8_t cmd_type, uint8_t error_code)
{
    uint8_t msg[4 + 2];
    proto_msg_hdr_t *hdr = (proto_msg_hdr_t *)msg;
    hdr->msg_type    = MSG_RSP_ERROR;
    hdr->flags       = FLAG_ERR;
    hdr->payload_len = 2;
    msg[4] = cmd_type;
    msg[5] = error_code;
    send_raw(msg, sizeof(msg));
}

void proto_send_promisc_status(bool enabled)
{
    uint8_t msg[4 + 1];
    proto_msg_hdr_t *hdr = (proto_msg_hdr_t *)msg;
    hdr->msg_type    = MSG_RSP_PROMISC_STATUS;
    hdr->flags       = FLAG_ACK;
    hdr->payload_len = 1;
    msg[4] = enabled ? 1 : 0;
    send_raw(msg, sizeof(msg));
}

/* -------- frame enqueue (called from promiscuous callback) -------- */

void proto_send_frame(const wifi_promiscuous_pkt_t *pkt,
                      wifi_promiscuous_pkt_type_t type)
{
    if (!scanning) return;

    uint16_t sig_len = pkt->rx_ctrl.sig_len;
    if (sig_len > MAX_FRAME_LEN) return; /* oversized, drop */

    /* grab a buffer from the pool (non-blocking) */
    uint8_t *buf = NULL;
    if (xQueueReceive(pool_queue, &buf, 0) != pdTRUE) return; /* pool empty */

    /* build header */
    proto_msg_hdr_t *hdr = (proto_msg_hdr_t *)buf;
    hdr->msg_type    = MSG_EVT_FRAME;
    hdr->flags       = 0;
    hdr->payload_len = sizeof(frame_meta_t) + sig_len;

    /* build metadata */
    frame_meta_t *meta = (frame_meta_t *)(buf + sizeof(proto_msg_hdr_t));
    meta->timestamp   = pkt->rx_ctrl.timestamp;
    meta->frame_len   = sig_len;
    meta->channel     = pkt->rx_ctrl.channel;
    meta->rssi        = pkt->rx_ctrl.rssi;
    meta->noise_floor = pkt->rx_ctrl.noise_floor;
    meta->pkt_type    = (uint8_t)type;
    meta->rx_state    = pkt->rx_ctrl.rx_state;
    meta->rate        = pkt->rx_ctrl.rate;
    meta->seq_num     = frame_seq++;
    meta->_reserved   = 0;

    /* copy raw frame */
    memcpy(buf + sizeof(proto_msg_hdr_t) + sizeof(frame_meta_t),
           pkt->payload, sig_len);

    /* enqueue for TX task */
    tx_item_t item = {
        .buf = buf,
        .len = sizeof(proto_msg_hdr_t) + sizeof(frame_meta_t) + sig_len,
    };
    if (xQueueSend(tx_queue, &item, 0) != pdTRUE) {
        /* TX queue full — return buffer to pool, frame is dropped */
        xQueueSend(pool_queue, &buf, 0);
    }
}

/* -------- TX task -------- */

static void proto_tx_task(void *arg)
{
    (void)arg;
    static uint8_t enc_buf[COBS_MAX_OUT];
    tx_item_t item;
    uint8_t delim = 0x00;

    while (1) {
        if (xQueueReceive(tx_queue, &item, portMAX_DELAY) != pdTRUE)
            continue;

        size_t enc_len = cobs_encode(item.buf, item.len, enc_buf);

        usb_serial_jtag_write_bytes(&delim, 1, pdMS_TO_TICKS(100));
        usb_serial_jtag_write_bytes(enc_buf, enc_len, pdMS_TO_TICKS(500));
        usb_serial_jtag_write_bytes(&delim, 1, pdMS_TO_TICKS(100));

        /* return buffer to pool */
        xQueueSend(pool_queue, &item.buf, 0);
    }
}

/* -------- RX task (command parsing) -------- */

#define RX_BUF_SIZE   64
#define RX_ACCUM_SIZE 128

static void handle_command(const uint8_t *data, size_t len)
{
    if (len < sizeof(proto_msg_hdr_t)) return;

    proto_msg_hdr_t hdr;
    memcpy(&hdr, data, sizeof(hdr));

    const uint8_t *payload = data + sizeof(proto_msg_hdr_t);
    size_t plen = hdr.payload_len;
    if (plen > len - sizeof(proto_msg_hdr_t)) return; /* truncated */

    switch (hdr.msg_type) {

    case MSG_CMD_SCAN_START: {
        if (plen < 2) {
            proto_send_error(hdr.msg_type, ERR_INVALID_CHANNEL);
            return;
        }
        uint8_t ch = payload[0];
        uint8_t filt_byte = payload[1];
        if (ch != 0 && !is_valid_channel(ch)) {
            proto_send_error(hdr.msg_type, ERR_INVALID_CHANNEL);
            return;
        }
        if (filt_byte & ~0x07) {
            proto_send_error(hdr.msg_type, ERR_INVALID_FILTER);
            return;
        }
        scan_channel = (ch == 0) ? -1 : (int)ch;
        scan_filter = filt_byte;
        /* 0x00 = all frame types */
        uint32_t mask = filt_byte ? (uint32_t)filt_byte
                                  : (WIFI_PROMIS_FILTER_MASK_MGMT |
                                     WIFI_PROMIS_FILTER_MASK_CTRL |
                                     WIFI_PROMIS_FILTER_MASK_DATA);
        scanning = true;
        wifi_promiscuous_filter_t filt = { .filter_mask = mask };
        esp_wifi_set_promiscuous_filter(&filt);
        if (!promisc_on) {
            esp_wifi_set_promiscuous(true);
            promisc_on = true;
        }
        if (scan_task_handle) {
            xTaskNotify(scan_task_handle, 1, eSetValueWithOverwrite);
        }
        proto_send_ack(hdr.msg_type);
        break;
    }

    case MSG_CMD_SCAN_STOP:
        scanning = false;
        if (scan_task_handle) {
            xTaskNotify(scan_task_handle, 0, eSetValueWithOverwrite);
        }
        proto_send_ack(hdr.msg_type);
        break;

    case MSG_CMD_PROMISC_ON: {
        uint32_t mask = scan_filter ? (uint32_t)scan_filter
                                    : (WIFI_PROMIS_FILTER_MASK_MGMT |
                                       WIFI_PROMIS_FILTER_MASK_CTRL |
                                       WIFI_PROMIS_FILTER_MASK_DATA);
        wifi_promiscuous_filter_t filt = { .filter_mask = mask };
        esp_wifi_set_promiscuous_filter(&filt);
        esp_wifi_set_promiscuous(true);
        promisc_on = true;
        proto_send_ack(hdr.msg_type);
        break;
    }

    case MSG_CMD_PROMISC_OFF:
        if (scanning) {
            proto_send_error(hdr.msg_type, ERR_SCAN_ACTIVE);
            return;
        }
        esp_wifi_set_promiscuous(false);
        promisc_on = false;
        proto_send_ack(hdr.msg_type);
        break;

    case MSG_CMD_PROMISC_QUERY:
        proto_send_promisc_status(promisc_on);
        break;

    default:
        proto_send_error(hdr.msg_type, ERR_UNKNOWN_CMD);
        break;
    }
}

static void proto_rx_task(void *arg)
{
    (void)arg;
    uint8_t rx_tmp[RX_BUF_SIZE];
    uint8_t accum[RX_ACCUM_SIZE];
    size_t  accum_len = 0;
    uint8_t decoded[RX_ACCUM_SIZE];

    while (1) {
        int n = usb_serial_jtag_read_bytes(rx_tmp, sizeof(rx_tmp),
                                           pdMS_TO_TICKS(100));
        if (n <= 0) continue;

        for (int i = 0; i < n; i++) {
            if (rx_tmp[i] == 0x00) {
                /* delimiter found */
                if (accum_len > 0) {
                    int dec_len = cobs_decode(accum, accum_len, decoded);
                    if (dec_len > 0) {
                        handle_command(decoded, (size_t)dec_len);
                    }
                    accum_len = 0;
                }
            } else {
                if (accum_len < RX_ACCUM_SIZE) {
                    accum[accum_len++] = rx_tmp[i];
                } else {
                    /* overflow: discard and wait for next delimiter */
                    accum_len = 0;
                }
            }
        }
    }
}

/* -------- initialization -------- */

void proto_init(void)
{
    /* install USB serial JTAG driver */
    usb_serial_jtag_driver_config_t usb_cfg = {
        .tx_buffer_size = 4096,
        .rx_buffer_size = 256,
    };
    usb_serial_jtag_driver_install(&usb_cfg);

    /* create buffer pool free-list */
    pool_queue = xQueueCreate(BUF_POOL_SIZE, sizeof(uint8_t *));
    for (int i = 0; i < BUF_POOL_SIZE; i++) {
        uint8_t *ptr = buf_pool[i];
        xQueueSend(pool_queue, &ptr, 0);
    }

    /* create TX queue */
    tx_queue = xQueueCreate(BUF_POOL_SIZE, sizeof(tx_item_t));

    /* start tasks */
    xTaskCreate(proto_tx_task, "proto_tx", 4096, NULL, 6, NULL);
    xTaskCreate(proto_rx_task, "proto_rx", 4096, NULL, 4, NULL);
}
