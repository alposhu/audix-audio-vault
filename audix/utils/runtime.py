"""Runtime environment detection.

A frozen build differs from a source checkout in ways that matter to audix:
there is no virtual environment to fall back on, there may be no console to
print an error to, and bundled data lives under a temporary extraction
directory rather than beside the package.
"""
from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """Directory holding bundled read-only data.

    ``sys._MEIPASS`` in a one-file build, the executable's folder in a
    one-folder build, and the project root when running from source.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    if is_frozen():
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


def executable_dir() -> Path:
    """Folder the user actually launched, for locating sibling files."""
    if is_frozen():
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


def has_console() -> bool:
    """Whether there is a usable stdout to print to.

    A windowed (``--noconsole``) build has no stdout, so any diagnostic must go
    to a dialog or the log file instead of ``print``.
    """
    stream = getattr(sys, "stdout", None)
    if stream is None:
        return False
    try:
        return stream.fileno() >= 0
    except (OSError, ValueError, AttributeError):
        return False


def describe() -> str:
    """One line for the log, identifying how audix was started."""
    mode = "frozen" if is_frozen() else "source"
    console = "with console" if has_console() else "windowed"
    return f"{mode}, {console}, python {sys.version.split()[0]}"
