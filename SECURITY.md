# Security

## Reporting a vulnerability

Open a [private security advisory](https://github.com/alposhu/audix-audio-vault/security/advisories/new)
rather than a public issue. Please include what you did, what happened, and what
you expected.

## What audix handles that is sensitive

**Browser session cookies.** Signing into YouTube in the embedded browser stores
real session credentials, so that age-restricted and members-only downloads work.

- Only cookies for `youtube.com`, `youtu.be`, `google.com`, `googlevideo.com`
  and `ytimg.com` are ever captured. Everything else the browser touches is
  discarded — verified against suffix-confusion attempts such as
  `youtube.com.evil.com`, which are rejected.
- They are written to `~/.audix/cookies.txt`, never into the project directory,
  and the filename is in `.gitignore` as a second line of defence.
- Permissions are restricted to your account: `0600` on macOS and Linux; on
  Windows, ACL inheritance is broken and a single explicit grant applied, so the
  file is not readable by other accounts on a shared machine.
- **Clear them any time** with *Settings → Sign out of the browser*, which deletes
  both the browser profile's cookies and the exported file.

**Your download lists.** The Queue (`~/.audix/queue.json`), finished downloads
(`~/.audix/history.jsonl`), and cached thumbnails stay on your machine. They record
video titles, links, and where files were saved. Removing an item from Downloads
deletes its record; the audio file itself stays where it is.

**The clipboard.** When audix comes to the front it reads the clipboard's text,
looking for a YouTube link to offer. Nothing is kept unless you add that link, and
nothing is sent anywhere. Turn it off under *Settings → Downloads*.

**Nothing is transmitted anywhere.** audix has no telemetry, no analytics, no
update check, and no server. It talks to YouTube (through `yt-dlp`, and for
thumbnails) and to GitHub (to fetch FFmpeg once). That is all.

## FFmpeg is downloaded at runtime

On first launch audix fetches a static FFmpeg build into `~/.audix/bin` and then
executes it. Stated plainly, because it is the largest trust decision the app
makes on your behalf:

- The download is HTTPS with certificate verification enabled, and a redirect to
  plaintext is refused.
- The archive's SHA-256 is always computed and written to the log.
- Archive entries that would escape the destination directory (Zip Slip) are
  rejected rather than extracted.
- Extracted binaries must execute successfully before being accepted.

**Residual risk:** by default the digest is not compared against a known value,
because the source is a rolling `latest` release whose content legitimately
changes. A checksum fetched from the same host would add nothing — anyone able
to replace the archive could replace the checksum beside it.

If you want a hard guarantee, pin one:

```bash
# Take the SHA-256 from your own log after a trusted first run,
# or compute it from a build you have verified yourself.
set AUDIX_FFMPEG_SHA256=e8ab8111...          # Windows
export AUDIX_FFMPEG_SHA256=e8ab8111...       # macOS / Linux
```

A mismatch aborts before anything is extracted or executed.

Alternatively, install FFmpeg yourself and put it on `PATH`; audix uses an
existing installation in preference to downloading one.

## Hardening already in place

| Area | Measure |
|---|---|
| Archive extraction | Path-traversal entries rejected (tested against Zip Slip payloads) |
| Filenames from video titles | Sanitised; output paths verified to stay inside the chosen folder |
| Subprocess calls | Argument lists only — never `shell=True`, never string commands |
| TLS | Verification never disabled; the embedded browser rejects invalid certificates |
| Cookies | Domain allowlist, restrictive file permissions, one-click wipe |
| Embedded browser script | Runs in Chromium's isolated world, so scripts on a page can neither see nor call it; everything it reports is treated as untrusted and validated |
| CI workflows | Least-privilege `permissions:` blocks, no untrusted input interpolated into `run:` |

## Known limitations

- **Releases are unsigned.** Windows SmartScreen will warn on first run. Signing
  requires a code-signing certificate. Verify downloads against the checksums in
  the release, and prefer building from source if that matters to you.
- **Dependencies use minimum-version pins** (`>=`), so `pip install` takes the
  newest compatible release. That gets security fixes automatically, at the cost
  of trusting future releases of PySide6, yt-dlp, mutagen, requests, numpy and
  sounddevice. Pin exact versions in your own environment if you need
  reproducibility.
- **`yt-dlp` fetches arbitrary remote media**, which is the point of the tool.
  Treat downloaded files as untrusted input, as you would any download.

## Scope

audix is a local desktop application. It exposes no network service, opens no
ports, and requires no elevated privileges.
