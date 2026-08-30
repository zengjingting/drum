# Board-resident drum PCM snapshot

The S1 kick comes from CM Music's Sample Drum Kit on ccMixter. The source page
labels the archive and its individual WAV files as CC0.

- Project page: <https://ccmixter.org/files/carbonmonoxidemusic/23425>
- Source archive: <https://ccmixter.org/content/CarbonMonoxideMusic/CarbonMonoxideMusic_-_Drum_Kit_Samples.zip>
- Source archive SHA-256: `80a37d6f3ed109a6c2d7b4dc40665604c6b0d7e7e28c6198d66739da8184c728`
- Source WAV: `Sample Drum Kit/Kick.wav`
- Source WAV SHA-256: `9faec713205af418607c1b06b232e271ecc94773a548837afc105fdfe8a2b8b9`
- CC0 legal-code snapshot: `LICENSE-CC0.txt`

The S2 snare and S7 closed hi-hat come from Versilian Studios and Karoryfer
Samples' Virtuosity Drums, a real contemporary-jazz drum kit released under
CC0 1.0. The selected snare is a medium-high-velocity center hit from the mid
microphone, while the selected hi-hat is a medium-velocity closed hit from the
darker lo-fi microphone.

- Project: <https://github.com/sfzinstruments/virtuosity_drums>
- Pinned commit: `9f04cf9a734527edfbb0a4eee1f674e45bbf71bc`
- License snapshot: `SOURCE-VIRTUOSITY-LICENSE.txt`
- License Git blob: `0e259d42c996742e9e3cba14c677129b2c1b6311`
- License snapshot SHA-256: `a2010f343487d3f7618affe54f789f5487602331c0a8d03f49e9a7c547cf0499`

| Pad | Source FLAC | Git blob | Source SHA-256 |
| --- | --- | --- | --- |
| S2 | `Samples/mid/snare/mid_snare_center_vl28.flac` | `6b629c831c277b896bd512db61d0885cb4988dcc` | `f8df18766689f44fa92ca17980555fac7e462b2f9c7afd56ef703b24bef36e03` |
| S7 | `Samples/lofi/hh/lofi_hh_closed_vl2_rr1.flac` | `e02a237af463232bed0e7a25b443a99ef64cbc22` | `d9424ee6b77c9c67f67f14a50fa611bf257f1b3f0380b0e06bb24e23311728e2` |

The S4 open hi-hat, S5 clap, and S6 rim are derived from the speaker-tuned TR-707
firmware RAW files in
Zhaohan-Wang's EasyInput Beatbox repository. That repository traces the sample
to `fluid-music/open-drums`; the pinned upstream `README.txt` states that all 15
TR-707 samples are public domain. A text snapshot is retained as
`SOURCE-TR707-README.txt`.

- EasyInput Beatbox project: <https://github.com/Zhaohan-Wang/easyinput-beatbox>
- Pinned EasyInput Beatbox commit: `9a0801a784bc3f97d15aa9f042dace9e83a99078`
- Upstream source: <https://github.com/fluid-music/open-drums/tree/main/tr-707/TR707WAV>
- Pinned upstream commit: `475cc3314fe06f6d1af02e9790ad9707c1f2b26b`

| Pad | Input firmware RAW | RAW SHA-256 | Original WAV mapping | WAV SHA-256 |
| --- | --- | --- | --- | --- |
| S4 | `firmware/main/audio/samples/hihat_open.raw` | `34ea67af7b176385b50e0db2c18082458002d3a68925b9a669ca518a80e98b1b` | `HhO.wav` -> `assets/samples/tr707/hihat_open.wav` | `dac451389b3466494efa720f383db0546e033eb5185a7e53cd84d3d85fc10f5e` |
| S5 | `firmware/main/audio/samples/clap.raw` | `4e6e16fa3e256dbbfbf590b81ecfa373f6f4a500d550b03236f60f7315a60c77` | `HandClap.wav` -> `assets/samples/tr707/clap.wav` | `8ed6c7acfd138d4ec8c526b09e0493cd7279e65df83e5f80e1d5ff6b4831eb26` |
| S6 | `firmware/main/audio/samples/rim.raw` | `ada63a27dedc788f03e1dd089c035c745e11c11248b0a667c5953d4842e66005` | `RimShot.wav` -> `assets/samples/tr707/rim.wav` | `7098761c605af6bdb0f9e289ad1d3632c7990df9dccb57ea40fa8aafa6535e88` |

## Pad mapping

| Pad | Board PCM | Original WAV | Duration | Output SHA-256 |
| --- | --- | --- | ---: | --- |
| S1 | `s1_kick.pcm` | ccMixter `Sample Drum Kit/Kick.wav` (gain -6 dB) | 456 ms | `74916dbb384460b6d2fecab5a98dfd3d79bf2c8782ed9ea3ae76bde3bf5371ad` |
| S2 | `s2_snare.pcm` | Virtuosity Drums `mid_snare_center_vl28.flac` | 450 ms | `671cc38dada2efb2df57c502d114d234e128ea20cc1e586976edaaa81c4c6a52` |
| S7 | `s3_closed_hihat.pcm` | Virtuosity Drums `lofi_hh_closed_vl2_rr1.flac` | 300 ms | `5063600d6f3746665da4f98d2cf2b546a36e81190aea5205888ac90b4ae8bad1` |
| S4 | `s4_open_hihat.pcm` | EasyInput Beatbox speaker-tuned TR-707 `hihat_open.raw` | 326 ms | `af51b5971a5d28d53110da9d31367d764b6475ab11e5d4f93b6bef32f7cb9c56` |
| S5 | `s5_clap.pcm` | EasyInput Beatbox speaker-tuned TR-707 `clap.raw` | 161 ms | `ce7dcfcedb033410992bf29e08b65a3b1c8e42c9cd4f2221b2c92ad42130fbae` |
| S6 | `s6_rimshot.pcm` | EasyInput Beatbox speaker-tuned TR-707 `rim.raw` | 80 ms | `4e6fe5f7315acd0febb960b62fbf2a83bc2921808d0500aa9022e3eb3a33d710` |

## Board format

Every file is headerless `48,000 Hz`, mono, signed `16-bit little-endian` PCM.
The ccMixter S1 source is 44.1 kHz, stereo, signed 16-bit WAV. It is downmixed
to mono, resampled once to 48 kHz, and reduced 6 dB to reproduce the accepted
computer audition at unity Q15 runtime gain. The Virtuosity source files are
48 kHz, 24-bit FLAC. S2 is downmixed from stereo to mono, trimmed to
450 ms, and faded over the last 50 ms. S7 is mono, raised 18 dB before 16-bit
quantization, trimmed to 300 ms, and faded over the last 50 ms. Its resulting
board peak is still about 16 dB below the previous closed-hi-hat path. S6 is
resampled once from 44.1 kHz to 48 kHz at build-asset preparation time.

S4, S5, and S6 reproduce the EasyInput Beatbox full-velocity single-instrument
outputs before resampling: multiply each 32 kHz signed-16-bit RAW by its
instrument level (40% open hi-hat, 88% clap, 82% rim), then apply that firmware's
integer limiter (`13000` linear threshold, `5000` headroom and `7000` knee
denominator). The resulting signals are resampled by
`scipy.signal.resample_poly` 3:2 with SciPy 1.17.1, rounded to the nearest
integer and clipped to signed 16-bit. S2 uses Q15 gain `23198` (-3.0 dB) to
match the previous board peak without preserving the TR-707 timbre. S7 uses
unity Q15 gain because its lower level is prepared directly in the PCM. S4
uses Q15 gain `19519` (-4.5 dB) on top of its pre-rendered 40% level to match
the natural-kit board balance. After subsequent board auditions, S5 uses Q15
gain `9782` (-10.5 dB) to balance its sustained clap energy with S2/S7 on the
small speaker. S6 uses Q15 gain `23198`
(-3.0 dB) to avoid a perceived level jump from its longer midrange body. This project's
24576-threshold soft limiter leaves each single hit unchanged. The firmware has
no runtime decoder or resampler.

Generic reproduction command for the direct WAV conversions:

```sh
ffmpeg -i SOURCE.wav -f s16le -acodec pcm_s16le -ar 48000 -ac 1 OUTPUT.pcm
```
