#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define DRUM_MIXER_MAX_VOICES 128
#define DRUM_MIXER_TAIL_FADE_SAMPLES 64

typedef struct {
    const int16_t *pcm;
    uint32_t sample_count;
    int16_t gain_q15;
} drum_sample_t;

typedef struct {
    const drum_sample_t *sample;
    uint32_t position;
} drum_voice_t;

typedef struct {
    drum_voice_t voices[DRUM_MIXER_MAX_VOICES];
    uint16_t active_voice_count;
    uint32_t dropped_trigger_count;
} drum_mixer_t;

void drum_mixer_init(drum_mixer_t *mixer);
bool drum_mixer_trigger(drum_mixer_t *mixer, const drum_sample_t *sample);
int32_t drum_mixer_render(drum_mixer_t *mixer);
int16_t drum_mixer_soft_limit(int32_t sample);
size_t drum_mixer_active_voices(const drum_mixer_t *mixer);
