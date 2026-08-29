#!/usr/bin/env python3

import hashlib
from pathlib import Path


EXPECTED = {
    "s1_kick.pcm": (21716, "2cc07fe66c70cb8522fb44500ce026baa94e8574d934db0c399158669262b28f"),
    "s2_snare.pcm": (21308, "c4928e4fcaeb0cd3d040a90102a42be78738adc782f01665847de5b0e45341a0"),
    "s3_closed_hihat.pcm": (31312, "3bf08a2f5d0786ea11f54f1dc738302bf5cfd6da5d10183dad8016c2c69f0a5f"),
    "s4_open_hihat.pcm": (39010, "8deb049183fdeb281fc6bab4894ce188b53d0d48d55284aa476599d2881c2c8b"),
    "s5_clap.pcm": (81920, "c97cc58cbdb17af8a9399b0dd1bfb23516601de3cb9a0ff1304483ae8c3cddb1"),
    "s6_rimshot.pcm": (24004, "3164c9e72d4116803b2095183cd824e78df5d5de9dfd20f63efedb07f5843852"),
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
