#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    uint32_t sample_rate_hz;
    uint16_t ppqn;
    uint16_t bpm;
    bool running;
    bool pending_start_beat;
    uint64_t phase;
    uint64_t total_samples;
    uint64_t run_samples;
    uint64_t ppqn_tick;
    uint64_t beats_emitted;
    uint64_t last_beat_index;
    uint8_t ui_position;
    uint8_t led_position;
} metronome_core_t;

typedef struct {
    bool beat;
    bool accent;
    uint8_t ppqn_ticks;
    uint64_t beat_index;
    uint8_t ui_position;
    uint8_t led_position;
} metronome_core_event_t;

void metronome_core_init(metronome_core_t *core,
                         uint32_t sample_rate_hz,
                         uint16_t ppqn,
                         uint16_t bpm);
void metronome_core_set_bpm(metronome_core_t *core, uint16_t bpm);
void metronome_core_set_running(metronome_core_t *core, bool running);
void metronome_core_step(metronome_core_t *core,
                         metronome_core_event_t *event);
uint8_t metronome_core_ping_pong(uint64_t beat_index, uint8_t positions);

#ifdef __cplusplus
}
#endif
