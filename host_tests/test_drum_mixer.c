#include <assert.h>
#include <limits.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "drum_mixer.h"

static int16_t s_sample_a[70];
static int16_t s_sample_b[70];

static void prepare_samples(void)
{
    for (size_t index = 0; index < 70; ++index) {
        s_sample_a[index] = 1000;
        s_sample_b[index] = 2000;
    }
}

static void test_overlap_and_retrigger(void)
{
    const drum_sample_t sample_a = {
        .pcm = s_sample_a,
        .sample_count = 70,
        .gain_q15 = INT16_MAX,
    };
    const drum_sample_t sample_b = {
        .pcm = s_sample_b,
        .sample_count = 70,
        .gain_q15 = INT16_MAX,
    };
    drum_mixer_t mixer;
    drum_mixer_init(&mixer);

    assert(drum_mixer_trigger(&mixer, &sample_a));
    assert(drum_mixer_render(&mixer) == 999);
    assert(drum_mixer_trigger(&mixer, &sample_a));
    assert(drum_mixer_render(&mixer) == 1998);
    assert(drum_mixer_trigger(&mixer, &sample_b));
    assert(drum_mixer_render(&mixer) == 3997);
    assert(drum_mixer_active_voices(&mixer) == 3);

    for (size_t frame = 0; frame < 67; ++frame) {
        (void)drum_mixer_render(&mixer);
    }
    assert(drum_mixer_active_voices(&mixer) == 2);
    (void)drum_mixer_render(&mixer);
    assert(drum_mixer_active_voices(&mixer) == 1);
    (void)drum_mixer_render(&mixer);
    assert(drum_mixer_active_voices(&mixer) == 0);
}

static void test_voice_capacity_preserves_active_audio(void)
{
    const drum_sample_t sample = {
        .pcm = s_sample_a,
        .sample_count = 70,
        .gain_q15 = INT16_MAX,
    };
    drum_mixer_t mixer;
    drum_mixer_init(&mixer);

    for (size_t index = 0; index < DRUM_MIXER_MAX_VOICES; ++index) {
        assert(drum_mixer_trigger(&mixer, &sample));
    }
    assert(drum_mixer_active_voices(&mixer) == DRUM_MIXER_MAX_VOICES);
    assert(!drum_mixer_trigger(&mixer, &sample));
    assert(mixer.dropped_trigger_count == 1);
    assert(drum_mixer_active_voices(&mixer) == DRUM_MIXER_MAX_VOICES);
    assert(drum_mixer_render(&mixer) ==
           999 * (int32_t)DRUM_MIXER_MAX_VOICES);
}

static void test_tail_fade_and_soft_limiter(void)
{
    const drum_sample_t sample = {
        .pcm = s_sample_a,
        .sample_count = 70,
        .gain_q15 = INT16_MAX,
    };
    drum_mixer_t mixer;
    drum_mixer_init(&mixer);
    assert(drum_mixer_trigger(&mixer, &sample));

    int32_t previous = drum_mixer_render(&mixer);
    for (size_t frame = 1; frame < 70; ++frame) {
        const int32_t current = drum_mixer_render(&mixer);
        if (frame >= 6) {
            assert(current <= previous);
        }
        previous = current;
    }
    assert(drum_mixer_active_voices(&mixer) == 0);
    assert(drum_mixer_soft_limit(0) == 0);
    assert(drum_mixer_soft_limit(20000) == 20000);
    assert(drum_mixer_soft_limit(1000000) <= INT16_MAX);
    assert(drum_mixer_soft_limit(-1000000) >= INT16_MIN);
    assert(drum_mixer_soft_limit(1000000) ==
           -drum_mixer_soft_limit(-1000000));
}

static void test_invalid_inputs(void)
{
    drum_mixer_t mixer;
    drum_mixer_init(&mixer);
    const drum_sample_t empty = {0};
    assert(!drum_mixer_trigger(NULL, &empty));
    assert(!drum_mixer_trigger(&mixer, NULL));
    assert(!drum_mixer_trigger(&mixer, &empty));
    assert(drum_mixer_render(NULL) == 0);
    assert(drum_mixer_active_voices(NULL) == 0);
}

int main(void)
{
    prepare_samples();
    test_overlap_and_retrigger();
    test_voice_capacity_preserves_active_audio();
    test_tail_fade_and_soft_limiter();
    test_invalid_inputs();
    puts("drum_mixer: all tests passed");
    return 0;
}
