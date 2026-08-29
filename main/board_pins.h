#pragma once

#include "driver/gpio.h"

/* EasyInput V2.0 / firmware alias v2 / PCB silkscreen AI Keyboard V2.1. */
#define PIN_SHARED_POWER      GPIO_NUM_8
#define PIN_WS2812_DATA       GPIO_NUM_12
#define PIN_STATUS_LED        GPIO_NUM_42

#define PIN_ENCODER_A         GPIO_NUM_17
#define PIN_ENCODER_B         GPIO_NUM_16
#define PIN_ENCODER_BUTTON    GPIO_NUM_18

#define PIN_MIC_BCLK          GPIO_NUM_9
#define PIN_MIC_WS            GPIO_NUM_10
#define PIN_MIC_DATA_IN       GPIO_NUM_11

#define PIN_SPEAKER_BCLK      GPIO_NUM_14
#define PIN_SPEAKER_WS        GPIO_NUM_13
#define PIN_SPEAKER_DATA_OUT  GPIO_NUM_15

/* Project choices, not board-level minimums or electrical guarantees. */
#define SHARED_POWER_SETTLE_MS 50
#define METRONOME_SAMPLE_RATE_HZ 48000
#define METRONOME_PPQN 96
#define METRONOME_DEFAULT_BPM 120
#define METRONOME_MIN_BPM 40
#define METRONOME_MAX_BPM 240
#define ENCODER_BPM_PER_DETENT 1

/* Change to -1 if clockwise rotation decreases BPM on the assembled encoder. */
#define ENCODER_DIRECTION 1
