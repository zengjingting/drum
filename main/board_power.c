#include "board_power.h"

#include "board_pins.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "board_power";

static esp_err_t latch_low_then_output(gpio_num_t pin)
{
    esp_err_t err = gpio_set_level(pin, 0);
    if (err != ESP_OK) {
        return err;
    }
    return gpio_set_direction(pin, GPIO_MODE_OUTPUT);
}

esp_err_t board_shared_power_cold_start(void)
{
    const gpio_num_t safe_output_pins[] = {
        PIN_MIC_BCLK,
        PIN_MIC_WS,
        PIN_WS2812_DATA,
        PIN_SPEAKER_WS,
        PIN_SPEAKER_BCLK,
        PIN_SPEAKER_DATA_OUT,
    };

    esp_err_t err = latch_low_then_output(PIN_SHARED_POWER);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Failed to latch shared power low: %s", esp_err_to_name(err));
        return err;
    }

    for (size_t i = 0; i < sizeof(safe_output_pins) / sizeof(safe_output_pins[0]); ++i) {
        err = latch_low_then_output(safe_output_pins[i]);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "Failed to make GPIO %d safe: %s",
                     safe_output_pins[i], esp_err_to_name(err));
            return err;
        }
    }

    err = gpio_set_direction(PIN_MIC_DATA_IN, GPIO_MODE_DISABLE);
    if (err != ESP_OK) {
        return err;
    }
    err = gpio_set_pull_mode(PIN_MIC_DATA_IN, GPIO_FLOATING);
    if (err != ESP_OK) {
        return err;
    }

    err = gpio_set_level(PIN_SHARED_POWER, 1);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Failed to enable GPIO8 shared power: %s", esp_err_to_name(err));
        return err;
    }

    vTaskDelay(pdMS_TO_TICKS(SHARED_POWER_SETTLE_MS));
    ESP_LOGI(TAG, "GPIO8 shared rail enabled; project settle time=%d ms",
             SHARED_POWER_SETTLE_MS);
    return ESP_OK;
}

esp_err_t board_status_led_init(void)
{
    esp_err_t err = latch_low_then_output(PIN_STATUS_LED);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Failed to initialize status LED: %s", esp_err_to_name(err));
    }
    return err;
}

void board_status_led_set(bool on)
{
    gpio_set_level(PIN_STATUS_LED, on ? 1 : 0);
}
