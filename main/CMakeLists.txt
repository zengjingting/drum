idf_component_register(
    SRCS
        "main.c"
        "board_power.c"
        "metronome_app.c"
        "input_controls.c"
        "led_display.c"
        "usb_serial_control.c"
    INCLUDE_DIRS "."
    REQUIRES
        esp_driver_gpio
        esp_driver_i2s
        esp_driver_usb_serial_jtag
        led_strip
        metronome_core
)
