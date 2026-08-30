#pragma once

#include <stdbool.h>

#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "metronome_app.h"

typedef enum {
    CAPTURE_STATE_IDLE = 0,
    CAPTURE_STATE_STARTING,
    CAPTURE_STATE_RECORDING,
    CAPTURE_STATE_STOPPING,
    CAPTURE_STATE_PROCESSING,
    CAPTURE_STATE_SYNCING,
} capture_state_t;

typedef enum {
    CAPTURE_ORIGIN_WEB = 0,
    CAPTURE_ORIGIN_S8,
    CAPTURE_ORIGIN_SYSTEM,
} capture_origin_t;

typedef struct {
    bool started;
    capture_origin_t origin;
    metronome_capture_marker_t marker;
} capture_event_t;

esp_err_t capture_controller_init(void);
void capture_controller_set_ready(bool ready);
bool capture_controller_is_ready(void);
capture_state_t capture_controller_get_state(void);
const char *capture_controller_state_name(capture_state_t state);
bool capture_controller_controls_locked(void);
bool capture_controller_start(capture_origin_t origin);
bool capture_controller_stop(capture_origin_t origin);
void capture_controller_abort(void);
bool capture_controller_begin_sync(void);
void capture_controller_finish_sync(bool success);
bool capture_controller_receive_event(capture_event_t *event, TickType_t wait);

