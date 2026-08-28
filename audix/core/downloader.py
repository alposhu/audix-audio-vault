"""yt-dlp extraction layer.

Two responsibilities, deliberately separated:

* :func:`resolve_targets` — turn one pasted URL into a list of concrete tracks.
  Playlists are enumerated *flat* (cheap, one request) so a 200-item playlist
  populates the queue instantly instead of blocking on 200 full extractions.
* :class:`YoutubeDownloader` — fetch the best available audio stream for a single
  track, reporting progress and honouring cancellation.

Everything here is synchronous and callback-driven; threading lives in
:mod:`audix.core.queue_manager`, which keeps this module easy to test headlessly.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from audix.core import cookies as cookie_module
from audix.core import user_agents

log = logging.getLogger("audix.downloader")

# (fraction 0..1, bytes/sec or None, seconds remaining or None)
ProgressCallback = Callable[[float, Optional[float], Optional[float]], None]

_YOUTUBE_HOSTS = ("youtube.com", "youtu.be", "music.youtube.com", "m.youtube.com")
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


class DownloadCancelled(RuntimeError):
    """Raised out of the progress hook when the user cancels a job."""


class ExtractionError(RuntimeError):
    """yt-dlp could not resolve or fetch the requested media."""


@dataclass
class MediaEntry:
    """One resolvable track. Populated cheaply, enriched at download time."""

    url: str
    video_id: str = ""
    title: str = "Loading…"
    uploader: str = ""
    duration: Optional[float] = None
    playlist_title: str = ""
    playlist_index: Optional[int] = None
    playlist_count: Optional[int] = None

    @property
    def is_playlist_item(self) -> bool:
        return self.playlist_index is not None


@dataclass
class ResolvedBatch:
    """The outcome of resolving a single pasted URL."""

    entries: List[MediaEntry] = field(default_factory=list)
    playlist_title: str = ""
    is_playlist: bool = False


@dataclass
class DownloadedMedia:
    """A source file on disk plus the full info dict that produced it."""

    path: Path
    info: Dict[str, Any]

    @property
    def duration(self) -> Optional[float]:
        value = self.info.get("duration")
        return float(value) if value else None


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def looks_like_url(text: str) -> bool:
    return bool(_URL_RE.match((text or "").strip()))


def is_youtube_url(text: str) -> bool:
    text = (text or "").strip().lower()
    return looks_like_url(text) and any(host in text for host in _YOUTUBE_HOSTS)


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def extract_video_id(url: str) -> str:
    """Best-effort video id from watch, shorts, embed, or youtu.be URLs."""
    patterns = (
        r"[?&]v=([A-Za-z0-9_-]{11})",
        r"youtu\.be/([A-Za-z0-9_-]{11})",
        r"/shorts/([A-Za-z0-9_-]{11})",
        r"/embed/([A-Za-z0-9_-]{11})",
        r"/live/([A-Za-z0-9_-]{11})",
    )
    for pattern in patterns:
        match = re.search(pattern, url or "")
        if match:
            return match.group(1)
    return ""


# ---------------------------------------------------------------------------
# yt-dlp option construction
# ---------------------------------------------------------------------------

class _YdlLogger:
    """Routes yt-dlp's chatter into our logger instead of stdout."""

    def debug(self, msg: str) -> None:
        if msg.startswith("[debug] "):
            return
        log.debug("yt-dlp: %s", msg)

    def info(self, msg: str) -> None:
        log.debug("yt-dlp: %s", msg)

    def warning(self, msg: str) -> None:
        log.warning("yt-dlp: %s", msg)

    def error(self, msg: str) -> None:
        log.error("yt-dlp: %s", msg)


def base_options(config) -> Dict[str, Any]:
    """Shared yt-dlp options derived from user settings.

    Applies the session User-Agent and, when enabled, the cookie file exported from
    the embedded browser — which is what makes age-restricted and members-only
    content downloadable.
    """
    agent = user_agents.session_user_agent(
        fixed=getattr(config, "fixed_user_agent", "") or "",
        rotate=getattr(config, "rotate_user_agent", True),
    )
    options: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "ignoreerrors": False,
        "consoletitle": False,
        "logger": _YdlLogger(),
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 30,
        "http_headers": {
            "User-Agent": agent,
            "Accept-Language": "en-US,en;q=0.9",
        },
    }

    if getattr(config, "use_browser_cookies", True):
        cookie_file = cookie_module.existing_cookie_file()
        if cookie_file:
            options["cookiefile"] = cookie_file
            log.debug("Using browser cookies from %s", cookie_file)

    proxy = (getattr(config, "proxy", "") or "").strip()
    if proxy:
        options["proxy"] = proxy

    return options


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def resolve_targets(url: str, config) -> ResolvedBatch:
    """Expand a pasted URL into the tracks it refers to.

    A single video yields one entry; a playlist yields one entry per item, each
    carrying its index and the playlist title for album tagging.
    """
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    url = (url or "").strip()
    if not looks_like_url(url):
        raise ExtractionError("That does not look like a URL.")

    options = base_options(config)
    options.update({
        "extract_flat": "in_playlist",   # enumerate without extracting each video
        "skip_download": True,
        "noplaylist": False,
    })

    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as exc:
        raise ExtractionError(_humanise(str(exc))) from exc
    except Exception as exc:  # noqa: BLE001 - yt-dlp raises a wide variety
        raise ExtractionError(f"Could not read that URL: {exc}") from exc

    if not info:
        raise ExtractionError("No media was found at that URL.")

    if info.get("_type") == "playlist" or info.get("entries") is not None:
        return _batch_from_playlist(info)
    return _batch_from_single(info, url)


def _batch_from_single(info: Dict[str, Any], fallback_url: str) -> ResolvedBatch:
    entry = MediaEntry(
        url=str(info.get("webpage_url") or fallback_url),
        video_id=str(info.get("id") or extract_video_id(fallback_url)),
        title=str(info.get("title") or "Untitled"),
        uploader=str(info.get("uploader") or info.get("channel") or ""),
        duration=_as_float(info.get("duration")),
    )
    return ResolvedBatch(entries=[entry], playlist_title="", is_playlist=False)


def _batch_from_playlist(info: Dict[str, Any]) -> ResolvedBatch:
    playlist_title = str(info.get("title") or "Playlist")
    raw_entries = [e for e in (info.get("entries") or []) if e]

    entries: List[MediaEntry] = []
    total = len(raw_entries)
    for position, raw in enumerate(raw_entries, start=1):
        video_id = str(raw.get("id") or "")
        url = str(raw.get("url") or raw.get("webpage_url") or "")
        if url and not looks_like_url(url):
            # Flat extraction sometimes returns a bare id in `url`.
            url = watch_url(url)
        if not url and video_id:
            url = watch_url(video_id)
        if not url:
            continue
        entries.append(
            MediaEntry(
                url=url,
                video_id=video_id,
                title=str(raw.get("title") or f"Track {position}"),
                uploader=str(raw.get("uploader") or raw.get("channel") or ""),
                duration=_as_float(raw.get("duration")),
                playlist_title=playlist_title,
                playlist_index=position,
                playlist_count=total,
            )
        )

    if not entries:
        raise ExtractionError(
            "That playlist is empty, private, or unavailable in your region."
        )
    return ResolvedBatch(entries=entries, playlist_title=playlist_title, is_playlist=True)


# ---------------------------------------------------------------------------
# Downloading
# ---------------------------------------------------------------------------

class YoutubeDownloader:
    """Fetches the best audio-only stream for a single track."""

    #: Prefer a real audio-only stream; fall back to muxed media if none exists.
    FORMAT_SELECTOR = "bestaudio[acodec!=none]/bestaudio/best[acodec!=none]/best"

    def __init__(self, config) -> None:
        self.config = config

    def download(
        self,
        entry: MediaEntry,
        working_dir: Path,
        job_id: str,
        progress: Optional[ProgressCallback] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> DownloadedMedia:
        """Download ``entry`` into ``working_dir``; returns the file and its info."""
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError

        working_dir.mkdir(parents=True, exist_ok=True)
        captured: Dict[str, str] = {}

        def hook(status: Dict[str, Any]) -> None:
            if cancel_event is not None and cancel_event.is_set():
                raise DownloadCancelled("Download cancelled by user.")
            state = status.get("status")
            if state == "downloading" and progress:
                total = (status.get("total_bytes")
                         or status.get("total_bytes_estimate") or 0)
                done = status.get("downloaded_bytes") or 0
                fraction = (done / total) if total else 0.0
                progress(
                    max(0.0, min(fraction, 1.0)),
                    _as_float(status.get("speed")),
                    _as_float(status.get("eta")),
                )
            elif state == "finished":
                filename = status.get("filename")
                if filename:
                    captured["filename"] = filename
                if progress:
                    progress(1.0, None, 0.0)

        options = base_options(self.config)
        options.update({
            "format": self.FORMAT_SELECTOR,
            "outtmpl": str(working_dir / f"{job_id}.%(ext)s"),
            "progress_hooks": [hook],
            "noplaylist": True,
            "overwrites": True,
            "concurrent_fragment_downloads": 4,
            "postprocessors": [],       # audix does its own conversion
        })

        try:
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(entry.url, download=True)
        except DownloadCancelled:
            _cleanup_partials(working_dir, job_id)
            raise
        except DownloadError as exc:
            if cancel_event is not None and cancel_event.is_set():
                _cleanup_partials(working_dir, job_id)
                raise DownloadCancelled("Download cancelled by user.") from exc
            raise ExtractionError(_humanise(str(exc))) from exc
        except Exception as exc:  # noqa: BLE001
            raise ExtractionError(f"Download failed: {exc}") from exc

        if not info:
            raise ExtractionError("yt-dlp returned no information for this track.")
        if info.get("_type") == "playlist":
            # noplaylist should prevent this, but be defensive about the shape.
            children = [e for e in (info.get("entries") or []) if e]
            if not children:
                raise ExtractionError("No downloadable media at that URL.")
            info = children[0]

        path = self._locate_output(captured.get("filename"), working_dir, job_id)
        if path is None:
            raise ExtractionError(
                "The audio stream was downloaded but the file could not be found."
            )
        return DownloadedMedia(path=path, info=info)

    @staticmethod
    def _locate_output(reported: Optional[str], working_dir: Path,
                       job_id: str) -> Optional[Path]:
        """Find the downloaded file, trusting the hook first, then globbing."""
        if reported:
            candidate = Path(reported)
            if candidate.is_file():
                return candidate
            # yt-dlp may report the pre-merge name; check for a sibling.
            sibling = candidate.with_suffix("")
            for match in sorted(working_dir.glob(f"{sibling.name}*")):
                if match.is_file() and not match.name.endswith(".part"):
                    return match
        matches = [
            p for p in sorted(working_dir.glob(f"{job_id}.*"))
            if p.is_file() and not p.name.endswith((".part", ".ytdl"))
        ]
        return matches[0] if matches else None


def _cleanup_partials(working_dir: Path, job_id: str) -> None:
    for path in working_dir.glob(f"{job_id}*"):
        try:
            path.unlink()
        except OSError:
            pass


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _humanise(message: str) -> str:
    """Translate common yt-dlp errors into something a user can act on."""
    lowered = message.lower()
    if "sign in to confirm your age" in lowered or "age" in lowered and "restrict" in lowered:
        return ("This video is age-restricted. Sign in on the Browser tab, then "
                "enable 'Use browser cookies' in Settings and try again.")
    if "members-only" in lowered or "join this channel" in lowered:
        return ("This is members-only content. Sign in on the Browser tab with an "
                "account that has access, then try again.")
    if "private video" in lowered:
        return "This video is private."
    if "video unavailable" in lowered:
        return "This video is unavailable, removed, or region-blocked."
    if "sign in to confirm" in lowered or "not a bot" in lowered:
        return ("YouTube asked for sign-in verification. Sign in on the Browser tab "
                "so audix can reuse your session cookies.")
    if "unsupported url" in lowered:
        return "That URL is not supported."
    # Strip yt-dlp's "ERROR: " prefix for a cleaner UI message.
    return message.replace("ERROR: ", "").strip() or "Download failed."
