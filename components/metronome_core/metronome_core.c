#include "metronome_core.h"

#include <stddef.h>
#include <string.h>

uint8_t metronome_core_ping_pong(uint64_t beat_index, uint8_t positions)
{
    if (positions < 2) {
        return 0;
    }

    const uint64_t period = 2U * (uint64_t)(positions - 1U);
    const uint64_t folded = beat_index % period;
    return (uint8_t)(folded < positions ? folded : period - folded);
}

void metronome_core_init(metronome_core_t *core,
                         uint32_t sample_rate_hz,
                         uint16_t ppqn,
                         uint16_t bpm)
{
    if (core == NULL) {
        return;
    }

    memset(core, 0, sizeof(*core));
    core->sample_rate_hz = sample_rate_hz;
    core->ppqn = ppqn;
    core->bpm = bpm;
}

void metronome_core_set_bpm(metronome_core_t *core, uint16_t bpm)
{
    if (core != NULL && bpm > 0) {
        core->bpm = bpm;
    }
}

void metronome_core_set_running(metronome_core_t *core, bool running)
{
    if (core == NULL || core->running == running) {
        return;
    }

    core->running = running;
    if (running) {
        core->phase = 0;
        core->run_samples = 0;
        core->ppqn_tick = 0;
        core->beats_emitted = 0;
        core->last_beat_index = 0;
        core->ui_position = 0;
        core->led_position = 0;
        core->pending_start_beat = true;
    } else {
        core->pending_start_beat = false;
    }
}

static void emit_beat(metronome_core_t *core,
                      metronome_core_event_t *event)
{
    const uint64_t beat_index = core->beats_emitted++;
    core->last_beat_index = beat_index;
    core->ui_position = metronome_core_ping_pong(beat_index, 4);
    core->led_position = metronome_core_ping_pong(beat_index, 5);

    event->beat = true;
    event->accent = (beat_index % 4U) == 0U;
    event->beat_index = beat_index;
    event->ui_position = core->ui_position;
    event->led_position = core->led_position;
}

void metronome_core_step(metronome_core_t *core,
                         metronome_core_event_t *event)
{
    if (core == NULL || event == NULL) {
        return;
    }

    memset(event, 0, sizeof(*event));
    core->total_samples++;

    if (!core->running || core->sample_rate_hz == 0 || core->ppqn == 0) {
        return;
    }

    core->run_samples++;
    if (core->pending_start_beat) {
        core->pending_start_beat = false;
        emit_beat(core, event);
        return;
    }

    const uint64_t threshold = (uint64_t)core->sample_rate_hz * 60U;
    core->phase += (uint64_t)core->bpm * core->ppqn;

    while (core->phase >= threshold) {
        core->phase -= threshold;
        core->ppqn_tick++;
        if (event->ppqn_ticks < UINT8_MAX) {
            event->ppqn_ticks++;
        }

        if ((core->ppqn_tick % core->ppqn) == 0U) {
            emit_beat(core, event);
        }
    }
}
