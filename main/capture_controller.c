#include "capture_controller.h"

#include <string.h>

#include "freertos/queue.h"
#include "freertos/semphr.h"

#define CAPTURE_EVENT_QUEUE_LENGTH 8

static SemaphoreHandle_t s_mutex;
static QueueHandle_t s_event_queue;
static capture_state_t s_state = CAPTURE_STATE_IDLE;
static capture_state_t s_sync_failure_state = CAPTURE_STATE_IDLE;
static bool s_ready;

static bool take_lock(void)
{
    return s_mutex != NULL &&
           xSemaphoreTake(s_mutex, pdMS_TO_TICKS(150)) == pdTRUE;
}

static void give_lock(void)
{
    xSemaphoreGive(s_mutex);
}

static void publish_event(bool started,
                          capture_origin_t origin,
                          metronome_capture_marker_t marker)
{
    const capture_event_t event = {
        .started = started,
        .origin = origin,
        .marker = marker,
    };
    (void)xQueueSend(s_event_queue, &event, 0);
}

esp_err_t capture_controller_init(void)
{
    s_mutex = xSemaphoreCreateMutex();
    s_event_queue = xQueueCreate(CAPTURE_EVENT_QUEUE_LENGTH,
                                 sizeof(capture_event_t));
    if (s_mutex == NULL || s_event_queue == NULL) {
        return ESP_ERR_NO_MEM;
    }
    s_state = CAPTURE_STATE_IDLE;
    s_sync_failure_state = CAPTURE_STATE_IDLE;
    s_ready = false;
    return ESP_OK;
}

void capture_controller_set_ready(bool ready)
{
    if (!take_lock()) {
        return;
    }
    s_ready = ready;
    if (!ready && s_state != CAPTURE_STATE_IDLE) {
        s_state = CAPTURE_STATE_IDLE;
        xQueueReset(s_event_queue);
    }
    give_lock();
}

bool capture_controller_is_ready(void)
{
    if (!take_lock()) {
        return false;
    }
    const bool ready = s_ready;
    give_lock();
    return ready;
}

capture_state_t capture_controller_get_state(void)
{
    if (!take_lock()) {
        return CAPTURE_STATE_IDLE;
    }
    const capture_state_t state = s_state;
    give_lock();
    return state;
}

const char *capture_controller_state_name(capture_state_t state)
{
    switch (state) {
    case CAPTURE_STATE_IDLE: return "idle";
    case CAPTURE_STATE_STARTING: return "starting";
    case CAPTURE_STATE_RECORDING: return "recording";
    case CAPTURE_STATE_STOPPING: return "stopping";
    case CAPTURE_STATE_PROCESSING: return "processing";
    case CAPTURE_STATE_SYNCING: return "syncing";
    default: return "unknown";
    }
}

bool capture_controller_controls_locked(void)
{
    return capture_controller_get_state() != CAPTURE_STATE_IDLE;
}

bool capture_controller_start(capture_origin_t origin)
{
    if (!take_lock()) {
        return false;
    }
    if (!s_ready || s_state != CAPTURE_STATE_IDLE ||
        metronome_app_get_state().running) {
        give_lock();
        return false;
    }
    s_state = CAPTURE_STATE_STARTING;
    const uint16_t empty[METRONOME_DRUM_TRACK_COUNT] = {0};
    metronome_capture_marker_t marker;
    const bool success = metronome_app_set_pattern(empty) &&
                         metronome_app_capture_marker(&marker);
    s_state = success ? CAPTURE_STATE_RECORDING : CAPTURE_STATE_IDLE;
    give_lock();
    if (success) {
        publish_event(true, origin, marker);
    }
    return success;
}

bool capture_controller_stop(capture_origin_t origin)
{
    if (!take_lock()) {
        return false;
    }
    if (s_state != CAPTURE_STATE_RECORDING) {
        give_lock();
        return false;
    }
    s_state = CAPTURE_STATE_STOPPING;
    metronome_capture_marker_t marker;
    const bool success = metronome_app_capture_marker(&marker);
    s_state = success ? CAPTURE_STATE_PROCESSING : CAPTURE_STATE_IDLE;
    give_lock();
    if (success) {
        publish_event(false, origin, marker);
    }
    return success;
}

void capture_controller_abort(void)
{
    if (!take_lock()) {
        return;
    }
    s_state = CAPTURE_STATE_IDLE;
    xQueueReset(s_event_queue);
    give_lock();
}

bool capture_controller_begin_sync(void)
{
    if (!take_lock()) {
        return false;
    }
    const bool running = metronome_app_get_state().running;
    const bool allowed = s_state == CAPTURE_STATE_IDLE ||
                         (s_state == CAPTURE_STATE_PROCESSING && !running);
    if (allowed) {
        s_sync_failure_state = s_state;
        s_state = CAPTURE_STATE_SYNCING;
    }
    give_lock();
    return allowed;
}

void capture_controller_finish_sync(bool success)
{
    if (!take_lock()) {
        return;
    }
    if (s_state == CAPTURE_STATE_SYNCING) {
        s_state = success ? CAPTURE_STATE_IDLE : s_sync_failure_state;
    }
    give_lock();
}

bool capture_controller_receive_event(capture_event_t *event, TickType_t wait)
{
    return event != NULL && s_event_queue != NULL &&
           xQueueReceive(s_event_queue, event, wait) == pdTRUE;
}
