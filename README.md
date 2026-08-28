# audix — Audio-Vault

A high-performance, modular desktop application for extracting and converting audio
from YouTube videos and playlists.

`audix` is an open-source, trademark-safe name. The project is intended for
downloading content you own or are otherwise licensed to download, and for
archival / accessibility use. Respect YouTube's Terms of Service and local law.

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
- **Embedded search browser** — a real Chromium view (`QWebEngineView`) so you can
  search and browse YouTube inside the app. A "Send to Quick Convert" button lifts
  the current video URL straight into the converter.
- **Quick Convert** — paste any video / Shorts / playlist URL, pick a format and
  bitrate, choose an output folder, download.
- **Queue & Active Downloads** — parallel queue with per-item progress, speed, ETA,
  cancel, and a global pause toggle. Finished items offer **Edit**.
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

**Easiest — just launch it:**

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

`Ctrl+1`–`Ctrl+5` also switch between the five destinations in the navigation rail.

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

| Variant | Size | Build time | Browser tab |
|---|---|---|---|
| full | **529 MB** | 122 s | works |
| `--lite` | **174 MB** | 67 s | shows its "not available" placeholder |

Everything except the in-app browser is identical — paste links into **Get**, and
the whole editor and queue work unchanged.

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
    │   ├── downloader.py        # yt-dlp wrapper (threaded, progress hooks)
    │   ├── converter.py         # FFmpeg subprocess conversion
    │   ├── metadata.py          # mutagen tagging + cover art embedding
    │   └── queue_manager.py     # parallel task queue (QThreadPool)
    ├── ui/
    │   ├── theme.py             # dark stylesheet
    │   ├── main_window.py       # tabbed shell
    │   ├── tabs/
    │   │   ├── browser_tab.py
    │   │   ├── quick_convert_tab.py
    │   │   ├── queue_tab.py
    │   │   └── settings_tab.py
    │   └── widgets/
    │       ├── setup_dialog.py  # "First Time Setup" modal
    │       └── download_item.py # one row in the queue view
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
- **Pause** is a global queue pause — in-flight downloads finish, nothing new
  starts. Per-item control is **cancel**. Stated plainly rather than faked.
- macOS FFmpeg builds from evermeet.cx are x86_64 and run under Rosetta 2 on Apple
  Silicon. If you have Homebrew FFmpeg on `PATH`, that is used instead.

---

## Verification status

The codebase was exercised on Windows 11 / Python 3.14 / PySide6 6.11.2:

| Area | Result |
|---|---|
| All modules byte-compile | pass |
| Core logic (URLs, naming, cookies, formats, config, progress parsing) | pass |
| Main window + all four tabs built offscreen | pass |
| Queue manager: concurrency cap, pause, cancel-before-start, retry, clear | pass |
| FFmpeg auto-installer (real download, extract, PATH registration) | pass — 12.5 s cold, 0.05 s cached |
| Conversion + tagging across **all 10 formats**, tags read back from disk | pass |
| Tagged files re-decoded by FFmpeg to prove no corruption | pass |

Not covered: live YouTube extraction and the embedded browser's rendering, both of
which need network access to YouTube and a visible display.
