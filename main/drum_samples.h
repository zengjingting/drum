#pragma once

#include <stddef.h>

#include "drum_mixer.h"

#define DRUM_SAMPLE_COUNT 6

void drum_samples_init(void);
const drum_sample_t *drum_samples_get(size_t index);
const char *drum_samples_name(size_t index);
