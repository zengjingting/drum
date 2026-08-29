#include "usb_serial_control.h"

#include <inttypes.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "board_pins.h"
#include "driver/usb_serial_jtag.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "metronome_app.h"

#define USB_RX_BUFFER_SIZE 1024
#define USB_TX_BUFFER_SIZE 1024
#define COMMAND_BUFFER_SIZE 96
#define STATE_JSON_BUFFER_SIZE 384

static const char *TAG = "usb_control";
static QueueHandle_t s_state_queue;

static void write_all(const char *text)
{
    if (!usb_serial_jtag_is_connected()) {
        return;
    }

    const size_t length = strlen(text);
    size_t written = 0;
    while (written < length) {
        int result = usb_serial_jtag_write_bytes(text + written,
                                                 length - written,
                                                 pdMS_TO_TICKS(20));
        if (result <= 0) {
            ESP_LOGW(TAG, "USB write timed out after %u of %u bytes",
                     (unsigned)written, (unsigned)length);
            return;
        }
        written += (size_t)result;
    }
}

static void send_state(metronome_state_t state)
{
    char response[STATE_JSON_BUFFER_SIZE];
    int length = snprintf(response, sizeof(response),
                          "{\"type\":\"state\",\"bpm\":%u,\"running\":%s,"
                          "\"accent\":%s,\"beat\":%" PRIu64 ","
                          "\"ppqnTick\":%" PRIu64 ",\"uiPosition\":%u,"
                          "\"ledPosition\":%u,\"sequenceStep\":%u,"
                          "\"lastPad\":%u,\"padEvent\":%" PRIu32 ","
                          "\"pattern\":[%u,%u,%u,%u,%u,%u]}\n",
                          state.bpm,
                          state.running ? "true" : "false",
                          state.accent ? "true" : "false",
                          state.beat_index,
                          state.ppqn_tick,
                          state.ui_position,
                          state.led_position,
                          state.sequence_step,
                          state.last_pad,
                          state.pad_event,
                          state.pattern[0], state.pattern[1], state.pattern[2],
                          state.pattern[3], state.pattern[4], state.pattern[5]);
    if (length < 0 || (size_t)length >= sizeof(response)) {
        ESP_LOGE(TAG, "State response buffer is too small");
        return;
    }
    write_all(response);
}

static void send_error(const char *message)
{
    char response[128];
    int length = snprintf(response, sizeof(response),
                          "{\"type\":\"error\",\"message\":\"%s\"}\n",
                          message);
    if (length > 0 && (size_t)length < sizeof(response)) {
        write_all(response);
    }
}

static void handle_command(char *command)
{
    if (strcmp(command, "STATE") == 0) {
        send_state(metronome_app_get_state());
        return;
    }

    if (strcmp(command, "TOGGLE") == 0) {
        metronome_app_toggle();
        return;
    }

    if (strncmp(command, "BPM ", 4) == 0) {
        char *end = NULL;
        long bpm = strtol(command + 4, &end, 10);
        if (end != command + 4 && *end == '\0' &&
            bpm >= METRONOME_MIN_BPM && bpm <= METRONOME_MAX_BPM) {
            metronome_app_set_bpm((uint16_t)bpm);
            return;
        }
        send_error("BPM must be an integer from 40 to 240");
        return;
    }

    unsigned pad = 0;
    unsigned mask = 0;
    char trailing = '\0';
    if (sscanf(command, "MASK %u %u %c", &pad, &mask, &trailing) == 2) {
        if (pad >= 1U && pad <= 6U && mask <= UINT16_MAX &&
            metronome_app_set_pattern_mask((uint8_t)(pad - 1U),
                                           (uint16_t)mask)) {
            return;
        }
        send_error("MASK needs pad 1-6 and value 0-65535");
        return;
    }

    if (sscanf(command, "TRIGGER %u %c", &pad, &trailing) == 1) {
        if (pad >= 1U && pad <= 6U &&
            metronome_app_trigger_drum((uint8_t)(pad - 1U))) {
            return;
        }
        send_error("TRIGGER needs pad 1-6");
        return;
    }

    send_error("Unknown command");
}

static void usb_control_task(void *arg)
{
    (void)arg;
    char command[COMMAND_BUFFER_SIZE];
    size_t command_length = 0;
    uint8_t incoming[64];
    metronome_state_t state;

    for (;;) {
        int received = usb_serial_jtag_read_bytes(incoming, sizeof(incoming),
                                                   pdMS_TO_TICKS(10));
        for (int index = 0; index < received; ++index) {
            char value = (char)incoming[index];
            if (value == '\n' || value == '\r') {
                if (command_length > 0) {
                    command[command_length] = '\0';
                    handle_command(command);
                    command_length = 0;
                }
                continue;
            }

            if (command_length + 1 < sizeof(command)) {
                command[command_length++] = value;
            } else {
                command_length = 0;
                send_error("Command is too long");
            }
        }

        while (xQueueReceive(s_state_queue, &state, 0) == pdTRUE) {
            send_state(state);
        }
    }
}

esp_err_t usb_serial_control_start(void)
{
    usb_serial_jtag_driver_config_t config = {
        .tx_buffer_size = USB_TX_BUFFER_SIZE,
        .rx_buffer_size = USB_RX_BUFFER_SIZE,
    };
    esp_err_t err = usb_serial_jtag_driver_install(&config);
    if (err != ESP_OK) {
        return err;
    }

    s_state_queue = xQueueCreate(1, sizeof(metronome_state_t));
    if (s_state_queue == NULL) {
        return ESP_ERR_NO_MEM;
    }

    err = metronome_app_subscribe(s_state_queue);
    if (err != ESP_OK) {
        return err;
    }

    if (xTaskCreate(usb_control_task, "usb_control", 4096, NULL, 5, NULL) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG, "USB control ready: STATE, TOGGLE, BPM, MASK, TRIGGER");
    return ESP_OK;
}
