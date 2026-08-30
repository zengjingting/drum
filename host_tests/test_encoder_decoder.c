#include <assert.h>
#include <stdint.h>
#include <stdio.h>

#include "encoder_decoder.h"

static int feed(encoder_decoder_t *decoder,
                const uint8_t *states,
                size_t count)
{
    int movement = 0;
    for (size_t index = 0; index < count; ++index) {
        movement += encoder_decoder_update(decoder, states[index]);
    }
    return movement;
}

static void test_each_full_cycle_is_one_detent(void)
{
    encoder_decoder_t decoder;
    encoder_decoder_init(&decoder, 3);

    const uint8_t positive[] = {1, 0, 2, 3};
    assert(feed(&decoder, positive, 3) == 0);
    assert(feed(&decoder, positive + 3, 1) == 1);

    const uint8_t negative[] = {2, 0, 1, 3};
    assert(feed(&decoder, negative, 3) == 0);
    assert(feed(&decoder, negative + 3, 1) == -1);
}

static void test_contact_bounce_does_not_duplicate_steps(void)
{
    encoder_decoder_t decoder;
    encoder_decoder_init(&decoder, 3);

    const uint8_t bounced_positive[] = {1, 3, 1, 1, 0, 2, 3};
    assert(feed(&decoder, bounced_positive, 7) == 1);

    encoder_decoder_init(&decoder, 3);
    const uint8_t bounced_negative[] = {2, 3, 2, 2, 0, 1, 3};
    assert(feed(&decoder, bounced_negative, 7) == -1);
}

static void test_invalid_jump_discards_partial_movement(void)
{
    encoder_decoder_t decoder;
    encoder_decoder_init(&decoder, 3);

    const uint8_t invalid_then_valid[] = {1, 2, 0};
    assert(feed(&decoder, invalid_then_valid, 3) == 0);

    const uint8_t recovery[] = {2, 3, 1, 0, 2, 3};
    assert(feed(&decoder, recovery, 6) == 1);
}

static void test_null_and_repeated_states_are_ignored(void)
{
    encoder_decoder_t decoder;
    encoder_decoder_init(&decoder, 3);
    const uint8_t repeated[] = {3, 3, 3};
    assert(feed(&decoder, repeated, 3) == 0);
    assert(encoder_decoder_update(NULL, 0) == 0);
    encoder_decoder_init(NULL, 0);
}

int main(void)
{
    test_each_full_cycle_is_one_detent();
    test_contact_bounce_does_not_duplicate_steps();
    test_invalid_jump_discards_partial_movement();
    test_null_and_repeated_states_are_ignored();
    puts("encoder_decoder: all tests passed");
    return 0;
}
