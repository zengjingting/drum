#include "drum_samples.h"

#include <stdbool.h>
#include <stdint.h>

#define BINARY_SYMBOL(name) \
    extern const uint8_t name##_start[] asm("_binary_" #name "_start"); \
    extern const uint8_t name##_end[] asm("_binary_" #name "_end")

BINARY_SYMBOL(s1_kick_pcm);
BINARY_SYMBOL(s2_snare_pcm);
BINARY_SYMBOL(s3_closed_hihat_pcm);
BINARY_SYMBOL(s4_open_hihat_pcm);
BINARY_SYMBOL(s5_clap_pcm);
BINARY_SYMBOL(s6_rimshot_pcm);

typedef struct {
    const uint8_t *start;
    const uint8_t *end;
    int32_t gain_q15;
    const char *name;
} embedded_sample_t;

static const embedded_sample_t s_embedded[DRUM_SAMPLE_COUNT] = {
    /* The ccMixter acoustic kick is level-prepared in the PCM. */
    {s1_kick_pcm_start, s1_kick_pcm_end, 32768, "kick"},
    /* Natural mid-mic snare; -3 dB preserves the previous board peak level. */
    {s2_snare_pcm_start, s2_snare_pcm_end, 23198, "snare"},
    /* The darker natural closed hat is level-prepared in the PCM. */
    {s3_closed_hihat_pcm_start, s3_closed_hihat_pcm_end, 32768, "closed hi-hat"},
    /* Beatbox's 40% open-hat is pre-rendered; -4.5 dB matches the natural kit. */
    {s4_open_hihat_pcm_start, s4_open_hihat_pcm_end, 19519, "open hi-hat"},
    /* Beatbox's voice/limiter are pre-rendered; -10.5 dB matches the natural kit. */
    {s5_clap_pcm_start, s5_clap_pcm_end, 9782, "clap"},
    /* Beatbox's Rim path is pre-rendered; -3 dB avoids a board level jump. */
    {s6_rimshot_pcm_start, s6_rimshot_pcm_end, 23198, "rimshot"},
};

static drum_sample_t s_samples[DRUM_SAMPLE_COUNT];
static bool s_initialized;

void drum_samples_init(void)
{
    if (s_initialized) {
        return;
    }
    for (size_t index = 0; index < DRUM_SAMPLE_COUNT; ++index) {
        const embedded_sample_t *embedded = &s_embedded[index];
        s_samples[index] = (drum_sample_t) {
            .pcm = (const int16_t *)embedded->start,
            .sample_count = (uint32_t)(embedded->end - embedded->start) /
                            sizeof(int16_t),
            .gain_q15 = embedded->gain_q15,
        };
    }
    s_initialized = true;
}

const drum_sample_t *drum_samples_get(size_t index)
{
    if (!s_initialized || index >= DRUM_SAMPLE_COUNT) {
        return NULL;
    }
    return &s_samples[index];
}

const char *drum_samples_name(size_t index)
{
    return index < DRUM_SAMPLE_COUNT ? s_embedded[index].name : "unknown";
}
