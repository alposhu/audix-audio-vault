<div align="center">

<img src="audix/assets/logo.png" width="120" alt="audix">

# audix — Audio Vault

**Pull audio out of YouTube and finish it into a library: converted, trimmed, leveled, tagged, and split.**

[![Build](https://github.com/alposhu/audix-audio-vault/actions/workflows/release.yml/badge.svg)](https://github.com/alposhu/audix-audio-vault/actions/workflows/release.yml)
[![CI](https://github.com/alposhu/audix-audio-vault/actions/workflows/ci.yml/badge.svg)](https://github.com/alposhu/audix-audio-vault/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Windows](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D6)](https://www.microsoft.com/windows)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776AB)](https://www.python.org)
[![Download](https://img.shields.io/github/v/release/alposhu/audix-audio-vault?label=download&color=eecb7d)](https://github.com/alposhu/audix-audio-vault/releases/latest)

</div>

---

Every other tool does half of this job. A downloader hands you a raw file; an
audio editor knows nothing about where that file came from. audix does both, so
it can do what neither can alone — split a 90-minute mix into individually tagged
tracks using the chapters it already has.

The project is intended for downloading content you own or are otherwise licensed
to download, and for archival / accessibility use. Respect YouTube's Terms of
Service and local law.

---

## Features

- **Sound editor** — two-tone waveform, selection, zoom, trim, cut, fades, gain,
  EQ, speed/pitch, reverse, and undo. Detailed below.
- **Chapter splitting** — because audix did the download, it already holds the
  video's chapters. One action turns a 90-minute mix into individually numbered,
  tagged tracks. A standalone editor structurally cannot do this.
- **Real-time effect preview** with an A/B bypass — hear a change *while* the audio
  plays and compare against the original instantly.
- **EBU R128 loudness normalization** (two-pass), alongside peak normalization.
- **Profiles** — Collector, Casual, Podcaster, DJ. Each presets format, loudness
  target, and how much of the editor is exposed up front.
- **A link means what it says** — a link that names a video gets you that video,
  however it was copied. YouTube leaves `list=RD...` on a video playing from a Mix,
  which used to turn one song into hundreds of queued tracks. The Mix or playlist is
  still one click away, as a separate choice.
- **Queue** — paste links, several at once, or drop them on the window. Every link
  lands as ticked rows, with playlists grouped under a header you can tick as a
  whole. Nothing starts until you choose: untick what you do not want, then press
  **Download selected** or **Download all**. The list survives a restart, tracks you
  already have arrive unticked, and a link on your clipboard is offered when audix
  comes to the front.
- **Downloads** — every item with its stage, size, speed, and time left, in fixed
  columns that never jump. Pause, resume, reorder, cancel, and retry each one, or run
  up to 16 at once. Selecting a row opens an inspector with the stream that was
  fetched, how long each stage took, and where the file went. Anything that finishes
  while you are elsewhere stays lit until you have seen it. Finished items are
  remembered between sessions and offer **Edit**.
- **Browse** — a real Chromium view (`QWebEngineView`) of YouTube with audix built
  in. The dock under the page always names what is on screen and offers Download and
  Add to Queue. Pointing at any thumbnail shows both right on it, and right-clicking
  any video link offers them too, along with a clean copy of the link.
- **Formats**
  - Lossy: `mp3`, `aac`, `m4a`, `opus`, `ogg`, `wma`
  - Lossless: `flac`, `wav`, `alac`, `aiff`
  - Bitrate presets: 128 / 192 / 256 / 320 kbps, or *native source bitrate*.
- **Metadata & tagging** — title, artist/uploader, album (playlist or track),
  release year, track numbers for playlists, and embedded cover art.
- **Cookie hand-off** — cookies collected in the embedded browser are exported to a
  Netscape cookie file and passed to `yt-dlp`, so age-restricted or members-only
  streams work if your logged-in session can see them.
- **User-agent rotation** — a clean, current desktop UA is picked per session for
  both the embedded browser and the `yt-dlp` backend.
- **FFmpeg auto-installer** — on first launch, if `ffmpeg` / `ffprobe` are not on
  `PATH` or in `~/.audix/bin`, a static build for your OS / architecture is
  downloaded, extracted to `~/.audix/bin`, and prepended to `PATH`. Downloads and
  conversions are blocked until this succeeds.

---

## Install & run

**Windows, no Python:** grab a build from
[Releases](https://github.com/alposhu/audix-audio-vault/releases/latest), unzip it
anywhere, run the executable.

| Asset | Download | Run | Difference |
|---|---|---|---|
| `audix-lite-*-win64.zip` | ~76 MB | `audix-lite.exe` | Everything except the in-app browser. Paste links into the **Queue**. |
| `audix-*-win64.zip` | ~222 MB | `audix.exe` | Adds the embedded Chromium browser: search YouTube in-app, stay signed in. |

Take **lite** unless you specifically want the Browse page; the editor, queue, and
every format are identical. `SHA256SUMS.txt` in the release verifies your download.

**From source — just launch it:**

- **Windows:** double-click **`launch.bat`**
- **macOS / Linux:** run **`./launch.sh`**

The launcher creates the virtual environment, installs dependencies on first run,
and starts the app. It stays open if anything fails, so you can read the error.

**Manual:**

```bash
cd audix
python -m venv .venv
# Windows:  .venv\Scripts\python.exe -m pip install -r requirements.txt
# macOS/Linux: .venv/bin/python -m pip install -r requirements.txt
python run.py
```

Python 3.9+ is required. No system FFmpeg install is needed — `audix` fetches its
own on first run (BtbN static builds on Windows/Linux, evermeet.cx on macOS).

> `run.py` is interpreter-aware: if you start it with a Python that lacks the
> dependencies, it re-executes itself inside `.venv` rather than crashing.

---

## Troubleshooting

**The window flashes and disappears immediately.**
You launched `run.py` with a Python that has no dependencies installed. Use
`launch.bat` / `./launch.sh` instead — or check the log, which records the
interpreter that was used:

```
~/.audix/logs/audix.log        (Windows: C:\Users\<you>\.audix\logs\audix.log)
```

A line reading `No module named 'PySide6'` confirms it. Current `run.py` versions
detect this and either hand off to `.venv` or print instructions and wait for a
keypress, so the message stays on screen.

**Several Python versions installed?** Check which one has the packages:

```
py -0p                       # Windows: lists every installed Python
```

The app must run under `audix\.venv\Scripts\python.exe`.

**Log shows "No supported JavaScript runtime could be found".**
Recent yt-dlp versions want a JS runtime for full YouTube extraction. Audio
downloads generally still work without one, but some videos may offer fewer
formats. Installing [Deno](https://deno.com/) resolves it — yt-dlp picks it up
from `PATH` automatically, no audix configuration needed.

---

## The editor

Non-destructive throughout. Edits are parameters applied on export; the originally
downloaded file is never written to, so nothing is irreversible and undo history
costs bytes rather than megabytes.

| Group | What it does |
|---|---|
| Selection | Trim to selection, delete a span, fade in/out, strip silence at both ends |
| Levels | Gain, peak normalization, EBU R128 loudness to −14 / −16 / −23 LUFS |
| Equalizer | Low shelf 100 Hz, peaking 1 kHz, high shelf 8 kHz, plus presets |
| Time & pitch | 0.25×–4× speed with optional pitch preservation, ±12 semitones, reverse |
| Chapters | Detected from video markup *or* description timestamps; split on export |
| Export | Any of the 10 formats, as a single file or one file per chapter |

**Waveform performance.** Repaint cost is bounded by widget width, not by file
length. Amplitude is summarised once into a multi-resolution peak pyramid, and
drawing picks the coarsest level giving about one bucket per pixel. Measured:

| File length | Full-view draw | Zoomed draw |
|---|---|---|
| 3 minutes | 6.6 ms | 6.4 ms |
| 30 minutes | 7.0 ms | 6.2 ms |
| 90 minutes | 7.2 ms | 6.8 ms |
| 3 hours | 7.4 ms | 6.8 ms |

A 60× increase in duration costs 1.12× in draw time. This matters because the naive
approach is publicly documented to lock the UI for roughly three minutes on a
90-minute file.

**Quiet material.** Un-normalized rips often peak far below full scale and would
otherwise draw as a flat line. The view fits itself to the file's own peak and
states the factor (`×12.2 view · peak −22.5 dBFS`), so it never silently misleads
about level. `1:1` returns to true scale; Shift+wheel adjusts it.

**Memory.** Audio is decoded once into a temporary raw file and memory-mapped, so
RAM stays flat regardless of duration — a 3-hour file is not a 2 GB allocation. That
buffer is used only for drawing and monitoring; export re-renders from the original
source, so nothing is lost to it.

### Editor keyboard shortcuts

| Key | Action |
|---|---|
| `Space` | Play / pause |
| `Ctrl+1` / `Ctrl+2` / `Ctrl+3` | Zoom in / fit / out |
| `Ctrl+E` | Zoom to selection |
| `Ctrl+A` | Select all |
| `Ctrl+Z` / `Ctrl+Shift+Z` | Undo / redo |
| `Delete` | Delete selection |
| `B` / `L` | A/B bypass · loop selection |
| `Home` / `End` | Jump to start / end |
| `Shift`+wheel | Vertical (amplitude) zoom |
| `Ctrl`+wheel | Horizontal zoom at the cursor |

### Everywhere else

| Key | Action |
|---|---|
| `Alt+1` – `Alt+5` | Tune to Browse, Queue, Downloads, Edit, Settings (the numerals on the dial) |
| `Ctrl+Q` | Quit |

| In the Queue | Action |
|---|---|
| `Enter` in the link field | Add what is in it |
| `Space` | Select or deselect the current row |
| `Shift`+click | Carry a selection across a range |
| `Enter` on a row | Download that track now |
| `Delete` | Remove the current row |
| `Left` / `Right` | Collapse or expand a playlist |
| `Ctrl+A` | Select everything |

| In Browse | Action |
|---|---|
| `Ctrl+D` | Download what is on screen |
| `Ctrl+Shift+D` | Add it to the Queue |
| `Ctrl+L` | Jump to the address bar |

---

## Building a Windows executable

```
build_exe.bat                 # full build, one folder
build_exe.bat --lite          # no in-app browser, far smaller
build_exe.bat --lite --onefile
```

Or directly: `python packaging/build_exe.py [--lite] [--onefile]`.

Run `launch.bat` once first so the environment exists. PyInstaller is installed
automatically on the first build.

**Two variants**, because QtWebEngine dominates the size. Both measured on
Windows 11 / Python 3.14 / PySide6 6.11.2:

Sizes below are a local build; the published release archives are a little larger
(the CI runner builds on Python 3.12, which pulls slightly different wheels).

| Variant | Unpacked | Zipped | Build time | Browse page |
|---|---|---|---|---|
| full | **539 MB** | **211 MB** | 122 s | works |
| `--lite` | **178 MB** | **74 MB** | 67 s | shows its "not available" placeholder |

Everything except the in-app browser is identical — paste links into the **Queue**,
and the whole editor and download list work unchanged.

Startup, measured on the full build:

| | Time |
|---|---|
| First ever launch | 16.7 s (13 s of it downloading FFmpeg) |
| Every launch after | **1.0 s** |

Chrome DevTools resources (83 MB of `.pak` files for an inspector audix never
opens) are stripped from the bundle by the spec. What remains is mostly
irreducible: `Qt6WebEngineCore.dll` alone is 194 MB.

**One folder is the default, deliberately.** In one-file mode the bootloader
unpacks the entire bundle to a temp directory on every launch, and
`QtWebEngineProcess.exe` does not reliably locate its resources from there.
`--onefile` is genuinely useful for `--lite`, where there is no Chromium.

**FFmpeg is not bundled.** The app downloads a platform-correct static build into
`~/.audix/bin` on first run, which keeps the download small and lets codecs update
independently of the app. The executable is therefore not fully offline on first
launch, but is thereafter.

**Distributing it.** Zip the whole `dist/audix` folder — the executable needs the
files beside it. Verified to run after being copied to a different location, from a
path containing spaces, launched from an unrelated working directory.

The build is unsigned, so SmartScreen will warn on first run ("More info" → "Run
anyway"). Signing needs a code-signing certificate.

> If this project lives inside a synced folder (OneDrive, Dropbox), add `dist/` and
> `build/` to that client's exclusions. Otherwise a ~700 MB build output uploads to
> the cloud on every rebuild, and file locks held during sync can make the next
> build fail to delete the previous one. The build script retries such locks and
> explains them, but excluding the folders is the real fix.

---

## Design documents

`PRODUCT.md` and `DESIGN.md` at the repository root record the strategy and the
visual system. `scripts/verify_palette.py` recomputes every contrast figure in
DESIGN.md from its OKLCH sources and exits non-zero on any regression, so the
documented numbers cannot drift from the shipped tokens.

The dial's lettering is [Michroma](https://github.com/googlefonts/Michroma-font),
bundled under the SIL Open Font License (`audix/assets/fonts/OFL-Michroma.txt`).

## Tests

```bash
python -m unittest discover -s tests -t .
```

These stand in for yt-dlp and FFmpeg, so they need no network or binaries, and they
drive the real pages with real input events. CI runs them on every push.

---

## Project layout

```
audix/
├── run.py                       # launcher
├── requirements.txt
├── pyproject.toml
└── audix/
    ├── __main__.py              # entry point
    ├── app.py                   # bootstraps FFmpeg check, then the main window
    ├── config.py                # persisted user settings (~/.audix/config.json)
    ├── core/
    │   ├── ffmpeg_manager.py    # detect / download / register FFmpeg
    │   ├── formats.py           # format + bitrate definitions, ffmpeg arg builder
    │   ├── user_agents.py       # UA pool + rotation
    │   ├── cookies.py           # cookie jar -> Netscape cookie file
    │   ├── links.py             # what a URL actually refers to
    │   ├── downloader.py        # yt-dlp wrapper (threaded, progress hooks)
    │   ├── converter.py         # FFmpeg subprocess conversion
    │   ├── metadata.py          # mutagen tagging + cover art embedding
    │   ├── link_queue.py        # the Queue: tickable rows, before anything starts
    │   ├── download_manager.py  # parallel download engine (QThreadPool)
    │   └── history.py           # finished downloads, kept between sessions
    ├── ui/
    │   ├── tokens.py            # verified color, type, and spacing
    │   ├── theme.py             # global stylesheet
    │   ├── icons.py             # the icon set, drawn in code
    │   ├── paint.py             # lamps, tick ladders, tick boxes
    │   ├── output_prefs.py      # format, folder, and parallelism, shared by every page
    │   ├── thumbnails.py        # artwork, fetched without blocking a paint
    │   ├── web_bridge.py        # the isolated page script behind the Browse keys
    │   ├── main_window.py       # the dial above a stacked workspace
    │   ├── tabs/
    │   │   ├── browser_tab.py
    │   │   ├── queue_tab.py
    │   │   ├── downloads_tab.py
    │   │   ├── editor_tab.py
    │   │   └── settings_tab.py
    │   └── widgets/
    │       ├── dial.py          # tuning-dial navigation and signal meter
    │       ├── row_list.py      # painted rows with clickable zones
    │       ├── toast.py         # notes that replace modal dialogs
    │       └── setup_dialog.py  # "First Time Setup" modal
    └── utils/
        ├── paths.py             # ~/.audix locations
        └── logging_setup.py
```

---

## Notes / limitations

- **ALAC** files are written into an `.m4a` container (standard for Apple Lossless).
- **Raw `.aac` (ADTS)** has no container-level duration field, so players show a
  length estimated from bitrate — typically a few percent high. This is inherent to
  the format, not to tagging (verified: adding a 100 KB cover shifts the reported
  duration by exactly 0.00s). Choose **M4A** if you want AAC with an exact duration.
- **Pause** works while a track is downloading, and resumes from the same byte. Once
  a track is converting it can only be cancelled, because FFmpeg cannot be suspended.
  Quitting mid-download puts unfinished tracks back in the Queue, but they start over.
- **All at once** runs up to 16 tracks together. Past that YouTube starts refusing
  requests, so the rest wait their turn.
- **The Browse keys** read YouTube's page, so a redesign of theirs could stop a
  thumbnail's title or length from coming through. Download and Queue keep working
  regardless: yt-dlp supplies the real details when the track starts.
- macOS FFmpeg builds from evermeet.cx are x86_64 and run under Rosetta 2 on Apple
  Silicon. If you have Homebrew FFmpeg on `PATH`, that is used instead.

---

## Verification status

The codebase was exercised on Windows 11 / Python 3.14 / PySide6 6.11.2:

| Area | Result |
|---|---|
| All modules byte-compile | pass |
| Core logic (URLs, naming, cookies, formats, config, progress parsing) | pass |
| Real pages driven by real clicks, keys, and drops (`tests/`, 89 tests) | pass |
| Download engine: concurrency, pause/resume races, cancel, retry, reorder, shutdown | pass |
| FFmpeg auto-installer (real download, extract, PATH registration) | pass — 12.5 s cold, 0.05 s cached |
| Conversion + tagging across **all 10 formats**, tags read back from disk | pass |
| Tagged files re-decoded by FFmpeg to prove no corruption | pass |
| Real YouTube: Mix link yields 1 track, whole Mix on request, real MP3 with tags and cover | pass |
| Real YouTube: pause resumes from the same byte; cancel leaves nothing behind on Windows | pass |
| Embedded browser on real YouTube: dock, hover keys, Mix tiles, script isolation | pass |
