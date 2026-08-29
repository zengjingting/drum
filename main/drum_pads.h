#pragma once

#include "esp_err.h"

/* Starts low-active, independently debounced S1-S6 drum pad scanning. */
esp_err_t drum_pads_start(void);
