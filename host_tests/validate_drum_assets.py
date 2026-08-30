#!/usr/bin/env python3

import hashlib
from pathlib import Path


EXPECTED = {
    "s1_kick.pcm": (43730, "74916dbb384460b6d2fecab5a98dfd3d79bf2c8782ed9ea3ae76bde3bf5371ad"),
    "s2_snare.pcm": (43200, "671cc38dada2efb2df57c502d114d234e128ea20cc1e586976edaaa81c4c6a52"),
    "s3_closed_hihat.pcm": (28800, "5063600d6f3746665da4f98d2cf2b546a36e81190aea5205888ac90b4ae8bad1"),
    "s4_open_hihat.pcm": (31288, "af51b5971a5d28d53110da9d31367d764b6475ab11e5d4f93b6bef32f7cb9c56"),
    "s5_clap.pcm": (15448, "ce7dcfcedb033410992bf29e08b65a3b1c8e42c9cd4f2221b2c92ad42130fbae"),
    "s6_rimshot.pcm": (7726, "4e6fe5f7315acd0febb960b62fbf2a83bc2921808d0500aa9022e3eb3a33d710"),
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
