"""Human-readable formatting for sizes, speeds, and durations."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Optional


def format_bytes(value: Optional[float]) -> str:
    if not value or value <= 0:
        return "—"
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def format_speed(bytes_per_second: Optional[float]) -> str:
    if not bytes_per_second or bytes_per_second <= 0:
        return "—"
    return f"{format_bytes(bytes_per_second)}/s"


def format_eta(seconds: Optional[float]) -> str:
    if seconds is None or seconds < 0:
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def format_duration(seconds: Optional[float]) -> str:
    if not seconds or seconds <= 0:
        return "—"
    seconds = int(seconds)
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def elide(text: str, limit: int = 70) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def count(number: int, noun: str) -> str:
    """``1 track`` / ``2 tracks``."""
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def format_ago(timestamp: Optional[float], now: Optional[float] = None) -> str:
    """How long ago something happened, in the words a person would use."""
    if not timestamp:
        return "—"
    seconds = max(0, (time.time() if now is None else now) - timestamp)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return count(int(seconds // 3600), "hour") + " ago"
    if seconds < 86400 * 30:
        return count(int(seconds // 86400), "day") + " ago"
    return datetime.fromtimestamp(timestamp).strftime("%d %b %Y")


def format_clock(timestamp: Optional[float]) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%H:%M:%S") if timestamp else "—"
