"""Chapter detection and track splitting.

This is the capability a standalone audio editor structurally cannot have:
audix performed the download, so it holds the video's chapter list, artist,
album, year, and artwork before a waveform is ever drawn. A 90-minute DJ set or
a full-album upload can therefore be split into individually numbered, tagged
tracks in one action.

Two sources are supported, because uploaders use both:

1. **Real chapters** from yt-dlp's ``chapters`` field, when the uploader marked
   them up properly.
2. **Timestamps in the description**, which is how most music uploads actually
   do it ("0:00 Intro", "3:42 - Track Two"). Parsed as a fallback.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from audix.utils.naming import sanitize_filename

log = logging.getLogger("audix.chapters")

#: A timestamp at the start of a line, or after a leading index like "01.".
#: Accepts H:MM:SS and M:SS, optionally bracketed.
_TIMESTAMP = re.compile(
    r"""^\s*
        (?:\d{1,3}[.)]\s*)?                 # optional leading "01." / "1)"
        [\[\(]?                             # optional bracket
        (?P<h>\d{1,2}:)?(?P<m>\d{1,2}):(?P<s>\d{2})
        [\]\)]?
        \s*[-–—:.]?\s*
        (?P<title>.*\S)?                    # remainder is the title
        \s*$""",
    re.VERBOSE,
)

#: A timestamp appearing *after* the title ("Track Two - 3:42").
_TRAILING_TIMESTAMP = re.compile(
    r"^\s*(?P<title>.*\S)\s*[-–—:]?\s*"
    r"[\[\(]?(?P<h>\d{1,2}:)?(?P<m>\d{1,2}):(?P<s>\d{2})[\]\)]?\s*$"
)

#: Below this, a "chapter list" is more likely to be an accident than a tracklist.
MIN_CHAPTERS = 2

#: Chapters shorter than this are almost always mis-parsed lines, not tracks.
MIN_CHAPTER_SECONDS = 5.0


@dataclass
class Chapter:
    """One detected track within a longer recording."""

    index: int
    start: float
    end: float
    title: str
    source: str = "chapters"        # "chapters" | "description"

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def filename_stem(self, total: int) -> str:
        width = max(2, len(str(total)))
        return sanitize_filename(f"{self.index:0{width}d} - {self.title}",
                                 f"Track {self.index}")


def from_info(info: Dict[str, Any], duration: Optional[float] = None) -> List[Chapter]:
    """Extract chapters from a yt-dlp info dict, trying both sources.

    Real chapter markup wins; the description is parsed only when that is
    absent or unusably short.
    """
    total = duration or _as_float(info.get("duration")) or 0.0

    chapters = _from_chapter_field(info.get("chapters"), total)
    if len(chapters) >= MIN_CHAPTERS:
        log.info("Found %d chapters from video markup", len(chapters))
        return chapters

    described = parse_description(info.get("description") or "", total)
    if len(described) >= MIN_CHAPTERS:
        log.info("Found %d chapters from description timestamps", len(described))
        return described

    return chapters


def _from_chapter_field(raw: Any, total: float) -> List[Chapter]:
    if not isinstance(raw, list) or not raw:
        return []
    entries: List[Chapter] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        start = _as_float(item.get("start_time"))
        if start is None:
            continue
        end = _as_float(item.get("end_time"))
        title = str(item.get("title") or f"Chapter {index}").strip()
        entries.append(Chapter(index, start, end or total, title, "chapters"))
    # Explicit markup is trusted at any length: the uploader deliberately placed
    # these, so a short interlude or intro track is real, not a parse error. The
    # minimum-duration filter exists to reject mis-read description lines, and
    # applying it here silently discarded legitimate chapter lists.
    return _finalise(entries, total, enforce_minimum=False)


def parse_description(description: str, total: float) -> List[Chapter]:
    """Pull a tracklist out of free-text description timestamps."""
    if not description:
        return []

    found: List[tuple] = []
    for line in description.splitlines():
        line = line.strip()
        if not line or len(line) > 200:
            continue

        match = _TIMESTAMP.match(line)
        if match and (match.group("title") or match.group("h") or match.group("m")):
            seconds = _to_seconds(match)
            title = (match.group("title") or "").strip(" -–—:.\t")
            if seconds is not None:
                found.append((seconds, title))
            continue

        match = _TRAILING_TIMESTAMP.match(line)
        if match:
            seconds = _to_seconds(match)
            title = (match.group("title") or "").strip(" -–—:.\t")
            # Guard against a bare duration line being read as a track.
            if seconds is not None and title:
                found.append((seconds, title))

    if len(found) < MIN_CHAPTERS:
        return []

    # Timestamps must be non-decreasing to be a tracklist rather than noise.
    found.sort(key=lambda item: item[0])
    entries: List[Chapter] = []
    for index, (start, title) in enumerate(found, start=1):
        end = found[index][0] if index < len(found) else total
        entries.append(Chapter(index, start, end, title or f"Track {index}",
                               "description"))
    return _finalise(entries, total)


def _finalise(entries: List[Chapter], total: float,
              enforce_minimum: bool = True) -> List[Chapter]:
    """Sort, close open ends, drop degenerate spans, and renumber.

    ``enforce_minimum`` guards against description lines that merely look like
    timestamps. It is off for real chapter markup, which is authored, not
    inferred.
    """
    if not entries:
        return []
    entries.sort(key=lambda c: c.start)

    for index, chapter in enumerate(entries):
        if index + 1 < len(entries):
            chapter.end = entries[index + 1].start
        elif not chapter.end or chapter.end <= chapter.start:
            chapter.end = total or chapter.start

    threshold = MIN_CHAPTER_SECONDS if enforce_minimum else 0.05
    kept = [c for c in entries if c.duration >= threshold]
    if len(kept) < MIN_CHAPTERS:
        return []
    for number, chapter in enumerate(kept, start=1):
        chapter.index = number
    return kept


def _to_seconds(match: re.Match) -> Optional[float]:
    try:
        hours = int((match.group("h") or "0").rstrip(":"))
        minutes = int(match.group("m"))
        seconds = int(match.group("s"))
    except (TypeError, ValueError):
        return None
    if seconds >= 60 or minutes >= 60 and hours == 0 and not match.group("h"):
        # "90:00" is legitimate as M:SS only when there is no hour field.
        pass
    return float(hours * 3600 + minutes * 60 + seconds)


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def describe(chapters: List[Chapter]) -> str:
    """One-line summary for the UI."""
    if not chapters:
        return "No chapters detected"
    source = chapters[0].source
    origin = "video chapters" if source == "chapters" else "description timestamps"
    return f"{len(chapters)} tracks from {origin}"
