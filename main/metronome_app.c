#include "metronome_app.h"

#include <math.h>
#include <string.h>

#include "board_pins.h"
#include "driver/i2s_std.h"
#include "drum_mixer.h"
#include "drum_samples.h"
#include "esp_log.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "metronome_core.h"

#define AUDIO_FRAMES_PER_BLOCK 64
#define MAX_SUBSCRIBERS 4
#define COMMAND_QUEUE_LENGTH 64
#define SEQUENCE_STEP_COUNT 16
#define SEQUENCE_TICKS_PER_STEP (METRONOME_PPQN / 4)

_Static_assert(METRONOME_PPQN % 4 == 0,
               "METRONOME_PPQN must divide evenly into sixteenth notes");
_Static_assert(DRUM_SAMPLE_COUNT == METRONOME_DRUM_TRACK_COUNT,
               "Protocol track count must match the embedded sound bank");

typedef enum {
    COMMAND_SET_BPM,
    COMMAND_ADJUST_BPM,
    COMMAND_SET_RUNNING,
    COMMAND_TOGGLE,
    COMMAND_TRIGGER_DRUM,
    COMMAND_SET_PATTERN_MASK,
    COMMAND_SET_PATTERN,
} command_type_t;

typedef struct {
    command_type_t type;
    int value;
    uint16_t pattern[METRONOME_DRUM_TRACK_COUNT];
    TaskHandle_t completion_task;
} metronome_command_t;

typedef struct {
    float phase;
    float phase_step;
    float gain;
    uint32_t samples_left;
    uint32_t total_samples;
} click_voice_t;

static const char *TAG = "metronome";
static QueueHandle_t s_command_queue;
static SemaphoreHandle_t s_state_mutex;
static QueueHandle_t s_subscribers[MAX_SUBSCRIBERS];
static size_t s_subscriber_count;
static metronome_state_t s_state = {
    .bpm = METRONOME_DEFAULT_BPM,
    .running = false,
    .accent = true,
};
static i2s_chan_handle_t s_i2s_tx;
static drum_mixer_t s_drum_mixer;
static uint16_t s_pattern[DRUM_SAMPLE_COUNT];
static uint32_t s_pad_event;
static uint8_t s_last_pad;

static int clamp_bpm(int bpm)
{
    if (bpm < METRONOME_MIN_BPM) {
        return METRONOME_MIN_BPM;
    }
    if (bpm > METRONOME_MAX_BPM) {
        return METRONOME_MAX_BPM;
    }
    return bpm;
}

static metronome_state_t snapshot_from_core(const metronome_core_t *core,
                                             bool accent)
{
    metronome_state_t state = {
        .bpm = core->bpm,
        .running = core->running,
        .accent = accent,
        .beat_index = core->last_beat_index,
        .ppqn_tick = core->ppqn_tick,
        .ui_position = core->ui_position,
        .led_position = core->led_position,
        .sequence_step = (uint8_t)((core->ppqn_tick /
                            SEQUENCE_TICKS_PER_STEP) % SEQUENCE_STEP_COUNT),
        .last_pad = s_last_pad,
        .pad_event = s_pad_event,
    };
    memcpy(state.pattern, s_pattern, sizeof(state.pattern));
    return state;
}

static void publish_state(metronome_state_t state)
{
    QueueHandle_t subscribers[MAX_SUBSCRIBERS];
    size_t count = 0;

    if (xSemaphoreTake(s_state_mutex, portMAX_DELAY) == pdTRUE) {
        s_state = state;
        count = s_subscriber_count;
        memcpy(subscribers, s_subscribers, count * sizeof(subscribers[0]));
        xSemaphoreGive(s_state_mutex);
    }

    for (size_t i = 0; i < count; ++i) {
        xQueueOverwrite(subscribers[i], &state);
    }
}

static void start_click(click_voice_t *voice, bool accent)
{
    const float frequency_hz = accent ? 1760.0f : 1120.0f;
    const float duration_ms = accent ? 28.0f : 20.0f;
    voice->phase = 0.0f;
    voice->phase_step = 2.0f * (float)M_PI * frequency_hz /
                        (float)METRONOME_SAMPLE_RATE_HZ;
    voice->gain = accent ? 0.34f : 0.22f;
    voice->total_samples = (uint32_t)(duration_ms *
                           (float)METRONOME_SAMPLE_RATE_HZ / 1000.0f);
    voice->samples_left = voice->total_samples;
}

static int16_t render_click_sample(click_voice_t *voice)
{
    if (voice->samples_left == 0 || voice->total_samples == 0) {
        return 0;
    }

    const float envelope = (float)voice->samples_left /
                           (float)voice->total_samples;
    const float sample = sinf(voice->phase) * voice->gain * envelope * envelope;
    voice->phase += voice->phase_step;
    if (voice->phase >= 2.0f * (float)M_PI) {
        voice->phase -= 2.0f * (float)M_PI;
    }
    voice->samples_left--;
    return (int16_t)(sample * 32767.0f);
}

static bool apply_command(metronome_core_t *core,
                          click_voice_t *voice,
                          const metronome_command_t *command)
{
    if (command->type == COMMAND_TRIGGER_DRUM) {
        const drum_sample_t *sample = drum_samples_get((size_t)command->value);
        if (!drum_mixer_trigger(&s_drum_mixer, sample)) {
            ESP_LOGW(TAG, "Drum voice pool full; S%d trigger dropped",
                     command->value + 1);
        }
        s_last_pad = (uint8_t)command->value;
        s_pad_event++;
        return true;
    }

    if (command->type == COMMAND_SET_PATTERN_MASK) {
        const uint8_t pad = (uint8_t)((uint32_t)command->value >> 16);
        if (pad < DRUM_SAMPLE_COUNT) {
            s_pattern[pad] = (uint16_t)command->value;
            return true;
        }
        return false;
    }

    if (command->type == COMMAND_SET_PATTERN) {
        memcpy(s_pattern, command->pattern, sizeof(s_pattern));
        return true;
    }

    const uint16_t previous_bpm = core->bpm;
    const bool previous_running = core->running;

    switch (command->type) {
    case COMMAND_SET_BPM:
        metronome_core_set_bpm(core, (uint16_t)clamp_bpm(command->value));
        break;
    case COMMAND_ADJUST_BPM:
        metronome_core_set_bpm(core,
            (uint16_t)clamp_bpm((int)core->bpm + command->value));
        break;
    case COMMAND_SET_RUNNING:
        metronome_core_set_running(core, command->value != 0);
        break;
    case COMMAND_TOGGLE:
        metronome_core_set_running(core, !core->running);
        break;
    case COMMAND_TRIGGER_DRUM:
    case COMMAND_SET_PATTERN_MASK:
    case COMMAND_SET_PATTERN:
        break;
    }

    if (!core->running) {
        memset(voice, 0, sizeof(*voice));
    }
    return previous_bpm != core->bpm || previous_running != core->running;
}

static void audio_task(void *arg)
{
    (void)arg;
    int16_t samples[AUDIO_FRAMES_PER_BLOCK * 2];
    metronome_core_t core;
    click_voice_t click = {0};

    metronome_core_init(&core, METRONOME_SAMPLE_RATE_HZ,
                        METRONOME_PPQN, METRONOME_DEFAULT_BPM);
    publish_state(snapshot_from_core(&core, true));

    while (true) {
        metronome_command_t command;
        while (xQueueReceive(s_command_queue, &command, 0) == pdTRUE) {
            if (apply_command(&core, &click, &command)) {
                publish_state(snapshot_from_core(
                    &core, (core.last_beat_index % 4U) == 0U));
            }
            if (command.completion_task != NULL) {
                xTaskNotifyGive(command.completion_task);
            }
        }

        bool block_has_beat = false;
        bool block_has_sequence_step = false;
        bool block_accent = false;
        for (size_t frame = 0; frame < AUDIO_FRAMES_PER_BLOCK; ++frame) {
            metronome_core_event_t event;
            metronome_core_step(&core, &event);
            const bool sequence_step =
                (event.beat && event.beat_index == 0U && core.ppqn_tick == 0U) ||
                (event.ppqn_ticks > 0U &&
                 (core.ppqn_tick % SEQUENCE_TICKS_PER_STEP) == 0U);
            if (sequence_step) {
                const uint8_t step = (uint8_t)((core.ppqn_tick /
                                     SEQUENCE_TICKS_PER_STEP) %
                                     SEQUENCE_STEP_COUNT);
                for (size_t pad = 0; pad < DRUM_SAMPLE_COUNT; ++pad) {
                    if ((s_pattern[pad] & (1U << step)) != 0U) {
                        if (!drum_mixer_trigger(&s_drum_mixer,
                                                drum_samples_get(pad))) {
                            ESP_LOGW(TAG, "Sequence trigger dropped: S%u step %u",
                                     (unsigned)pad + 1U, (unsigned)step + 1U);
                        }
                    }
                }
                block_has_sequence_step = true;
            }
            if (event.beat) {
                start_click(&click, event.accent);
                block_has_beat = true;
                block_accent = event.accent;
            }

            int32_t mixed = drum_mixer_render(&s_drum_mixer);
            if (core.running) {
                mixed += render_click_sample(&click);
            }
            const int16_t sample = drum_mixer_soft_limit(mixed);
            samples[frame * 2] = sample;
            samples[frame * 2 + 1] = sample;
        }

        size_t bytes_written = 0;
        esp_err_t err = i2s_channel_write(s_i2s_tx, samples, sizeof(samples),
                                          &bytes_written, portMAX_DELAY);
        if (err != ESP_OK || bytes_written != sizeof(samples)) {
            ESP_LOGE(TAG, "I2S write failed: %s (%u/%u bytes)",
                     esp_err_to_name(err), (unsigned)bytes_written,
                     (unsigned)sizeof(samples));
        }

        if (block_has_beat || block_has_sequence_step) {
            publish_state(snapshot_from_core(&core, block_accent));
        }
    }
}

esp_err_t metronome_app_start(void)
{
    s_command_queue = xQueueCreate(COMMAND_QUEUE_LENGTH,
                                   sizeof(metronome_command_t));
    s_state_mutex = xSemaphoreCreateMutex();
    if (s_command_queue == NULL || s_state_mutex == NULL) {
        return ESP_ERR_NO_MEM;
    }

    drum_samples_init();
    drum_mixer_init(&s_drum_mixer);

    i2s_chan_config_t channel_config =
        I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    channel_config.dma_desc_num = 4;
    channel_config.dma_frame_num = AUDIO_FRAMES_PER_BLOCK;

    esp_err_t err = i2s_new_channel(&channel_config, &s_i2s_tx, NULL);
    if (err != ESP_OK) {
        return err;
    }

    i2s_std_config_t standard_config = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(METRONOME_SAMPLE_RATE_HZ),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
            I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = PIN_SPEAKER_BCLK,
            .ws = PIN_SPEAKER_WS,
            .dout = PIN_SPEAKER_DATA_OUT,
            .din = I2S_GPIO_UNUSED,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv = false,
            },
        },
    };

    err = i2s_channel_init_std_mode(s_i2s_tx, &standard_config);
    if (err != ESP_OK) {
        return err;
    }
    err = i2s_channel_enable(s_i2s_tx);
    if (err != ESP_OK) {
        return err;
    }

    if (xTaskCreate(audio_task, "metronome_audio", 4096, NULL,
                    configMAX_PRIORITIES - 3, NULL) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG, "Continuous I2S started at %d Hz, %d PPQN, default %d BPM",
             METRONOME_SAMPLE_RATE_HZ, METRONOME_PPQN, METRONOME_DEFAULT_BPM);
    return ESP_OK;
}

esp_err_t metronome_app_subscribe(QueueHandle_t state_queue)
{
    if (state_queue == NULL || s_state_mutex == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    metronome_state_t state;
    if (xSemaphoreTake(s_state_mutex, portMAX_DELAY) != pdTRUE) {
        return ESP_FAIL;
    }
    if (s_subscriber_count >= MAX_SUBSCRIBERS) {
        xSemaphoreGive(s_state_mutex);
        return ESP_ERR_NO_MEM;
    }
    s_subscribers[s_subscriber_count++] = state_queue;
    state = s_state;
    xSemaphoreGive(s_state_mutex);
    xQueueOverwrite(state_queue, &state);
    return ESP_OK;
}

metronome_state_t metronome_app_get_state(void)
{
    metronome_state_t state = s_state;
    if (s_state_mutex != NULL &&
        xSemaphoreTake(s_state_mutex, pdMS_TO_TICKS(100)) == pdTRUE) {
        state = s_state;
        xSemaphoreGive(s_state_mutex);
    }
    return state;
}

static bool enqueue_command(const metronome_command_t *command)
{
    if (s_command_queue == NULL || command == NULL) {
        return false;
    }
    if (xQueueSend(s_command_queue, command, 0) != pdTRUE) {
        ESP_LOGW(TAG, "Command queue full; command dropped");
        return false;
    }
    return true;
}

static bool send_command(command_type_t type, int value)
{
    const metronome_command_t command = {.type = type, .value = value};
    return enqueue_command(&command);
}

void metronome_app_set_bpm(int bpm)
{
    (void)send_command(COMMAND_SET_BPM, bpm);
}

void metronome_app_adjust_bpm(int delta)
{
    (void)send_command(COMMAND_ADJUST_BPM, delta);
}

void metronome_app_set_running(bool running)
{
    (void)send_command(COMMAND_SET_RUNNING, running ? 1 : 0);
}

void metronome_app_toggle(void)
{
    (void)send_command(COMMAND_TOGGLE, 0);
}

bool metronome_app_trigger_drum(uint8_t pad_index)
{
    if (pad_index >= DRUM_SAMPLE_COUNT) {
        return false;
    }
    return send_command(COMMAND_TRIGGER_DRUM, pad_index);
}

bool metronome_app_set_pattern_mask(uint8_t pad_index, uint16_t mask)
{
    if (pad_index >= DRUM_SAMPLE_COUNT) {
        return false;
    }
    const int encoded = ((int)pad_index << 16) | mask;
    return send_command(COMMAND_SET_PATTERN_MASK, encoded);
}

bool metronome_app_set_pattern(
    const uint16_t pattern[METRONOME_DRUM_TRACK_COUNT])
{
    if (pattern == NULL) {
        return false;
    }
    TaskHandle_t caller = xTaskGetCurrentTaskHandle();
    if (caller == NULL) {
        return false;
    }
    (void)ulTaskNotifyTake(pdTRUE, 0);
    metronome_command_t command = {
        .type = COMMAND_SET_PATTERN,
        .completion_task = caller,
    };
    memcpy(command.pattern, pattern, sizeof(command.pattern));
    if (!enqueue_command(&command)) {
        return false;
    }
    return ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(100)) > 0U;
}
