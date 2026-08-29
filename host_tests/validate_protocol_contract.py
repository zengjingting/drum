#!/usr/bin/env python3
from pathlib import Path


root = Path(__file__).resolve().parents[1]
firmware = (root / "main" / "usb_serial_control.c").read_text()
web = (root / "main" / "web" / "index.html").read_text()

required_firmware_fragments = (
    "#define PROTOCOL_VERSION 2",
    r'\"capabilities\":[\"pattern\",\"trigger\",\"sequencer\"]',
    'send_ack("PATTERN")',
    '"PATTERN %u %u %u %u %u %u %c"',
)
for fragment in required_firmware_fragments:
    assert fragment in firmware, f"missing firmware contract: {fragment}"

required_web_fragments = (
    "const REQUIRED_PROTOCOL_VERSION=2",
    "capabilities.has('pattern')",
    "capabilities.has('trigger')",
    "capabilities.has('sequencer')",
    "`PATTERN ${pattern.join(' ')}`",
    "message.type==='ack'&&message.command==='PATTERN'",
)
for fragment in required_web_fragments:
    assert fragment in web, f"missing web contract: {fragment}"

assert "`MASK ${" not in web, "web must use one atomic PATTERN command"
assert "setConnection('error',message.message)" not in web, (
    "protocol errors must not be promoted to connection failures"
)

print("protocol_contract: v2 handshake, atomic PATTERN, ACK, error split verified")
