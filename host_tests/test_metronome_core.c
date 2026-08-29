#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "metronome_core.h"

static void test_exact_120_bpm_spacing(void)
{
    metronome_core_t core;
    metronome_core_event_t event;
    metronome_core_init(&core, 48000, 96, 120);
    metronome_core_set_running(&core, true);

    uint64_t beat_samples[3] = {0};
    size_t beat_count = 0;
    for (uint64_t sample = 0; sample <= 48000; ++sample) {
        metronome_core_step(&core, &event);
        if (event.beat && beat_count < 3) {
            beat_samples[beat_count++] = sample;
        }
    }

    assert(beat_count == 3);
    assert(beat_samples[0] == 0);
    assert(beat_samples[1] == 24000);
    assert(beat_samples[2] == 48000);
    assert(core.ppqn_tick == 192);
}

static void test_fractional_bpm_has_bounded_phase_error(void)
{
    metronome_core_t core;
    metronome_core_event_t event;
    metronome_core_init(&core, 48000, 96, 137);
    metronome_core_set_running(&core, true);

    for (uint64_t sample = 0; sample < 480001; ++sample) {
        metronome_core_step(&core, &event);
    }

    const uint64_t expected_ticks = (480000ULL * 137ULL * 96ULL) /
                                    (48000ULL * 60ULL);
    assert(core.ppqn_tick == expected_ticks);
    assert(core.phase < 48000ULL * 60ULL);
}

static void test_ping_pong_sequences(void)
{
    const uint8_t ui_expected[] = {0, 1, 2, 3, 2, 1, 0};
    const uint8_t led_expected[] = {0, 1, 2, 3, 4, 3, 2, 1, 0};

    for (size_t i = 0; i < sizeof(ui_expected); ++i) {
        assert(metronome_core_ping_pong(i, 4) == ui_expected[i]);
    }
    for (size_t i = 0; i < sizeof(led_expected); ++i) {
        assert(metronome_core_ping_pong(i, 5) == led_expected[i]);
    }
}

static void test_stop_and_restart_resets_transport(void)
{
    metronome_core_t core;
    metronome_core_event_t event;
    metronome_core_init(&core, 48000, 96, 120);
    metronome_core_set_running(&core, true);
    metronome_core_step(&core, &event);
    assert(event.beat && event.beat_index == 0);

    metronome_core_set_running(&core, false);
    for (int i = 0; i < 100; ++i) {
        metronome_core_step(&core, &event);
        assert(!event.beat);
    }

    metronome_core_set_running(&core, true);
    metronome_core_step(&core, &event);
    assert(event.beat && event.beat_index == 0);
    assert(core.ppqn_tick == 0);
}

int main(void)
{
    test_exact_120_bpm_spacing();
    test_fractional_bpm_has_bounded_phase_error();
    test_ping_pong_sequences();
    test_stop_and_restart_resets_transport();
    puts("metronome_core: all tests passed");
    return 0;
}
