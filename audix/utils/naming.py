"""Filename sanitisation and output-name templating.

Kept separate from the download pipeline so the same rules apply whether a name
comes from a single video, a playlist entry, or a user-supplied template.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Dict

# Characters Windows forbids outright, plus control characters.
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")

# Reserved device names on Windows; a file called "CON.mp3" is unopenable.
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

MAX_STEM_LEN = 120


def sanitize_filename(name: str, fallback: str = "audix-track") -> str:
    """Turn an arbitrary title into a safe cross-platform file stem."""
    if not name:
        return fallback
    # Normalise so decomposed accents don't inflate the length unexpectedly.
    name = unicodedata.normalize("NFC", str(name))
    name = _ILLEGAL.sub("_", name)
    name = _WHITESPACE.sub(" ", name).strip()
    # Trailing dots/spaces are silently stripped by Windows; do it explicitly.
    name = name.rstrip(". ")
    if len(name) > MAX_STEM_LEN:
        name = name[:MAX_STEM_LEN].rstrip(". ")
    if not name or name.upper() in _RESERVED:
        return fallback
    return name


def render_template(template: str, fields: Dict[str, object]) -> str:
    """Render a user filename template, tolerating unknown placeholders.

    Supported fields: ``{index}``, ``{title}``, ``{artist}``, ``{album}``,
    ``{year}``, ``{id}``. An unknown placeholder is left as literal text rather
    than raising, so a typo in settings degrades instead of breaking downloads.
    """
    safe: Dict[str, str] = {
        "index": _format_index(fields.get("index")),
        "title": str(fields.get("title") or ""),
        "artist": str(fields.get("artist") or ""),
        "album": str(fields.get("album") or ""),
        "year": str(fields.get("year") or ""),
        "id": str(fields.get("id") or ""),
    }
    out = template or "{title}"
    for key, value in safe.items():
        out = out.replace("{" + key + "}", value)
    out = _WHITESPACE.sub(" ", out).strip(" -_")
    return sanitize_filename(out, fallback=safe["title"] or "audix-track")


def _format_index(index: object) -> str:
    try:
        return f"{int(index):02d}"
    except (TypeError, ValueError):
        return ""


def unique_path(path: Path) -> Path:
    """Return ``path``, or ``path`` with a ``(2)``/``(3)``… suffix if it exists."""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    for counter in range(2, 1000):
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
    # Astronomically unlikely; fall back to something guaranteed distinct.
    import uuid

    return parent / f"{stem}-{uuid.uuid4().hex[:8]}{suffix}"
