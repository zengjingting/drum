#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

#define METRONOME_DRUM_TRACK_COUNT 6

typedef struct {
    uint16_t bpm;
    bool running;
    bool accent;
    uint64_t beat_index;
    uint64_t ppqn_tick;
    uint8_t ui_position;
    uint8_t led_position;
    uint8_t sequence_step;
    uint8_t last_pad;
    uint32_t pad_event;
    uint16_t pattern[METRONOME_DRUM_TRACK_COUNT];
} metronome_state_t;

esp_err_t metronome_app_start(void);
esp_err_t metronome_app_subscribe(QueueHandle_t state_queue);
metronome_state_t metronome_app_get_state(void);

void metronome_app_set_bpm(int bpm);
void metronome_app_adjust_bpm(int delta);
void metronome_app_set_running(bool running);
void metronome_app_toggle(void);
bool metronome_app_trigger_drum(uint8_t pad_index);
bool metronome_app_set_pattern_mask(uint8_t pad_index, uint16_t mask);
bool metronome_app_set_pattern(
    const uint16_t pattern[METRONOME_DRUM_TRACK_COUNT]);
