#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "nvs_flash.h"
#include <string.h>
#include "protocol.h"

/* -------- shared state (declared in protocol.h) -------- */
volatile bool     scanning        = false;
volatile bool     promisc_on      = false;
volatile int      scan_channel    = -1;   /* -1 = all channels */
TaskHandle_t      scan_task_handle = NULL;

/* -------- channel table -------- */
static const uint8_t channels[] = {
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13,
    36, 40, 44, 48,
    149, 153, 157, 161, 165
};
static const int num_channels = sizeof(channels) / sizeof(channels[0]);

/* -------- packet handler -------- */
static void wifi_sniffer_packet_handler(void *buf,
                                        wifi_promiscuous_pkt_type_t type)
{
    const wifi_promiscuous_pkt_t *pkt = (wifi_promiscuous_pkt_t *)buf;
    proto_send_frame(pkt, type);
}

/* -------- scan task -------- */
static void scan_task(void *arg)
{
    (void)arg;
    int ch_idx = 0;

    while (1) {
        /* block until notified to start */
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);

        ch_idx = 0;

        if (scan_channel > 0) {
            /* single-channel mode */
            esp_wifi_set_channel((uint8_t)scan_channel, WIFI_SECOND_CHAN_NONE);

            while (scanning) {
                if (ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(2500))) {
                    /* re-notified: either restart or stop */
                    if (!scanning) break;
                    /* if still scanning, re-apply channel (may have changed) */
                    if (scan_channel > 0) {
                        esp_wifi_set_channel((uint8_t)scan_channel,
                                             WIFI_SECOND_CHAN_NONE);
                    } else {
                        break; /* switched to all-channel mode, restart outer */
                    }
                }
            }
        } else {
            /* all-channel mode */
            while (scanning) {
                uint8_t ch = channels[ch_idx];
                esp_wifi_set_channel(ch, WIFI_SECOND_CHAN_NONE);
                ch_idx = (ch_idx + 1) % num_channels;

                if (ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(2500))) {
                    if (!scanning) break;
                    /* re-notified while scanning: restart loop */
                    break;
                }
            }
        }
    }
}

/* -------- main -------- */
void app_main(void)
{
    ESP_ERROR_CHECK(nvs_flash_init());
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_NULL));
    ESP_ERROR_CHECK(esp_wifi_start());

    /* register promiscuous callback but don't enable yet */
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous_rx_cb(wifi_sniffer_packet_handler));

    /* initialize binary protocol (USB serial, buffer pool, TX/RX tasks) */
    proto_init();

    /* create scan task */
    xTaskCreate(scan_task, "scan_task", 4096, NULL, 5, &scan_task_handle);
}
