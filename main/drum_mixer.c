#include "drum_mixer.h"

#include <limits.h>
#include <string.h>

void drum_mixer_init(drum_mixer_t *mixer)
{
    if (mixer != NULL) {
        memset(mixer, 0, sizeof(*mixer));
    }
}

bool drum_mixer_trigger(drum_mixer_t *mixer, const drum_sample_t *sample)
{
    if (mixer == NULL || sample == NULL || sample->pcm == NULL ||
        sample->sample_count == 0 || sample->gain_q15 <= 0) {
        return false;
    }

    for (size_t index = 0; index < DRUM_MIXER_MAX_VOICES; ++index) {
        drum_voice_t *voice = &mixer->voices[index];
        if (voice->sample == NULL) {
            voice->sample = sample;
            voice->position = 0;
            mixer->active_voice_count++;
            return true;
        }
    }

    /* Preserve every voice already sounding instead of stealing/cutting it. */
    mixer->dropped_trigger_count++;
    return false;
}

int32_t drum_mixer_render(drum_mixer_t *mixer)
{
    if (mixer == NULL) {
        return 0;
    }

    int32_t mixed = 0;
    for (size_t index = 0; index < DRUM_MIXER_MAX_VOICES; ++index) {
        drum_voice_t *voice = &mixer->voices[index];
        const drum_sample_t *sample = voice->sample;
        if (sample == NULL) {
            continue;
        }

        int32_t gain_q15 = sample->gain_q15;
        const uint32_t remaining = sample->sample_count - voice->position;
        if (remaining < DRUM_MIXER_TAIL_FADE_SAMPLES) {
            gain_q15 = (gain_q15 * (int32_t)remaining) /
                       DRUM_MIXER_TAIL_FADE_SAMPLES;
        }

        const int32_t value = sample->pcm[voice->position];
        mixed += (value * gain_q15) >> 15;
        voice->position++;
        if (voice->position >= sample->sample_count) {
            voice->sample = NULL;
            voice->position = 0;
            mixer->active_voice_count--;
        }
    }
    return mixed;
}

int16_t drum_mixer_soft_limit(int32_t sample)
{
    const int32_t threshold = 24576;
    const int32_t headroom = INT16_MAX - threshold;
    int32_t magnitude = sample < 0 ? -sample : sample;
    const bool negative = sample < 0;

    if (magnitude > threshold) {
        const int32_t excess = magnitude - threshold;
        magnitude = threshold + (int32_t)(((int64_t)excess * headroom) /
                                           (excess + headroom));
    }
    if (magnitude > INT16_MAX) {
        magnitude = INT16_MAX;
    }
    return (int16_t)(negative ? -magnitude : magnitude);
}

size_t drum_mixer_active_voices(const drum_mixer_t *mixer)
{
    return mixer == NULL ? 0 : mixer->active_voice_count;
}
