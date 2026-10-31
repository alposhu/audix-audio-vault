"""yt-dlp extraction layer.

Two responsibilities, deliberately separated:

* :func:`resolve_targets` — turn one pasted URL into a list of concrete tracks.
  Playlists are enumerated *flat* (cheap, one request) so a 200-item playlist
  populates the queue instantly instead of blocking on 200 full extractions.
* :class:`YoutubeDownloader` — fetch the best available audio stream for a single
  track, reporting progress and honouring cancellation and pausing.

Everything here is synchronous and callback-driven; threading lives in
:mod:`audix.core.link_queue` and :mod:`audix.core.download_manager`, which keeps
this module easy to test headlessly.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import asdict, dataclass, field, fields
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from audix.core import cookies as cookie_module
from audix.core import links, user_agents
from audix.utils import paths

log = logging.getLogger("audix.downloader")

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)

#: A Mix keeps generating tracks for as long as anyone asks. Measured at 383 on a
#: single seed video, so an explicit "take the whole mix" still gets a ceiling.
MIX_TRACK_LIMIT = 100


class Scope(str, Enum):
    """How much of a link the user asked for."""

    AUTO = "auto"              # what the link names: its video if it has one
    WHOLE_LIST = "whole_list"  # the list the link belongs to, on explicit request


class DownloadCancelled(RuntimeError):
    """Raised out of the progress hook when the user cancels a job."""


class DownloadPaused(RuntimeError):
    """Raised out of the progress hook when the user pauses a job.

    Unlike a cancel this keeps the ``.part`` file, so resuming continues from the
    same byte rather than starting again.
    """


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
    thumbnail: str = ""

    @property
    def is_playlist_item(self) -> bool:
        return self.playlist_index is not None

    @property
    def thumbnail_url(self) -> str:
        if self.thumbnail:
            return self.thumbnail
        return links.thumbnail_url(self.video_id) if self.video_id else ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "MediaEntry":
        known = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in raw.items() if key in known})


@dataclass(frozen=True)
class ParentList:
    """The list a single video was reached through, kept as a separate choice."""

    url: str
    list_id: str
    is_mix: bool


@dataclass
class ResolvedBatch:
    """The outcome of resolving a single pasted URL."""

    entries: List[MediaEntry] = field(default_factory=list)
    playlist_title: str = ""
    is_playlist: bool = False
    is_mix: bool = False
    #: Set when the link named one video and also carried a list we left out.
    parent_list: Optional[ParentList] = None


@dataclass
class DownloadedMedia:
    """A source file on disk plus the full info dict that produced it."""

    path: Path
    info: Dict[str, Any]

    @property
    def duration(self) -> Optional[float]:
        value = self.info.get("duration")
        return float(value) if value else None


@dataclass(frozen=True)
class ByteProgress:
    """One progress report from a running download."""

    fraction: float                  # 0..1 of this file
    speed: Optional[float]           # bytes/sec
    eta: Optional[float]             # seconds remaining
    done: int                        # bytes on disk
    total: int                       # bytes expected, 0 when unknown


ProgressCallback = Callable[[ByteProgress], None]


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def looks_like_url(text: str) -> bool:
    return bool(_URL_RE.match((text or "").strip()))


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

def resolve_targets(url: str, config, scope: Scope = Scope.AUTO) -> ResolvedBatch:
    """Expand a pasted URL into the tracks it refers to.

    A link that names a video yields that video, even when it also carries a list:
    the browser's address bar picks up ``list=`` from any Mix or playlist, and that
    must not silently turn one song into hundreds. The list comes back on
    ``parent_list`` so the UI can offer it, and ``Scope.WHOLE_LIST`` is how the user
    takes it up. A link to a list alone yields one entry per item, each carrying its
    index and the playlist title for album tagging.
    """
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    url = (url or "").strip()
    if not looks_like_url(url):
        raise ExtractionError("That does not look like a URL.")

    link = links.parse(url)
    just_the_video = link.has_video and scope is Scope.AUTO

    options = base_options(config)
    options.update({
        "extract_flat": "in_playlist",   # enumerate without extracting each video
        "skip_download": True,
        "noplaylist": just_the_video,
    })
    if link.is_mix and not just_the_video:
        options["playlistend"] = MIX_TRACK_LIMIT

    target = link.video_url if just_the_video else url
    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(target, download=False)
    except DownloadError as exc:
        raise ExtractionError(_humanise(str(exc))) from exc
    except Exception as exc:  # noqa: BLE001 - yt-dlp raises a wide variety
        raise ExtractionError(f"Could not read that URL: {exc}") from exc

    if not info:
        raise ExtractionError("No media was found at that URL.")

    if info.get("_type") == "playlist" or info.get("entries") is not None:
        batch = _batch_from_playlist(info)
        batch.is_mix = link.is_mix
        return batch

    batch = _batch_from_single(info, target)
    if link.has_list:
        batch.parent_list = ParentList(url=url, list_id=link.list_id, is_mix=link.is_mix)
    return batch


def _batch_from_single(info: Dict[str, Any], fallback_url: str) -> ResolvedBatch:
    entry = MediaEntry(
        url=str(info.get("webpage_url") or fallback_url),
        video_id=str(info.get("id") or links.parse(fallback_url).video_id),
        title=str(info.get("title") or "Untitled"),
        uploader=str(info.get("uploader") or info.get("channel") or ""),
        duration=_as_float(info.get("duration")),
        thumbnail=_thumbnail_of(info),
    )
    return ResolvedBatch(entries=[entry], playlist_title="", is_playlist=False)


def _without_repeats(raw_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each video once, in first-seen order.

    A Mix can loop back over itself: measured on one seed video, 100 entries held
    anywhere from 100 distinct videos down to 59, depending on the User-Agent asked
    with. This runs before numbering, so track numbers stay sequential and true.
    """
    seen = set()
    kept = []
    for raw in raw_entries:
        key = raw.get("id") or raw.get("url") or id(raw)
        if key not in seen:
            seen.add(key)
            kept.append(raw)
    return kept


def _batch_from_playlist(info: Dict[str, Any]) -> ResolvedBatch:
    playlist_title = str(info.get("title") or "Playlist")
    raw_entries = _without_repeats([e for e in (info.get("entries") or []) if e])

    entries: List[MediaEntry] = []
    total = len(raw_entries)
    for position, raw in enumerate(raw_entries, start=1):
        video_id = str(raw.get("id") or "")
        url = str(raw.get("url") or raw.get("webpage_url") or "")
        if url and not looks_like_url(url):
            # Flat extraction sometimes returns a bare id in `url`.
            url = links.watch_url(url)
        if not url and video_id:
            url = links.watch_url(video_id)
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
                thumbnail=_thumbnail_of(raw),
            )
        )

    if not entries:
        raise ExtractionError(
            "That playlist is empty, private, or unavailable in your region."
        )
    return ResolvedBatch(entries=entries, playlist_title=playlist_title, is_playlist=True)


def _thumbnail_of(info: Dict[str, Any]) -> str:
    """Artwork for sites other than YouTube, whose frames are not predictable."""
    if links.parse(str(info.get("webpage_url") or info.get("url") or "")).is_youtube:
        return ""
    thumbnails = info.get("thumbnails") or []
    fallback = thumbnails[-1].get("url") if thumbnails else ""
    return str(info.get("thumbnail") or fallback or "")


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
        pause_event: Optional[threading.Event] = None,
        on_info: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> DownloadedMedia:
        """Download ``entry`` into ``working_dir``; returns the file and its info.

        ``on_info`` fires once, as soon as yt-dlp has the real metadata, so a row
        that was queued with a guessed title corrects itself before the file lands.
        """
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError

        working_dir.mkdir(parents=True, exist_ok=True)
        captured: Dict[str, str] = {}
        announced: List[bool] = []

        def hook(status: Dict[str, Any]) -> None:
            if cancel_event is not None and cancel_event.is_set():
                raise DownloadCancelled("Download cancelled by user.")
            if pause_event is not None and pause_event.is_set():
                raise DownloadPaused("Download paused by user.")
            if on_info and not announced and status.get("info_dict"):
                announced.append(True)
                on_info(status["info_dict"])
            state = status.get("status")
            if state == "downloading" and progress:
                total = (status.get("total_bytes")
                         or status.get("total_bytes_estimate") or 0)
                done = status.get("downloaded_bytes") or 0
                fraction = (done / total) if total else 0.0
                progress(ByteProgress(
                    fraction=max(0.0, min(fraction, 1.0)),
                    speed=_as_float(status.get("speed")),
                    eta=_as_float(status.get("eta")),
                    done=int(done),
                    total=int(total),
                ))
            elif state == "finished":
                filename = status.get("filename")
                if filename:
                    captured["filename"] = filename
                if progress:
                    size = int(status.get("total_bytes") or 0)
                    progress(ByteProgress(1.0, None, 0.0, size, size))

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

        info = None
        cancelled = False
        try:
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(entry.url, download=True)
        except DownloadCancelled:
            cancelled = True
        except DownloadPaused:
            raise
        except DownloadError as exc:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
            elif pause_event is not None and pause_event.is_set():
                raise DownloadPaused("Download paused by user.") from exc
            else:
                raise ExtractionError(_humanise(str(exc))) from exc
        except Exception as exc:  # noqa: BLE001
            raise ExtractionError(f"Download failed: {exc}") from exc

        if cancelled:
            # Outside the except block on purpose: the live traceback keeps yt-dlp's
            # stream open, and Windows will not delete a file that is still open.
            _cleanup_partials(working_dir, job_id)
            raise DownloadCancelled("Download cancelled by user.")

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


def discard_partials(job_id: str) -> None:
    """Delete what a paused job left in the cache, once nobody will resume it."""
    _cleanup_partials(paths.cache_dir(), job_id)


def describe_source(info: Dict[str, Any]) -> str:
    """The stream actually fetched, e.g. ``opus · 129 kbps · webm``."""
    codec = str(info.get("acodec") or "").split(".")[0]
    bitrate = _as_float(info.get("abr") or info.get("tbr"))
    parts = [
        codec if codec and codec != "none" else "",
        f"{bitrate:.0f} kbps" if bitrate else "",
        str(info.get("ext") or ""),
    ]
    return " · ".join(part for part in parts if part)


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _humanise(message: str) -> str:
    """Translate common yt-dlp errors into something a user can act on."""
    lowered = message.lower()
    if "sign in to confirm your age" in lowered or "age" in lowered and "restrict" in lowered:
        return ("This video is age-restricted. Sign in on the Browse page, then turn "
                "on 'Share browser sign-in' in Settings and try again.")
    if "members-only" in lowered or "join this channel" in lowered:
        return ("This is members-only content. Sign in on the Browse page with an "
                "account that has access, then try again.")
    if "private video" in lowered:
        return "This video is private."
    if "video unavailable" in lowered:
        return "This video is unavailable, removed, or region-blocked."
    if "sign in to confirm" in lowered or "not a bot" in lowered:
        return ("YouTube asked for sign-in verification. Sign in on the Browse page "
                "so audix can reuse your session cookies.")
    if "unsupported url" in lowered:
        return "That URL is not supported."
    # Strip yt-dlp's "ERROR: " prefix for a cleaner UI message.
    return message.replace("ERROR: ", "").strip() or "Download failed."
