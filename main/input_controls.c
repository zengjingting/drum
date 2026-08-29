#include "input_controls.h"

#include <stdint.h>

#include "board_pins.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "metronome_app.h"

#define INPUT_POLL_MS 1
#define BUTTON_DEBOUNCE_MS 25

static const char *TAG = "input";

static uint8_t read_encoder_ab(void)
{
    return (uint8_t)((gpio_get_level(PIN_ENCODER_A) << 1) |
                     gpio_get_level(PIN_ENCODER_B));
}

static void input_task(void *arg)
{
    (void)arg;
    static const int8_t transition_table[16] = {
         0, -1,  1,  0,
         1,  0,  0, -1,
        -1,  0,  0,  1,
         0,  1, -1,  0,
    };

    uint8_t previous_ab = read_encoder_ab();
    int transition_accumulator = 0;
    bool raw_pressed = gpio_get_level(PIN_ENCODER_BUTTON) == 0;
    bool stable_pressed = raw_pressed;
    uint32_t stable_count = 0;

    while (true) {
        const uint8_t current_ab = read_encoder_ab();
        const int8_t transition = transition_table[(previous_ab << 2) | current_ab];
        previous_ab = current_ab;
        transition_accumulator += transition;

        if (transition_accumulator >= 4) {
            metronome_app_adjust_bpm(ENCODER_DIRECTION * ENCODER_BPM_PER_DETENT);
            transition_accumulator = 0;
        } else if (transition_accumulator <= -4) {
            metronome_app_adjust_bpm(-ENCODER_DIRECTION * ENCODER_BPM_PER_DETENT);
            transition_accumulator = 0;
        }

        const bool current_pressed = gpio_get_level(PIN_ENCODER_BUTTON) == 0;
        if (current_pressed == raw_pressed) {
            if (stable_count < BUTTON_DEBOUNCE_MS / INPUT_POLL_MS) {
                stable_count++;
            }
        } else {
            raw_pressed = current_pressed;
            stable_count = 0;
        }

        if (stable_count == BUTTON_DEBOUNCE_MS / INPUT_POLL_MS &&
            stable_pressed != raw_pressed) {
            stable_pressed = raw_pressed;
            if (stable_pressed) {
                metronome_app_toggle();
            }
        }

        vTaskDelay(pdMS_TO_TICKS(INPUT_POLL_MS));
    }
}

esp_err_t input_controls_start(void)
{
    gpio_config_t config = {
        .pin_bit_mask = (1ULL << PIN_ENCODER_A) |
                        (1ULL << PIN_ENCODER_B) |
                        (1ULL << PIN_ENCODER_BUTTON),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };

    esp_err_t err = gpio_config(&config);
    if (err != ESP_OK) {
        return err;
    }
    if (xTaskCreate(input_task, "encoder_input", 2048, NULL, 6, NULL) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG, "Encoder ready: A=%d B=%d button=%d",
             PIN_ENCODER_A, PIN_ENCODER_B, PIN_ENCODER_BUTTON);
    return ESP_OK;
}
