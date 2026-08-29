#pragma once

#include <stdbool.h>
#include "esp_err.h"

esp_err_t board_shared_power_cold_start(void);
esp_err_t board_status_led_init(void);
void board_status_led_set(bool on);
