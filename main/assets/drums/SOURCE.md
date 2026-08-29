# Board-resident drum PCM snapshot

Five board-resident samples come from the FreePats synthesizer percussion sound
bank, version `2022-07-18`, created by Roberto with Yoshimi and Geonkick and
released under the Creative Commons CC0 1.0 public-domain dedication.

- Project page: <https://freepats.zenvoid.org/Percussion/electric-percussion.html>
- Source archive: <https://freepats.zenvoid.org/Percussion/SynthesizerPercussion/SynthesizerPercussion-SFZ-20220718.7z>
- Source archive SHA-256: `dbb2e5bb8268022fffa6dcc3d11a93368316038bf3ae81a965c58e9d490ed23b`
- License snapshot: `LICENSE-CC0.txt`, copied byte-for-byte from the archive

The S6 rimshot comes from Boochi44's Free Drum Samples repository. Its README
states that all samples are CC0 1.0 while also asking redistributors to verify
licensing. This repository therefore pins the exact upstream commit and keeps
the complete README containing both statements.

- Project: <https://github.com/Boochi44/free-drum-samples>
- Pinned commit: `77ba31428a079dd8f17c8e144c1e649ea0a198b3`
- Source WAV: `drum-samples/01-hard-trap/percs/perc-rimshot.wav`
- Source WAV Git blob: `c5a54c77a27ed9776b74890b4ffe1016b1202e13`
- Source WAV SHA-256: `20d5cd385c0f8c3a24bbfe78c2e2747776841ede6185bc0fe93f97f0b455b89c`
- Licensing statement snapshot: `SOURCE-FREE-DRUM-SAMPLES-README.md`
- Snapshot Git blob: `b9c52e91499b7f1cdd0fb3ab7a13debfffcd66b3`
- Snapshot SHA-256: `054e540e5b7186bea1f99bc9718899bbfa1b7f3122b7802efff8a63f4aa51152`

## Pad mapping

| Pad | Board PCM | Original WAV | Duration | Output SHA-256 |
| --- | --- | --- | ---: | --- |
| S1 | `s1_kick.pcm` | `Kick04.wav` | 226 ms | `2cc07fe66c70cb8522fb44500ce026baa94e8574d934db0c399158669262b28f` |
| S2 | `s2_snare.pcm` | `Snare09.wav` | 222 ms | `c4928e4fcaeb0cd3d040a90102a42be78738adc782f01665847de5b0e45341a0` |
| S3 | `s3_closed_hihat.pcm` | `ClosedHiHat02-01.wav` | 326 ms | `3bf08a2f5d0786ea11f54f1dc738302bf5cfd6da5d10183dad8016c2c69f0a5f` |
| S4 | `s4_open_hihat.pcm` | `OpenHiHat02-01.wav` | 406 ms | `8deb049183fdeb281fc6bab4894ce188b53d0d48d55284aa476599d2881c2c8b` |
| S5 | `s5_clap.pcm` | FreePats `Clap01.wav` | 853 ms | `c97cc58cbdb17af8a9399b0dd1bfb23516601de3cb9a0ff1304483ae8c3cddb1` |
| S6 | `s6_rimshot.pcm` | Free Drum Samples `perc-rimshot.wav` | 250 ms | `3164c9e72d4116803b2095183cd824e78df5d5de9dfd20f63efedb07f5843852` |

## Board format

Every file is headerless `48,000 Hz`, mono, signed `16-bit little-endian` PCM.
The FreePats WAV files are already 48 kHz mono, so their conversion changes
only the sample representation and removes the WAV container. The S6 source is
44.1 kHz mono PCM and is resampled once to 48 kHz at build-asset preparation
time. The firmware has no runtime decoder or resampler.

Reproduction command for each file:

```sh
ffmpeg -i SOURCE.wav -f s16le -acodec pcm_s16le -ar 48000 -ac 1 OUTPUT.pcm
```
