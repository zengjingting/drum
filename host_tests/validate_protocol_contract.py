#!/usr/bin/env python3
from pathlib import Path


root = Path(__file__).resolve().parents[1]
firmware = (root / "main" / "usb_serial_control.c").read_text()
web = (root / "main" / "web" / "app.js").read_text()

required_firmware_fragments = (
    "#define PROTOCOL_VERSION 3",
    r'\"hardwareCaptureButton\",\"revisionCommit\"',
    'send_ack("PATTERN")',
    '"PATTERN %u %u %u %u %u %u %c"',
    '"COMMIT %" SCNu32 " %u %u %u %u %u %u %u %c"',
    'send_commit_ack(metronome_app_get_state())',
    'strcmp(command, "CAPTURE READY 1") == 0',
    'strcmp(command, "ABORT") == 0',
    'strcmp(command, "RECORD START") == 0',
    'strcmp(command, "RECORD STOP") == 0',
    'Recording requires CAPTURE READY 1',
    'Recording is unavailable during playback',
    'Recording is busy in capture state %s',
    r'\"type\":\"pad\"',
    'metronome_app_subscribe_pad_events(s_pad_event_queue)',
)
for fragment in required_firmware_fragments:
    assert fragment in firmware, f"missing firmware contract: {fragment}"

required_web_fragments = (
    "const REQUIRED_PROTOCOL_VERSION = 3",
    "capabilities.has('pattern')",
    "capabilities.has('trigger')",
    "capabilities.has('sequencer')",
    "capabilities.has('padEvents')",
    "capabilities.has('hardwareCaptureButton')",
    "capabilities.has('revisionCommit')",
    "`COMMIT ${snapshot.revision} ${snapshot.bpm} ${snapshot.masks.join(' ')}`",
    "message.type === 'ack' && message.command === 'COMMIT'",
)
for fragment in required_web_fragments:
    assert fragment in web, f"missing web contract: {fragment}"

assert "`MASK ${" not in web, "web must use an atomic pattern command"
assert "setConnection('error',message.message)" not in web, (
    "protocol errors must not be promoted to connection failures"
)

print("protocol_contract: v3 revision COMMIT and hardware capture controls verified")
