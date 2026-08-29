# FreePats synthesizer percussion PCM snapshot

These six board-resident samples come from the FreePats synthesizer percussion
sound bank, version `2022-07-18`, created by Roberto with Yoshimi and Geonkick
and released under the Creative Commons CC0 1.0 public-domain dedication.

- Project page: <https://freepats.zenvoid.org/Percussion/electric-percussion.html>
- Source archive: <https://freepats.zenvoid.org/Percussion/SynthesizerPercussion/SynthesizerPercussion-SFZ-20220718.7z>
- Source archive SHA-256: `dbb2e5bb8268022fffa6dcc3d11a93368316038bf3ae81a965c58e9d490ed23b`
- License snapshot: `LICENSE-CC0.txt`, copied byte-for-byte from the archive

## Pad mapping

| Pad | Board PCM | Original WAV | Duration | Output SHA-256 |
| --- | --- | --- | ---: | --- |
| S1 | `s1_kick.pcm` | `Kick04.wav` | 226 ms | `2cc07fe66c70cb8522fb44500ce026baa94e8574d934db0c399158669262b28f` |
| S2 | `s2_snare.pcm` | `Snare09.wav` | 222 ms | `c4928e4fcaeb0cd3d040a90102a42be78738adc782f01665847de5b0e45341a0` |
| S3 | `s3_closed_hihat.pcm` | `ClosedHiHat01-01.wav` | 181 ms | `c92fd18054f276a55b4bb8bcc3d56dd38f7ce9f24bf8dff708bd67414d4fde9f` |
| S4 | `s4_open_hihat.pcm` | `OpenHiHat02-01.wav` | 406 ms | `8deb049183fdeb281fc6bab4894ce188b53d0d48d55284aa476599d2881c2c8b` |
| S5 | `s5_low_tom.pcm` | `LowTom02-01.wav` | 535 ms | `b72a3e241bcc2fc58c5eb624b094b2ef4177f9ef4311ae785039622a222c8707` |
| S6 | `s6_cymbal.pcm` | `Cymbal02.wav` | 1858 ms | `bb395ece39506e497b5232a5fcaf68826d6aac3ecaea9670434afca7332015af` |

## Board format

Every file is headerless `48,000 Hz`, mono, signed `16-bit little-endian` PCM.
The original FreePats WAV files are already 48 kHz mono, so conversion changes
only the sample representation and removes the WAV container; there is no
resampling or runtime decoder.

Reproduction command for each file:

```sh
ffmpeg -i SOURCE.wav -f s16le -acodec pcm_s16le -ar 48000 -ac 1 OUTPUT.pcm
```
