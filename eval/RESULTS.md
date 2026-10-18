# AAC encoder evaluation for audiblez (macOS, 2026-10-18)

Reproduce: `python -I eval/encoder_eval.py eval/corpus <out_dir> <ffmpeg-with-libfdk_aac>`
(eval venv: numpy soundfile scipy pesq pystoi). Raw rows: `results.csv`.

**Setup**
- **System ffmpeg:** Homebrew 8.1_1, with `aac`, `aac_at` and `libopus`.
- **FDK ffmpeg:** a minimal 8.1 build configured with `--enable-nonfree --enable-libfdk-aac`, linked against Homebrew `fdk-aac` 2.0.3.
- **Corpus:** 6 Kokoro WAVs (24 kHz mono, about 2.7 min in total). It has 5 voices (af_sky, af_heart, am_michael, im_nicola, zf_xiaobei) in English, Italian and Chinese.
- **Scoring:** each output is decoded by the system ffmpeg, aligned to the source by cross-correlation, resampled to 16 kHz, then scored with PESQ-WB and STOI.

Bitrate is weighted by duration across the corpus and includes MP4 overhead. "8–12 kHz LSD" is the RMS log-spectral distance from the source in the band PESQ-WB/STOI can't see (speech-active frames; lower is better).

| cand | pipeline | PESQ-WB mean | PESQ-WB min | STOI mean | 8–12 kHz LSD dB | kb/s | start lag (samples) |
|---|---|---|---|---|---|---|---|
| current | libfdk_aac 192k → native aac 64k (upstream HEAD 788a6a8) | 4.026 | 3.785 | 0.9977 | 4.94 | 70.0 | 0 |
| native64 | native aac 64k | 3.969 | 3.765 | 0.9974 | 4.98 | 70.3 | 0 |
| native80 | native aac 80k | 4.330 | 4.209 | 0.9994 | 3.39 | 87.1 | 0 |
| native96 | native aac 96k | 4.465 | 4.317 | 0.9999 | **2.67** | 96.9 | 0 |
| at48 | aac_at cvbr 48k | 4.255 | 4.125 | 0.9985 | 5.95 | 51.6 | 0 |
| **at64** | aac_at cvbr 64k | **4.448** | 4.350 | 0.9995 | 3.92 | 67.2 | 0 |
| fdk48 | libfdk_aac 48k | 4.286 | 4.084 | 0.9992 | 7.13 | 49.2 | 0 |
| **fdk64** | libfdk_aac 64k | **4.444** | 4.359 | 0.9989 | 4.76 | 65.3 | 0 |
| fdk_he32 | libfdk_aac HE-AAC 32k | 3.612 | 3.325 | 0.9971 | 12.10 | 32.9 | 1 |
| at_he32/48 | aac_at HE-AAC (`-profile:a 4`) | 3.313 | 2.999 | 0.9951 | 8.69 | 33.0 | **3074** |
| opus32 | libopus 32k in MP4 | 4.465 | 4.413 | 0.9945 | 6.25 | 31.0 | 78 |

## Findings
1. **The double encode in upstream HEAD wastes the FDK pass.** `current` scores 4.03, only +0.06 above native aac at 64k (3.97) and far below FDK 64k used directly (4.44), because the final 64k native encode limits quality. Separately, the FDK step fails outright on stock ffmpeg.
2. **At 64k, `aac_at` and `libfdk_aac` tie on PESQ-WB** (4.448 vs 4.444; the minimums are reversed), and **`aac_at` is closer to the source at 8–12 kHz** (3.92 vs 4.76 dB). Native `aac` needs **96k** to match on PESQ. At that rate it is the closest of all at 8–12 kHz (2.67 dB), but its files are ~45% larger.
3. **HE-AAC is disqualified for this input.** It scores lowest at 24 kHz mono speech.
   - aac_at caps HE-AAC at 32k, so the 32k and 48k runs are fp64-identical (config collapse, caught by the gate).
   - aac_at HE output starts **3074 samples (128 ms) late**: the delay isn't in the edit list, so every chapter mark would shift.
4. **Opus has the best PESQ per bit but is unusable here.** Apple Books/iOS don't play Opus in MP4 (see RESEARCH.md §4), and its STOI is the lowest of the non-HE candidates.
5. **The extra duration is tail padding, not drift.** All AAC-LC outputs start sample-aligned and run 29–69 ms long at the end. With a single encode of the joined chapters, that padding comes after the last chapter mark.

6. **A listed encoder may not start.** Inside codex's macOS seatbelt sandbox, `aac_at` initialises with `AudioToolbox init error: 'fmt?'` and writes no packets. The same command outside the sandbox works (51,859 vs 0 bytes, reproduced with `codex sandbox ffmpeg … -c:a aac_at -f adts -`). The encoder itself is fine; the sandbox blocks the system audio services it needs. The code therefore can't trust `ffmpeg -encoders` and has to fall back at encode time.

## Decision (implemented in `audiblez/core.py`)
- **One encode:** the chapter WAVs go straight to the `.m4b` ffmpeg call through the concat demuxer. There is no intermediate lossy file, and no 4 GB WAV limit to worry about.
- **Encoder choice:** `AAC_ENCODERS` is tried in order at encode time. An encoder counts as having worked only if ffmpeg exits 0 and the output's audio stream is at least 99% as long as the summed chapter WAVs. Container duration or packet count alone isn't enough: chapter metadata gives a duration, and aac_at emits priming packets even for empty input.
  1. `aac_at` cvbr 64k (macOS)
  2. `libfdk_aac` 64k (non-free builds)
  3. native `aac` 96k (everything else, including CI)
- All three land at PESQ-WB ≈ 4.45. FDK comes before native 96k because it is ~1/3 smaller at equal PESQ.
- **Failure handling:** if every encoder fails, `create_m4b` raises `RuntimeError`. Output is written to `<book>.tmp.m4b` and renamed only on success, so a failed run can't clobber an existing `.m4b`.
- **Concat list:** uses absolute paths, with `'` escaped for ffconcat, and is removed in `finally`.

## Caveats
- PESQ-WB/STOI are objective speech metrics. PESQ-WB is band-limited to 8 kHz, so it can't see the 8–12 kHz band of 24 kHz audio. No listening test was done; the per-candidate `.m4a` files are kept in the out dir for ABX.
- Bitrates include one MP4 container per corpus file, about +1.0 kb/s compared with a single-container audiobook (codex packet accounting). The ranking is unaffected.
- The corpus is small (6 files, ~2.7 min); rankings within ±0.02 PESQ are ties.
- The FDK numbers come from a minimal ffmpeg build. The encoder wrapper and the library are the same as in a full build.
