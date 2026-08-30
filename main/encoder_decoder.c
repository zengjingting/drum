#include "encoder_decoder.h"

#include <stddef.h>

void encoder_decoder_init(encoder_decoder_t *decoder, uint8_t initial_ab)
{
    if (decoder == NULL) {
        return;
    }
    decoder->previous_ab = initial_ab & 0x03U;
    decoder->transition_accumulator = 0;
}

int8_t encoder_decoder_update(encoder_decoder_t *decoder, uint8_t current_ab)
{
    static const int8_t transition_table[16] = {
         0, -1,  1,  0,
         1,  0,  0, -1,
        -1,  0,  0,  1,
         0,  1, -1,  0,
    };

    if (decoder == NULL) {
        return 0;
    }

    current_ab &= 0x03U;
    const uint8_t previous_ab = decoder->previous_ab;
    if (current_ab == previous_ab) {
        return 0;
    }

    const int8_t transition =
        transition_table[(previous_ab << 2U) | current_ab];
    decoder->previous_ab = current_ab;

    if (transition == 0) {
        /* Both phases changed between samples: discard the partial movement. */
        decoder->transition_accumulator = 0;
        return 0;
    }

    decoder->transition_accumulator += transition;

    /* The assembled encoder returns to 11 after each physical detent. */
    if (current_ab != 3U) {
        return 0;
    }

    int8_t direction = 0;
    if (decoder->transition_accumulator >= 4) {
        direction = 1;
    } else if (decoder->transition_accumulator <= -4) {
        direction = -1;
    }
    decoder->transition_accumulator = 0;
    return direction;
}
