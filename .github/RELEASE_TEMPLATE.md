## What's new in 2.0

A new look and a new way of working. Your settings carry over.

**One link, one track.** A video opened from a YouTube Mix or playlist used to queue
the whole list, up to hundreds of tracks, most often when the link came from the
built-in browser. A link that names a video now gets that video, however you copied
it. The Mix or playlist is still there as a separate choice when you want it.

**Queue: choose before anything starts.** Every link lands as a row with a tick box,
and playlists are grouped so you can tick them as a whole. Press **Download selected**
or **Download all** when you are ready. You can paste several links at once or drop
them on the window. The list survives a restart, and tracks you already have arrive
unticked.

**Downloads: see every item.** Each one shows its stage, size, speed, and time left.
Pause, resume, reorder, cancel, or retry any of them, and run up to 16 at once. Click
a row for the full story, and anything that finishes while you are elsewhere stays
lit until you have seen it. Finished items are still listed after a restart.

**Browse: download from where you are.** A bar under the page always names the video
on screen and offers Download and Add to Queue. Point at any thumbnail for the same
two buttons, or right-click a video link.

**A whole new interface.** A dark bronze hi-fi receiver, with a lit tuning dial as the
navigation. Long lists stay smooth, and notes that used to stop you with a dialog are
now small messages in the corner.

**If you are upgrading:** Quick Convert is now part of the Queue, Alt+1 to Alt+5 switch
pages, and Settings save themselves.

## Downloads

| File | Download | Unpacked | Run | What you get |
|---|---|---|---|---|
| `audix-lite-*-win64.zip` | ~75 MB | ~178 MB | `audix-lite.exe` | Everything except the in-app YouTube browser. Paste links into the **Queue**. |
| `audix-*-win64.zip` | ~220 MB | ~540 MB | `audix.exe` | Adds the embedded browser, so you can search YouTube inside the app, download from any page, and stay signed in for age-restricted content. |

Unzip anywhere and run the executable. The folder contents must stay together.

Both are the same application; the only difference is the embedded browser. If
you are unsure, take **lite** — it is a quarter of the size and you can still
paste any YouTube link into it.

`SHA256SUMS.txt` lists the checksum of each archive, so you can confirm your
download arrived intact:

```powershell
Get-FileHash .\audix-*-win64.zip -Algorithm SHA256
```

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
- **Queue and Downloads** — choose what to take, then watch every item land

The waveform is drawn from a multi-resolution peak pyramid, so scrolling a
three-hour file costs the same as a three-minute one (measured: 7.4 ms per repaint
at three hours, versus 6.6 ms at three minutes).

## Requirements

Windows 10 or 11, 64-bit. No Python, no manual FFmpeg install.

## Note

Use this for content you own or are licensed to download. Respect YouTube's Terms
of Service and your local law.
