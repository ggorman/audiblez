# AAC encoder research notes (2026-10-18)

trac.ffmpeg.org and Hydrogenaudio blocked direct fetches (Anubis/403). Statements attributed to them come from search snippets and archived revisions. Points marked *local* were checked on Homebrew ffmpeg 8.1 on this Mac.

## 1. Quality ranking at 32–96 kb/s
- **FFmpeg wiki AAC-LC ranking:** "aac_at ≥ libfdk_aac > native aac". Older revisions put fdk first "except on macOS". https://trac.ffmpeg.org/wiki/Encode/AAC?version=69
- **Native aac history:**
  - Kamedo2's 96k test (2015) placed it below LAME and Nero. https://ffmpeg.org/pipermail/ffmpeg-trac/2015-July/028981.html
  - In 2020 FFmpeg dropped its doc claim of parity with fdk at 128k. https://ffmpeg.org/pipermail/ffmpeg-cvslog/2020-May/122054.html
- **Forum consensus:** QAAC/Apple > FDK > … > FFmpeg AAC. https://forum.doom9.org/archive/index.php/t-186465.html
- **No public test covers 24 kHz mono speech.** That is why the local evaluation (RESULTS.md) was needed.

## 2. HE-AAC
- **Which encoders have it:**
  - libfdk_aac: `aac_he` and `aac_he_v2`.
  - Native aac: none (`aac_low`, `mpeg2_aac_low`, `aac_ltp` only). https://ffmpeg.org/ffmpeg-codecs.html
- **aac_at quirks:**
  - It needs numeric profiles (`-profile:a 4` = HE, `28` = HEv2); *local*: `aac_he` is rejected.
  - At 24 kHz mono, HE-AAC is capped at 32k (*local*: "Bitrate 48000 not allowed").
  - Source: https://raw.githubusercontent.com/FFmpeg/FFmpeg/master/libavcodec/audiotoolboxenc.c
- **SBR at 24 kHz input:** the core runs at 12 kHz and SBR rebuilds 6–12 kHz.
- **Apple's guidance:** HE-AAC pays off at 32–80 kb/s stereo 44.1 kHz. https://developer.apple.com/library/content/technotes/tn2236/_index.html

## 3. aac_at options
- **`-aac_at_mode`:** `auto`, `cbr`, `abr`, `cvbr` or `vbr`.
- **`-aac_at_quality`:** 0–2, where 0 is the best quality and the default.
- **`-q:a`:** 0–14, where lower is better.
- **Sample formats:** s16 or u8 input only.
- **Platform:** macOS only.
- **Padding:** trailing padding isn't signalled (*local*: about +27–69 ms at the end).

## 4. M4B player compatibility
- **AAC-LC:** plays everywhere (Apple Books, iOS, Android, ExoPlayer, VLC).
- **HE-AAC:** Android 4.1+ and Apple support it; an LC-only decoder plays the core alone, at reduced quality.
- **Opus in MP4:** not playable on Apple (Opus works only in .caf). https://developer.apple.com/forums/thread/722399 — Android's extractor list names Ogg/WebM for Opus. https://developer.android.com/media/platform/supported-formats

## 5. Licensing
- libfdk_aac's licence is GPL-incompatible, and a build with it needs `--enable-nonfree` and cannot be redistributed.
- Homebrew core has no fdk build, so it needs a third-party tap.
- Debian ships it in non-free; Fedora ships only an LC-only `fdk-aac-free`. https://en.wikipedia.org/wiki/Fraunhofer_FDK_AAC
- Calling the user's own ffmpeg through subprocess doesn't affect audiblez's MIT licence. **The real problem is availability:** fdk can be used when present but never required.

## 6. Encoder delay and chapter timing
- **How players handle delay:** they trim priming through the MP4 edit list (Apple assumes 2112 samples). https://developer.apple.com/documentation/quicktime-file-format/appendix_g_audio_priming_handling_encoder_delay_in_aac.md
- **What ffmpeg does:** it writes the encoder's own delay and often drops the trailing padding. https://trac.ffmpeg.org/ticket/7185
- **Implication:** encode the joined chapters **once**, so any offset is a constant rather than adding up per chapter. Chapter times come from the PCM durations (`create_index_file`).
