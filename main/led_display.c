#include "led_display.h"

#include "board_pins.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "led_strip.h"
#include "metronome_app.h"

#define LED_COUNT 5

static const char *TAG = "led_display";
static led_strip_handle_t s_strip;

static void render_state(const metronome_state_t *state)
{
    if (!state->running) {
        led_strip_clear(s_strip);
        return;
    }

    for (int i = 0; i < LED_COUNT; ++i) {
        led_strip_set_pixel(s_strip, i, 1, 1, 2);
    }

    if (state->accent) {
        led_strip_set_pixel(s_strip, state->led_position, 48, 10, 2);
    } else {
        led_strip_set_pixel(s_strip, state->led_position, 2, 18, 48);
    }
    led_strip_refresh(s_strip);
}

static void led_task(void *arg)
{
    QueueHandle_t queue = (QueueHandle_t)arg;
    metronome_state_t state;
    while (xQueueReceive(queue, &state, portMAX_DELAY) == pdTRUE) {
        render_state(&state);
    }
}

esp_err_t led_display_start(void)
{
    led_strip_config_t strip_config = {
        .strip_gpio_num = PIN_WS2812_DATA,
        .max_leds = LED_COUNT,
        .led_model = LED_MODEL_WS2812,
        .color_component_format = LED_STRIP_COLOR_COMPONENT_FMT_GRB,
        .flags = {
            .invert_out = false,
        },
    };
    led_strip_rmt_config_t rmt_config = {
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = 10 * 1000 * 1000,
        .mem_block_symbols = 64,
        .flags = {
            .with_dma = false,
        },
    };

    esp_err_t err = led_strip_new_rmt_device(&strip_config, &rmt_config, &s_strip);
    if (err != ESP_OK) {
        return err;
    }
    err = led_strip_clear(s_strip);
    if (err != ESP_OK) {
        return err;
    }

    QueueHandle_t queue = xQueueCreate(1, sizeof(metronome_state_t));
    if (queue == NULL) {
        return ESP_ERR_NO_MEM;
    }
    err = metronome_app_subscribe(queue);
    if (err != ESP_OK) {
        return err;
    }
    if (xTaskCreate(led_task, "led_display", 3072, queue, 5, NULL) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG, "Five-pixel beat display ready on GPIO%d", PIN_WS2812_DATA);
    return ESP_OK;
}
