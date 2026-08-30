#pragma once

#include <stdint.h>

typedef struct {
    uint8_t previous_ab;
    int8_t transition_accumulator;
} encoder_decoder_t;

void encoder_decoder_init(encoder_decoder_t *decoder, uint8_t initial_ab);

/* Returns +1 or -1 after one complete quadrature cycle (one physical click). */
int8_t encoder_decoder_update(encoder_decoder_t *decoder, uint8_t current_ab);
