"""A single row in the queue view.

Renders one :class:`DownloadTask`: title, state badge, progress, speed/ETA, and the
context-appropriate action button (cancel while running, retry when failed, reveal
in file manager when complete).
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from audix.core import formats
from audix.core.task import DownloadTask, TaskState
from audix.ui import theme
from audix.utils import humanize

log = logging.getLogger("audix.ui.queue")


class DownloadItemWidget(QFrame):
    """Row widget for one queued task."""

    cancel_requested = Signal(str)
    retry_requested = Signal(str)
    remove_requested = Signal(str)
    edit_requested = Signal(str)

    def __init__(self, task: DownloadTask, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.task_id = task.id
        self.setProperty("role", "card")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._build_ui()
        self.update_from(task)

    # ------------------------------------------------------------------ layout
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 11, 14, 11)
        outer.setSpacing(8)

        # --- top line: title + badge + actions ---------------------------
        top = QHBoxLayout()
        top.setSpacing(10)

        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-weight: 600; font-size: 13px;")
        self.title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        top.addWidget(self.title_label, 1)

        self.badge_label = QLabel()
        self.badge_label.setAlignment(Qt.AlignCenter)
        self.badge_label.setFixedHeight(20)
        top.addWidget(self.badge_label, 0)

        self.edit_button = QPushButton("Edit")
        self.edit_button.setProperty("variant", "tool")
        self.edit_button.setFixedWidth(56)
        self.edit_button.setToolTip(
            "Open in the editor — trim, level, or split by chapter"
        )
        self.edit_button.clicked.connect(
            lambda: self.edit_requested.emit(self.task_id)
        )
        self.edit_button.hide()
        top.addWidget(self.edit_button, 0)

        self.action_button = QPushButton("Cancel")
        self.action_button.setProperty("variant", "ghost")
        self.action_button.setFixedWidth(84)
        self.action_button.clicked.connect(self._on_action)
        top.addWidget(self.action_button, 0)

        self.remove_button = QPushButton("✕")
        self.remove_button.setProperty("variant", "ghost")
        self.remove_button.setFixedWidth(30)
        self.remove_button.setToolTip("Remove from queue")
        self.remove_button.clicked.connect(
            lambda: self.remove_requested.emit(self.task_id)
        )
        top.addWidget(self.remove_button, 0)

        outer.addLayout(top)

        # --- progress bar -------------------------------------------------
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        outer.addWidget(self.progress)

        # --- bottom line: stats -------------------------------------------
        bottom = QHBoxLayout()
        bottom.setSpacing(16)
        self.detail_label = QLabel()
        self.detail_label.setProperty("role", "hint")
        self.detail_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bottom.addWidget(self.detail_label, 1)

        self.speed_label = QLabel()
        self.speed_label.setProperty("role", "hint")
        bottom.addWidget(self.speed_label, 0)

        self.eta_label = QLabel()
        self.eta_label.setProperty("role", "hint")
        bottom.addWidget(self.eta_label, 0)

        outer.addLayout(bottom)

    # ------------------------------------------------------------------ update
    def update_from(self, task: DownloadTask) -> None:
        """Re-render this row from the current task state."""
        self._task_state = task.state
        self._output_path = task.output_path

        index_prefix = ""
        if task.entry.playlist_index:
            index_prefix = f"{task.entry.playlist_index:02d}. "
        self.title_label.setText(humanize.elide(index_prefix + task.title, 78))
        self.title_label.setToolTip(task.entry.url)

        self._set_badge(task.state)
        self.progress.setValue(int(task.progress * 1000))
        self._set_progress_tone(task.state)
        self.detail_label.setText(self._describe(task))
        self.detail_label.setToolTip(task.message or "")

        show_stats = task.state == TaskState.DOWNLOADING
        self.speed_label.setText(humanize.format_speed(task.speed) if show_stats else "")
        self.eta_label.setText(
            f"ETA {humanize.format_eta(task.eta)}" if show_stats and task.eta else ""
        )

        self._configure_action(task.state)

    def _describe(self, task: DownloadTask) -> str:
        fmt = formats.get(task.audio_format)
        quality = "lossless" if fmt.lossless else (
            "native bitrate" if task.bitrate == formats.NATIVE_BITRATE
            else f"{task.bitrate} kbps"
        )
        spec = f"{fmt.label} · {quality}"

        if task.state == TaskState.COMPLETED and task.output_path:
            return f"{spec} · saved to {Path(task.output_path).parent.name}"
        if task.state == TaskState.FAILED:
            return humanize.elide(task.message or "Failed", 90)
        if task.state == TaskState.CANCELLED:
            return f"{spec} · cancelled"
        if task.state in (TaskState.CONVERTING, TaskState.TAGGING):
            return f"{spec} · {task.state.value.lower()}…"
        if task.entry.duration:
            return f"{spec} · {humanize.format_duration(task.entry.duration)}"
        return spec

    def _set_badge(self, state: TaskState) -> None:
        color = theme.STATE_COLORS.get(state.value, theme.COLORS["text_dim"])
        self.badge_label.setText(f"  {state.value}  ")
        self.badge_label.setStyleSheet(
            f"color: {color};"
            f"border: 1px solid {color};"
            "border-radius: 9px;"
            "font-size: 10px;"
            "font-weight: 700;"
            "background: transparent;"
        )

    def _set_progress_tone(self, state: TaskState) -> None:
        if state == TaskState.COMPLETED:
            tone = "success"
        elif state == TaskState.FAILED:
            tone = "error"
        elif state in (TaskState.PENDING, TaskState.CANCELLED):
            tone = "idle"
        else:
            tone = "default"
        if self.progress.property("tone") != tone:
            self.progress.setProperty("tone", tone)
            self.progress.style().unpolish(self.progress)
            self.progress.style().polish(self.progress)

    def _configure_action(self, state: TaskState) -> None:
        # Editing is only meaningful once there is a finished file to edit.
        self.edit_button.setVisible(
            state == TaskState.COMPLETED and bool(self._output_path)
        )
        if state == TaskState.COMPLETED:
            self.action_button.setText("Show")
            self.action_button.setEnabled(bool(self._output_path))
            self.action_button.setToolTip("Reveal the file in your file manager")
        elif state in (TaskState.FAILED, TaskState.CANCELLED):
            self.action_button.setText("Retry")
            self.action_button.setEnabled(True)
            self.action_button.setToolTip("Queue this track again")
        else:
            self.action_button.setText("Cancel")
            self.action_button.setEnabled(True)
            self.action_button.setToolTip("Stop this download")

    # ----------------------------------------------------------------- actions
    def _on_action(self) -> None:
        state = self._task_state
        if state == TaskState.COMPLETED:
            reveal_in_file_manager(self._output_path)
        elif state in (TaskState.FAILED, TaskState.CANCELLED):
            self.retry_requested.emit(self.task_id)
        else:
            self.cancel_requested.emit(self.task_id)


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
