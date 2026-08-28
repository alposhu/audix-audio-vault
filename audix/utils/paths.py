"""Canonical filesystem locations used by audix.

Everything the app writes for itself lives under a single hidden directory,
``~/.audix``. Nothing here touches the user's project or system directories.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_DIRNAME = ".audix"


def app_home() -> Path:
    """Root config/data directory: ``~/.audix`` (override with ``AUDIX_HOME``)."""
    override = os.environ.get("AUDIX_HOME")
    base = Path(override).expanduser() if override else (Path.home() / APP_DIRNAME)
    return base


def bin_dir() -> Path:
    """Where downloaded FFmpeg / ffprobe binaries are placed."""
    return app_home() / "bin"


def cache_dir() -> Path:
    """Scratch space for downloads-in-progress and temp artifacts."""
    return app_home() / "cache"


def logs_dir() -> Path:
    return app_home() / "logs"


def config_file() -> Path:
    return app_home() / "config.json"


def cookies_file() -> Path:
    """Netscape cookie jar exported from the embedded browser for yt-dlp."""
    return app_home() / "cookies.txt"


def log_file() -> Path:
    return logs_dir() / "audix.log"


def default_output_dir() -> Path:
    """Sensible default library location: ``~/Music/audix``."""
    music = Path.home() / "Music"
    return (music if music.exists() else Path.home()) / "audix"


def ensure_dirs() -> None:
    """Create every directory audix expects. Safe to call repeatedly."""
    for path in (app_home(), bin_dir(), cache_dir(), logs_dir(), default_output_dir()):
        path.mkdir(parents=True, exist_ok=True)


def executable_name(stem: str) -> str:
    """``ffmpeg`` -> ``ffmpeg.exe`` on Windows, unchanged elsewhere."""
    return f"{stem}.exe" if os.name == "nt" else stem
