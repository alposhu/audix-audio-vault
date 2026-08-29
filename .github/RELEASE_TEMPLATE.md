## Downloads

| File | Download | Unpacked | What you get |
|---|---|---|---|
| `audix-lite-*-win64.zip` | ~74 MB | ~174 MB | Everything except the in-app YouTube browser. Paste links into the **Get** tab. |
| `audix-*-win64.zip` | ~200 MB | ~529 MB | Adds the embedded browser, so you can search YouTube inside the app and stay signed in for age-restricted content. |

Unzip anywhere and run `audix.exe`. The folder contents must stay together.

**First launch takes about 15 seconds** while audix downloads FFmpeg into
`~/.audix/bin`. Every launch after that is about a second.

Windows SmartScreen will warn because the build is unsigned — **More info → Run
anyway**. Signing requires a code-signing certificate.

## What it does

Pulls audio out of YouTube and finishes it into library files: converted, trimmed,
leveled, tagged, and split.

- 10 formats — MP3, AAC, M4A, Opus, OGG, WMA, FLAC, WAV, ALAC, AIFF
- **Chapter splitting** — turns a long mix or full-album upload into individually
  numbered, tagged tracks, using the video's chapter markers or the timestamps in
  its description
- **Sound editor** — trim, cut, fades, gain, 3-band EQ, speed and pitch, reverse,
  with full undo. Nothing is destructive; your original download is never modified.
- **Real-time preview** — hear an effect while the audio plays, with an A/B bypass
  to compare against the original
- **EBU R128 loudness normalization** — two-pass, to −14 / −16 / −23 LUFS
- Parallel download queue with progress, speed, ETA, and cancel

The waveform is drawn from a multi-resolution peak pyramid, so scrolling a
three-hour file costs the same as a three-minute one (measured: 7.4 ms per repaint
at three hours, versus 6.6 ms at three minutes).

## Requirements

Windows 10 or 11, 64-bit. No Python, no manual FFmpeg install.

## Note

Use this for content you own or are licensed to download. Respect YouTube's Terms
of Service and your local law.
