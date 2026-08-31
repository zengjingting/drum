#include "usb_serial_control.h"

#include <inttypes.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "board_pins.h"
#include "capture_controller.h"
#include "driver/usb_serial_jtag.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "metronome_app.h"

#define USB_RX_BUFFER_SIZE 1024
#define USB_TX_BUFFER_SIZE 1024
#define COMMAND_BUFFER_SIZE 96
#define STATE_JSON_BUFFER_SIZE 512
#define PAD_EVENT_QUEUE_LENGTH 64
#define PROTOCOL_VERSION 3

static const char *TAG = "usb_control";
static QueueHandle_t s_state_queue;
static QueueHandle_t s_pad_event_queue;
static bool s_streaming_pad_events;
static uint64_t s_recording_start_frame;

static const char *capture_origin_name(capture_origin_t origin)
{
    switch (origin) {
    case CAPTURE_ORIGIN_WEB: return "web";
    case CAPTURE_ORIGIN_S8: return "s8";
    case CAPTURE_ORIGIN_SYSTEM: return "system";
    default: return "unknown";
    }
}

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
                          "\"protocolVersion\":%u,"
                          "\"capabilities\":[\"pattern\",\"trigger\",\"sequencer\",\"padEvents\",\"hardwareCaptureButton\",\"revisionCommit\"],"
                          "\"captureState\":\"%s\",\"captureReady\":%s,"
                          "\"accent\":%s,\"beat\":%" PRIu64 ","
                          "\"ppqnTick\":%" PRIu64 ",\"uiPosition\":%u,"
                          "\"ledPosition\":%u,\"sequenceStep\":%u,"
                          "\"lastPad\":%u,\"padEvent\":%" PRIu32 ","
                          "\"patternRevision\":%" PRIu32 ","
                          "\"pattern\":[%u,%u,%u,%u,%u,%u]}\n",
                          state.bpm,
                          state.running ? "true" : "false",
                          PROTOCOL_VERSION,
                          capture_controller_state_name(
                              capture_controller_get_state()),
                          capture_controller_is_ready() ? "true" : "false",
                          state.accent ? "true" : "false",
                          state.beat_index,
                          state.ppqn_tick,
                          state.ui_position,
                          state.led_position,
                          state.sequence_step,
                          state.last_pad,
                          state.pad_event,
                          state.pattern_revision,
                          state.pattern[0], state.pattern[1], state.pattern[2],
                          state.pattern[3], state.pattern[4], state.pattern[5]);
    if (length < 0 || (size_t)length >= sizeof(response)) {
        ESP_LOGE(TAG, "State response buffer is too small");
        return;
    }
    write_all(response);
}

static void send_pad_event(metronome_pad_event_t event)
{
    char response[160];
    int length = snprintf(response, sizeof(response),
                          "{\"type\":\"pad\",\"event\":%" PRIu32 ","
                          "\"track\":%u,\"frame\":%" PRIu64 ","
                          "\"source\":\"hardware\"}\n",
                          event.event, event.track, event.frame);
    if (length > 0 && (size_t)length < sizeof(response)) {
        write_all(response);
    }
}

static void send_record_boundary(const char *phase,
                                 capture_origin_t origin,
                                 metronome_capture_marker_t marker)
{
    char response[192];
    int length = snprintf(response, sizeof(response),
                          "{\"type\":\"record\",\"phase\":\"%s\","
                          "\"origin\":\"%s\","
                          "\"frame\":%" PRIu64 ",\"lastEvent\":%" PRIu32 ","
                          "\"dropped\":%" PRIu32 "}\n",
                          phase, capture_origin_name(origin), marker.frame,
                          marker.last_pad_event,
                          marker.dropped_pad_events);
    if (length > 0 && (size_t)length < sizeof(response)) {
        write_all(response);
    }
}

static void drain_pad_events(uint64_t end_frame)
{
    metronome_pad_event_t event;
    while (xQueueReceive(s_pad_event_queue, &event, 0) == pdTRUE) {
        if (s_streaming_pad_events &&
            event.frame >= s_recording_start_frame &&
            event.frame <= end_frame) {
            send_pad_event(event);
        }
    }
}

static void send_ack(const char *command)
{
    char response[96];
    int length = snprintf(response, sizeof(response),
                          "{\"type\":\"ack\",\"command\":\"%s\"}\n",
                          command);
    if (length > 0 && (size_t)length < sizeof(response)) {
        write_all(response);
    }
}

static void send_commit_ack(metronome_state_t state)
{
    char response[224];
    int length = snprintf(response, sizeof(response),
                          "{\"type\":\"ack\",\"command\":\"COMMIT\","
                          "\"revision\":%" PRIu32 ",\"bpm\":%u,"
                          "\"pattern\":[%u,%u,%u,%u,%u,%u]}\n",
                          state.pattern_revision, state.bpm,
                          state.pattern[0], state.pattern[1], state.pattern[2],
                          state.pattern[3], state.pattern[4], state.pattern[5]);
    if (length > 0 && (size_t)length < sizeof(response)) {
        write_all(response);
    }
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
        if (capture_controller_controls_locked()) {
            send_error("Playback is locked during capture processing");
            return;
        }
        metronome_app_toggle();
        return;
    }

    if (strcmp(command, "CAPTURE READY 1") == 0) {
        capture_controller_set_ready(true);
        send_ack("CAPTURE READY");
        return;
    }

    if (strcmp(command, "CAPTURE READY 0") == 0 ||
        strcmp(command, "ABORT") == 0) {
        capture_controller_set_ready(false);
        capture_controller_abort();
        s_streaming_pad_events = false;
        xQueueReset(s_pad_event_queue);
        send_ack(strcmp(command, "ABORT") == 0 ? "ABORT" : "CAPTURE READY");
        return;
    }

    if (strcmp(command, "RECORD START") == 0) {
        const capture_state_t capture_state = capture_controller_get_state();
        if (!capture_controller_is_ready()) {
            send_error("Recording requires CAPTURE READY 1");
            return;
        }
        if (metronome_app_get_state().running) {
            send_error("Recording is unavailable during playback");
            return;
        }
        if (capture_state != CAPTURE_STATE_IDLE) {
            char message[96];
            snprintf(message, sizeof(message),
                     "Recording is busy in capture state %s",
                     capture_controller_state_name(capture_state));
            send_error(message);
            return;
        }
        if (!capture_controller_start(CAPTURE_ORIGIN_WEB)) {
            send_error("Recording start boundary could not be applied");
        }
        return;
    }

    if (strcmp(command, "RECORD STOP") == 0) {
        if (capture_controller_get_state() != CAPTURE_STATE_RECORDING) {
            send_error("Recording stop requires an active recording");
            return;
        }
        if (!capture_controller_stop(CAPTURE_ORIGIN_WEB)) {
            send_error("Recording stop boundary could not be applied");
        }
        return;
    }

    if (strncmp(command, "BPM ", 4) == 0) {
        char *end = NULL;
        long bpm = strtol(command + 4, &end, 10);
        if (end != command + 4 && *end == '\0' &&
            bpm >= METRONOME_MIN_BPM && bpm <= METRONOME_MAX_BPM) {
            if (capture_controller_controls_locked() ||
                !metronome_app_get_state().running) {
                send_error("BPM adjustment is only available during playback");
                return;
            }
            metronome_app_set_bpm((uint16_t)bpm);
            return;
        }
        send_error("BPM must be an integer from 40 to 240");
        return;
    }

    unsigned pad = 0;
    unsigned mask = 0;
    char trailing = '\0';
    unsigned values[METRONOME_DRUM_TRACK_COUNT] = {0};
    uint32_t revision = 0;
    unsigned commit_bpm = 0;
    int commit_fields = sscanf(command,
        "COMMIT %" SCNu32 " %u %u %u %u %u %u %u %c",
        &revision, &commit_bpm,
        &values[0], &values[1], &values[2],
        &values[3], &values[4], &values[5], &trailing);
    if (commit_fields == METRONOME_DRUM_TRACK_COUNT + 2) {
        uint16_t pattern[METRONOME_DRUM_TRACK_COUNT];
        if (commit_bpm < METRONOME_MIN_BPM ||
            commit_bpm > METRONOME_MAX_BPM) {
            send_error("COMMIT BPM must be an integer from 40 to 240");
            return;
        }
        for (size_t index = 0; index < METRONOME_DRUM_TRACK_COUNT; ++index) {
            if (values[index] > UINT16_MAX) {
                send_error("COMMIT pattern values must be 0-65535");
                return;
            }
            pattern[index] = (uint16_t)values[index];
        }
        if (!capture_controller_begin_sync()) {
            send_error("COMMIT is not safe in the current device state");
            return;
        }
        const bool committed = metronome_app_commit_pattern(
            revision, (uint16_t)commit_bpm, pattern);
        capture_controller_finish_sync(committed);
        if (committed) {
            send_commit_ack(metronome_app_get_state());
        } else {
            send_error("COMMIT could not be applied");
        }
        return;
    }
    if (strncmp(command, "COMMIT", 6) == 0) {
        send_error("COMMIT needs revision, BPM, and exactly 6 pattern values");
        return;
    }
    int pattern_fields = sscanf(command,
        "PATTERN %u %u %u %u %u %u %c",
        &values[0], &values[1], &values[2],
        &values[3], &values[4], &values[5], &trailing);
    if (pattern_fields == METRONOME_DRUM_TRACK_COUNT) {
        uint16_t pattern[METRONOME_DRUM_TRACK_COUNT];
        for (size_t index = 0; index < METRONOME_DRUM_TRACK_COUNT; ++index) {
            if (values[index] > UINT16_MAX) {
                send_error("PATTERN values must be 0-65535");
                return;
            }
            pattern[index] = (uint16_t)values[index];
        }
        if (metronome_app_set_pattern(pattern)) {
            send_ack("PATTERN");
        } else {
            send_error("PATTERN could not be queued");
        }
        return;
    }
    if (strncmp(command, "PATTERN", 7) == 0) {
        send_error("PATTERN needs exactly 6 values from 0-65535");
        return;
    }

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
    bool was_connected = false;

    for (;;) {
        const bool connected = usb_serial_jtag_is_connected();
        if (!connected && was_connected) {
            capture_controller_set_ready(false);
            capture_controller_abort();
            s_streaming_pad_events = false;
            xQueueReset(s_pad_event_queue);
        }
        was_connected = connected;

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
        capture_event_t capture_event;
        while (capture_controller_receive_event(&capture_event, 0)) {
            if (capture_event.started) {
                s_recording_start_frame = capture_event.marker.frame;
                s_streaming_pad_events = true;
                send_record_boundary("started", capture_event.origin,
                                     capture_event.marker);
                drain_pad_events(UINT64_MAX);
            } else {
                drain_pad_events(capture_event.marker.frame);
                s_streaming_pad_events = false;
                send_record_boundary("stopped", capture_event.origin,
                                     capture_event.marker);
                xQueueReset(s_pad_event_queue);
            }
        }
        if (s_streaming_pad_events) {
            drain_pad_events(UINT64_MAX);
        } else if (capture_controller_get_state() != CAPTURE_STATE_RECORDING) {
            xQueueReset(s_pad_event_queue);
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
    s_pad_event_queue = xQueueCreate(PAD_EVENT_QUEUE_LENGTH,
                                     sizeof(metronome_pad_event_t));
    if (s_state_queue == NULL || s_pad_event_queue == NULL) {
        return ESP_ERR_NO_MEM;
    }

    err = metronome_app_subscribe(s_state_queue);
    if (err != ESP_OK) {
        return err;
    }
    err = metronome_app_subscribe_pad_events(s_pad_event_queue);
    if (err != ESP_OK) {
        return err;
    }

    if (xTaskCreate(usb_control_task, "usb_control", 4096, NULL, 5, NULL) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG,
             "USB protocol v%d ready: STATE, TOGGLE, BPM, PATTERN, MASK, "
             "TRIGGER, RECORD, COMMIT, CAPTURE READY, ABORT",
             PROTOCOL_VERSION);
    return ESP_OK;
}
