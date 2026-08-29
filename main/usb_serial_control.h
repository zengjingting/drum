#pragma once

#include "esp_err.h"

/*
 * Starts the USB Serial/JTAG command channel used by the local Web Serial UI.
 * The hardware metronome remains fully functional if this optional channel is
 * unavailable or no browser is connected.
 */
esp_err_t usb_serial_control_start(void);
