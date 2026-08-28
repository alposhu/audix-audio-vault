"""Application bootstrap.

Startup order matters and is enforced here:

1. Create directories and configure logging.
2. Import QtWebEngine *before* the ``QApplication`` exists — Chromium must be
   initialised first or the embedded browser cannot start.
3. Build the application and apply the dark theme.
4. Block on the FFmpeg check. Nothing that converts audio is constructed until it
   succeeds, so a half-installed toolchain can never reach the pipeline.
5. Show the main window.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import List, Optional

from audix import __version__
from audix.config import AppConfig
from audix.utils import paths
from audix.utils.logging_setup import setup_logging

log = logging.getLogger("audix.app")


def _preinitialise_webengine() -> bool:
    """Import QtWebEngine before any QApplication is constructed.

    Returns ``True`` if the embedded browser will be available. A failure here is
    not fatal: the Browser tab degrades to a placeholder.
    """
    try:
        from PySide6.QtCore import QCoreApplication, Qt

        # Chromium requires a shared OpenGL context across threads.
        QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)

        import PySide6.QtWebEngineCore  # noqa: F401
        import PySide6.QtWebEngineWidgets  # noqa: F401
        return True
    except ImportError as exc:
        log.warning("QtWebEngine unavailable, the Browser tab will be disabled: %s", exc)
        return False
    except Exception as exc:  # noqa: BLE001 - GPU/driver failures surface oddly
        log.warning("QtWebEngine could not be initialised: %s", exc)
        return False


def _configure_environment() -> None:
    """Environment tweaks applied before Qt starts."""
    # Respect an explicit user override; otherwise keep Chromium quiet and avoid
    # the sandbox warnings that clutter the console on some Linux setups.
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-logging")
    # High-DPI scaling is on by default in Qt6; make rounding predictable.
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")


def run(argv: Optional[List[str]] = None) -> int:
    """Start audix. Returns the process exit code."""
    argv = argv if argv is not None else sys.argv

    paths.ensure_dirs()
    setup_logging()
    log.info("Starting audix %s (Python %s on %s)",
             __version__, sys.version.split()[0], sys.platform)

    _configure_environment()
    webengine_ok = _preinitialise_webengine()

    # Qt imports happen after the WebEngine pre-initialisation above.
    from PySide6.QtWidgets import QApplication, QMessageBox

    from audix.core.ffmpeg_manager import FFmpegManager
    from audix.ui import theme
    from audix.ui.main_window import MainWindow
    from audix.ui.widgets.setup_dialog import SetupDialog

    app = QApplication(argv)
    app.setApplicationName("audix")
    app.setApplicationDisplayName("audix")
    app.setOrganizationName("audix")
    app.setApplicationVersion(__version__)
    theme.apply(app)

    config = AppConfig.load()
    log.info("Config loaded from %s", paths.config_file())

    # --- gate: FFmpeg must be present before anything can convert ----------
    ffmpeg = FFmpegManager(preferred_dir=config.ffmpeg_dir)
    dialog = SetupDialog(ffmpeg)
    if not dialog.run_setup():
        log.error("FFmpeg setup did not complete; exiting")
        QMessageBox.critical(
            None,
            "audix cannot start",
            "FFmpeg is required to convert audio and could not be installed.\n\n"
            f"See the log for details:\n{paths.log_file()}",
        )
        return 1

    log.info("FFmpeg ready: %s", ffmpeg.ffmpeg())
    if not webengine_ok:
        log.info("Running without the embedded browser")

    # Report the audio backend explicitly. In a frozen build a missing PortAudio
    # binary is invisible until someone presses play, so record it at startup
    # where a support log will show it.
    from audix.core.audio import engine as audio_engine

    if audio_engine.backend_available():
        log.info("Audio backend ready: real-time preview available")
    else:
        log.warning("Audio backend unavailable: %s", audio_engine.backend_error())

    window = MainWindow(config, ffmpeg)
    window.show()

    exit_code = app.exec()
    log.info("audix exited with code %s", exit_code)
    return exit_code
