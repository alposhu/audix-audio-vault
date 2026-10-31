"""What a link actually points at.

A YouTube URL can name two things at once. ``watch?v=abc&list=RDabc`` names the
video ``abc`` and also the radio mix YouTube happens to be playing it from, and
yt-dlp, given the choice, takes the list. That one query parameter is the whole
difference between "download this song" and "queue 383 songs".

YouTube adds it constantly: clicking a thumbnail on the home page, starting a Mix,
or letting autoplay advance all leave ``list=`` in the address bar. So a link copied
from the embedded browser carries it far more often than one shared from elsewhere,
which usually arrives as a bare ``youtu.be/abc``.

The rule everything else follows: **a link that names a video means that video.**
The list is kept alongside it, so the UI can still offer it as a separate choice.

No Qt and no yt-dlp here, so this stays trivially testable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import parse_qs, urlsplit

_YOUTUBE_DOMAINS = ("youtube.com", "youtu.be", "youtube-nocookie.com")

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

#: Paths that carry the video id in the path instead of in ``?v=``.
_PATH_VIDEO_RE = re.compile(r"^/(?:shorts|embed|live|v|e)/([A-Za-z0-9_-]{11})(?:[/?#]|$)")

#: Finds links inside a block of pasted text, with or without the scheme.
_LINK_IN_TEXT_RE = re.compile(
    r"https?://[^\s<>\"']+"
    r"|(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)/[^\s<>\"']+",
    re.IGNORECASE,
)

#: Curated YouTube Music playlists borrow the ``RD`` prefix but have a fixed length.
_CURATED_LIST_PREFIX = "RDCLAK5uy_"


def is_mix_id(list_id: str) -> bool:
    """True for a YouTube-generated Mix or Radio, which has no real end."""
    return list_id.startswith("RD") and not list_id.startswith(_CURATED_LIST_PREFIX)


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def thumbnail_url(video_id: str) -> str:
    """The 320x180 frame YouTube serves for every video, with no API call."""
    return f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"


@dataclass(frozen=True)
class Link:
    """A parsed URL. Anything that is not YouTube only ever fills in ``url``."""

    url: str
    is_youtube: bool = False
    video_id: str = ""
    list_id: str = ""
    index: Optional[int] = None

    @property
    def has_video(self) -> bool:
        return bool(self.video_id)

    @property
    def has_list(self) -> bool:
        return bool(self.list_id)

    @property
    def is_mix(self) -> bool:
        return is_mix_id(self.list_id)

    @property
    def is_downloadable(self) -> bool:
        """Whether there is anything on this link for audix to take."""
        return self.has_video or self.has_list

    @property
    def video_url(self) -> str:
        """This video on its own, with every list and tracking parameter gone."""
        return watch_url(self.video_id) if self.video_id else ""


def parse(url: str) -> Link:
    """Read a URL into a :class:`Link`. Never raises, whatever it is given."""
    text = (url or "").strip()
    try:
        parts = urlsplit(text)
        host = (parts.hostname or "").lower()
    except ValueError:
        return Link(url=text)

    if parts.scheme.lower() not in ("http", "https") or not _is_youtube_host(host):
        return Link(url=text)

    query = parse_qs(parts.query)
    return Link(
        url=text,
        is_youtube=True,
        video_id=_video_id(host, parts.path, query),
        list_id=_first(query, "list"),
        index=_as_index(_first(query, "index")),
    )


def find_links(text: str) -> List[str]:
    """Every link in a block of pasted text, in order, without duplicates."""
    found: List[str] = []
    for match in _LINK_IN_TEXT_RE.findall(text or ""):
        link = match.rstrip(").,;]")
        if not link.lower().startswith(("http://", "https://")):
            link = f"https://{link}"
        if link not in found:
            found.append(link)
    return found


def _is_youtube_host(host: str) -> bool:
    return any(host == domain or host.endswith(f".{domain}")
               for domain in _YOUTUBE_DOMAINS)


def _video_id(host: str, path: str, query: dict) -> str:
    if host == "youtu.be" or host.endswith(".youtu.be"):
        candidate = path.strip("/").split("/")[0]
    else:
        candidate = _first(query, "v")
        if not candidate:
            match = _PATH_VIDEO_RE.match(path)
            candidate = match.group(1) if match else ""
    return candidate if _VIDEO_ID_RE.match(candidate) else ""


def _first(query: dict, key: str) -> str:
    values = query.get(key)
    return values[0].strip() if values else ""


def _as_index(value: str) -> Optional[int]:
    try:
        return int(value)
    except ValueError:
        return None
