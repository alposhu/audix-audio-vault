"""Handing files over to the operating system."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("audix.ui.desktop")


def reveal_in_file_manager(path_str: str) -> None:
    """Open the OS file manager with ``path`` selected, best-effort."""
    if not path_str:
        return
    path = Path(path_str)
    if not path.exists():
        path = path.parent
    if not path.exists():
        return
    try:
        if sys.platform == "win32":
            if path.is_file():
                subprocess.Popen(["explorer", "/select,", str(path)])
            else:
                os.startfile(str(path))  # noqa: S606 - intentional shell-less open
        elif sys.platform == "darwin":
            args = ["open", "-R", str(path)] if path.is_file() else ["open", str(path)]
            subprocess.Popen(args)
        else:
            target = str(path if path.is_dir() else path.parent)
            subprocess.Popen(["xdg-open", target])
    except OSError as exc:
        log.warning("Could not open file manager for %s: %s", path, exc)


def open_file(path_str: str) -> bool:
    """Open a file in its default application. Returns whether that was possible."""
    path = Path(path_str or "")
    if not path.is_file():
        return False
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # noqa: S606 - intentional shell-less open
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError as exc:
        log.warning("Could not open %s: %s", path, exc)
        return False
    return True
