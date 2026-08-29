#!/bin/sh
set -eu

cc -std=c11 -Wall -Wextra -Werror \
  -Icomponents/metronome_core/include \
  components/metronome_core/metronome_core.c \
  host_tests/test_metronome_core.c \
  -o host_tests/metronome_core_test

./host_tests/metronome_core_test
