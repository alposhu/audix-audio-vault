"""First-run dependency setup dialog.

Blocks the application until FFmpeg is confirmed available. The check and any
download run on a worker thread; the dialog only renders progress, so the window
stays responsive while a ~100 MB archive comes down.

The dialog cannot be dismissed while work is in flight — conversions must not be
allowed to start against a half-installed toolchain.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from audix.core.ffmpeg_manager import FFmpegError, FFmpegManager

log = logging.getLogger("audix.ui.setup")


class _SetupWorker(QObject):
    """Runs :meth:`FFmpegManager.ensure` off the UI thread."""

    progress = Signal(str, float)
    finished = Signal(bool, str)

    def __init__(self, manager: FFmpegManager) -> None:
        super().__init__()
        self.manager = manager

    @Slot()
    def run(self) -> None:
        try:
            self.manager.ensure(progress=lambda stage, pct: self.progress.emit(stage, pct))
            self.finished.emit(True, "")
        except FFmpegError as exc:
            log.error("FFmpeg setup failed: %s", exc)
            self.finished.emit(False, str(exc))
        except Exception as exc:  # noqa: BLE001 - surface anything unexpected
            log.exception("Unexpected error during FFmpeg setup")
            self.finished.emit(False, f"Unexpected error: {exc}")


class SetupDialog(QDialog):
    """Modal 'First Time Setup' progress dialog for the FFmpeg installer."""

    def __init__(self, manager: FFmpegManager, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.manager = manager
        self._thread: QThread | None = None
        self._worker: _SetupWorker | None = None
        self._succeeded = False

        self.setWindowTitle("audix — First Time Setup")
        self.setModal(True)
        self.setFixedWidth(460)
        # No close button: the app is not usable until this resolves.
        self.setWindowFlags(
            (self.windowFlags() | Qt.CustomizeWindowHint) & ~Qt.WindowCloseButtonHint
        )
        self._build_ui()

    # ------------------------------------------------------------------ layout
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 22)
        layout.setSpacing(14)

        heading = QLabel("First Time Setup")
        heading.setProperty("role", "title")
        layout.addWidget(heading)

        self.stage_label = QLabel("Downloading required audio codecs…")
        self.stage_label.setProperty("role", "subtitle")
        self.stage_label.setWordWrap(True)
        layout.addWidget(self.stage_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)        # indeterminate until we know better
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        self.detail_label = QLabel(
            "audix needs FFmpeg to convert audio. It will be installed privately "
            "into your home folder — nothing is changed system-wide."
        )
        self.detail_label.setProperty("role", "hint")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.retry_button = QPushButton("Retry")
        self.retry_button.setProperty("variant", "primary")
        self.retry_button.clicked.connect(self._start)
        self.retry_button.hide()
        self.quit_button = QPushButton("Quit")
        self.quit_button.clicked.connect(self.reject)
        self.quit_button.hide()
        buttons.addWidget(self.quit_button)
        buttons.addWidget(self.retry_button)
        layout.addLayout(buttons)

    # ------------------------------------------------------------------ public
    def run_setup(self) -> bool:
        """Show the dialog and block until setup succeeds or the user quits."""
        self._start()
        self.exec()
        return self._succeeded

    # --------------------------------------------------------------- internals
    def _start(self) -> None:
        self.retry_button.hide()
        self.quit_button.hide()
        self.progress.setRange(0, 0)
        self.stage_label.setProperty("role", "subtitle")
        self.stage_label.setText("Checking for required audio codecs…")
        self._restyle(self.stage_label)

        self._thread = QThread(self)
        self._worker = _SetupWorker(self.manager)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._thread.start()

    @Slot(str, float)
    def _on_progress(self, stage: str, percent: float) -> None:
        self.stage_label.setText(stage)
        if percent < 0:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(int(percent))

    @Slot(bool, str)
    def _on_finished(self, success: bool, error: str) -> None:
        self._stop_thread()
        self._succeeded = success
        if success:
            self.progress.setRange(0, 100)
            self.progress.setValue(100)
            self.accept()
            return

        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.stage_label.setProperty("role", "error")
        self.stage_label.setText("Setup failed")
        self._restyle(self.stage_label)
        self.detail_label.setText(
            f"{error}\n\nYou can retry, or install ffmpeg and ffprobe yourself and "
            "make sure they are on your PATH."
        )
        self.retry_button.show()
        self.quit_button.show()

    def _stop_thread(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(5000)
            self._thread = None
        self._worker = None

    @staticmethod
    def _restyle(widget: QWidget) -> None:
        """Re-evaluate QSS after a dynamic property changed."""
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    # Swallow the Escape key while work is in progress.
    def reject(self) -> None:  # noqa: D102
        if self._thread is not None and self._thread.isRunning():
            return
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: D102, N802
        if self._thread is not None and self._thread.isRunning():
            event.ignore()
            return
        self._stop_thread()
        super().closeEvent(event)
