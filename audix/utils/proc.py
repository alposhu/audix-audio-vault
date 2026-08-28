"""Subprocess helpers shared by the FFmpeg manager and converter.

The main job here is keeping console windows from flashing on Windows every time
we shell out to ffmpeg/ffprobe, which would otherwise happen once per queue item.
"""
from __future__ import annotations

import os
import subprocess
from typing import Any, Dict

IS_WINDOWS = os.name == "nt"


def no_window_kwargs() -> Dict[str, Any]:
    """Keyword args for :class:`subprocess.Popen` that suppress console windows."""
    if not IS_WINDOWS:
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "startupinfo": startupinfo,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }


def run_capture(cmd, timeout: float = 30.0) -> subprocess.CompletedProcess:
    """Run ``cmd`` capturing text output, never raising on non-zero exit."""
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        errors="replace",
        timeout=timeout,
        check=False,
        **no_window_kwargs(),
    )
