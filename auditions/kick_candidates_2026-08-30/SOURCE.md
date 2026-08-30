# Kick audition candidates — 2026-08-30

These files are listening candidates only. They are not referenced by the
firmware build.

All three audition files were converted to 48 kHz, mono, signed 16-bit PCM and
attenuated by 6 dB. No EQ, compression, pitch shifting, or envelope shaping was
applied.

## 01 — ccMixter standard kick

- Output: `01-ccmixter-standard-kick.wav`
- Original: `Sample Drum Kit/Kick.wav`
- Source: https://ccmixter.org/files/carbonmonoxidemusic/23425
- License shown by source: CC0
- Role: conventional acoustic/rock kick
- Dominant spectral peak in the screening window: about 194 Hz
- SHA-256: `45636b08783e0bcf6cb00268fdecc2e467a13496291e8fa29ce294dbcf2fea4b`

## 02 — FreePats darbuka doom used as a kick role

- Output: `02-freepats-darbuka-doom-kick-role.wav`
- Original: `samples/Darbuka/doom_01_02.wav`
- Source: https://freepats.zenvoid.org/Percussion/world-and-rare-percussion.html
- License shown by source: CC0
- Role: short, rounded low-frequency hit; not labeled as a conventional kick
- Dominant spectral peak in the screening window: about 133 Hz
- SHA-256: `18821ce35a2b686f400e2a13c2e713b5b1e5ad05581d8b3d888b9744da2c4d92`

## 03 — FreePats cajon bass used as a kick role

- Output: `03-freepats-cajon-bass-kick-role.wav`
- Original: `samples/CajonFlamenco/212.wav`
- Source: https://freepats.zenvoid.org/Percussion/world-and-rare-percussion.html
- License shown by source: CC0
- Role: dry wooden bass hit; not labeled as a conventional kick
- Dominant spectral peak in the screening window: about 144 Hz
- SHA-256: `fe2884bcd2bcd9eec2126a563e6d9ec3e8c568016aa792daa2cf087d24ee4f66`

Frequency-domain screening is only a shortlist signal. The final choice still
requires a firmware build, flash, and listening test on the physical board.
