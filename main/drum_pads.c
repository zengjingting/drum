#include "drum_pads.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "board_pins.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "metronome_app.h"

#define DRUM_PAD_COUNT 7
#define DRUM_PAD_POLL_MS 1
#define DRUM_SAMPLE_DISABLED (-1)

typedef struct {
    bool raw_pressed;
    bool stable_pressed;
    uint8_t stable_samples;
} pad_state_t;

static const char *TAG = "drum_pads";
static const gpio_num_t s_pad_pins[DRUM_PAD_COUNT] = {
    PIN_DRUM_PAD_S1,
    PIN_DRUM_PAD_S2,
    PIN_DRUM_PAD_S3,
    PIN_DRUM_PAD_S4,
    PIN_DRUM_PAD_S5,
    PIN_DRUM_PAD_S6,
    PIN_DRUM_PAD_S7,
};

/* Physical pad to six-slot sound-bank mapping. S3 is disabled until repaired. */
static const int8_t s_pad_samples[DRUM_PAD_COUNT] = {
    0, 1, DRUM_SAMPLE_DISABLED, 3, 4, 5, 2,
};

static bool pad_is_pressed(size_t index)
{
    return gpio_get_level(s_pad_pins[index]) == 0;
}

static void drum_pad_task(void *arg)
{
    (void)arg;
    pad_state_t states[DRUM_PAD_COUNT] = {0};

    for (size_t index = 0; index < DRUM_PAD_COUNT; ++index) {
        states[index].raw_pressed = pad_is_pressed(index);
        states[index].stable_pressed = states[index].raw_pressed;
    }

    for (;;) {
        for (size_t index = 0; index < DRUM_PAD_COUNT; ++index) {
            pad_state_t *state = &states[index];
            const bool pressed = pad_is_pressed(index);

            if (pressed != state->raw_pressed) {
                state->raw_pressed = pressed;
                state->stable_samples = 1;
                continue;
            }

            if (state->stable_samples < DRUM_PAD_DEBOUNCE_MS) {
                state->stable_samples++;
            }
            if (state->stable_samples == DRUM_PAD_DEBOUNCE_MS &&
                state->stable_pressed != state->raw_pressed) {
                state->stable_pressed = state->raw_pressed;
                const int8_t sample_index = s_pad_samples[index];
                if (state->stable_pressed && sample_index >= 0 &&
                    !metronome_app_trigger_drum((uint8_t)sample_index)) {
                    ESP_LOGW(TAG, "S%u trigger queue full", (unsigned)index + 1U);
                }
            }
        }

        vTaskDelay(pdMS_TO_TICKS(DRUM_PAD_POLL_MS));
    }
}

esp_err_t drum_pads_start(void)
{
    uint64_t pin_mask = 0;
    for (size_t index = 0; index < DRUM_PAD_COUNT; ++index) {
        pin_mask |= 1ULL << s_pad_pins[index];
    }

    const gpio_config_t config = {
        .pin_bit_mask = pin_mask,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    esp_err_t err = gpio_config(&config);
    if (err != ESP_OK) {
        return err;
    }

    if (xTaskCreate(drum_pad_task, "drum_pads", 3072, NULL, 7, NULL) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG,
             "S1-S7 ready on GPIO 2/47/38/41/1/6/7; S3 disabled, "
             "closed hi-hat on S7; debounce %d ms",
             DRUM_PAD_DEBOUNCE_MS);
    return ESP_OK;
}
