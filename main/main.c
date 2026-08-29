#include "board_power.h"
#include "drum_pads.h"
#include "esp_err.h"
#include "esp_log.h"
#include "input_controls.h"
#include "led_display.h"
#include "metronome_app.h"
#include "usb_serial_control.h"

static const char *TAG = "main";

void app_main(void)
{
    esp_err_t err = board_status_led_init();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Status LED initialization failed: %s", esp_err_to_name(err));
        return;
    }

    err = board_shared_power_cold_start();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Shared peripheral cold start failed: %s", esp_err_to_name(err));
        return;
    }

    err = metronome_app_start();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Metronome/I2S initialization failed: %s", esp_err_to_name(err));
        return;
    }
    err = led_display_start();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "WS2812 initialization failed: %s", esp_err_to_name(err));
        return;
    }
    err = input_controls_start();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Encoder initialization failed: %s", esp_err_to_name(err));
        return;
    }
    err = drum_pads_start();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Drum pad initialization failed: %s", esp_err_to_name(err));
        return;
    }

    board_status_led_set(true);
    ESP_LOGI(TAG, "Hardware metronome ready; press encoder to start/stop");

    err = usb_serial_control_start();
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "USB control unavailable (%s); hardware metronome remains active",
                 esp_err_to_name(err));
    }
}
