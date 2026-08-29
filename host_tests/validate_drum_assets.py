#!/usr/bin/env python3

import hashlib
from pathlib import Path


EXPECTED = {
    "s1_kick.pcm": (21716, "2cc07fe66c70cb8522fb44500ce026baa94e8574d934db0c399158669262b28f"),
    "s2_snare.pcm": (21308, "c4928e4fcaeb0cd3d040a90102a42be78738adc782f01665847de5b0e45341a0"),
    "s3_closed_hihat.pcm": (17412, "c92fd18054f276a55b4bb8bcc3d56dd38f7ce9f24bf8dff708bd67414d4fde9f"),
    "s4_open_hihat.pcm": (39010, "8deb049183fdeb281fc6bab4894ce188b53d0d48d55284aa476599d2881c2c8b"),
    "s5_low_tom.pcm": (51340, "b72a3e241bcc2fc58c5eb624b094b2ef4177f9ef4311ae785039622a222c8707"),
    "s6_cymbal.pcm": (178330, "bb395ece39506e497b5232a5fcaf68826d6aac3ecaea9670434afca7332015af"),
}


def main() -> None:
    asset_dir = Path(__file__).resolve().parents[1] / "main" / "assets" / "drums"
    actual_names = {path.name for path in asset_dir.glob("*.pcm")}
    assert actual_names == set(EXPECTED), (actual_names, set(EXPECTED))

    total_bytes = 0
    for name, (expected_size, expected_hash) in EXPECTED.items():
        data = (asset_dir / name).read_bytes()
        assert len(data) == expected_size, (name, len(data), expected_size)
        assert len(data) % 2 == 0, name
        digest = hashlib.sha256(data).hexdigest()
        assert digest == expected_hash, (name, digest, expected_hash)
        total_bytes += len(data)

    print(f"drum_assets: 6 PCM files verified ({total_bytes} bytes)")


if __name__ == "__main__":
    main()
