#!/bin/sh
set -eu

cc -std=c11 -Wall -Wextra -Werror \
  -Icomponents/metronome_core/include \
  components/metronome_core/metronome_core.c \
  host_tests/test_metronome_core.c \
  -o host_tests/metronome_core_test

./host_tests/metronome_core_test

cc -std=c11 -Wall -Wextra -Werror \
  -Imain \
  main/drum_mixer.c \
  host_tests/test_drum_mixer.c \
  -o host_tests/drum_mixer_test

./host_tests/drum_mixer_test

python3 host_tests/validate_drum_assets.py
python3 host_tests/validate_protocol_contract.py
