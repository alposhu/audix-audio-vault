"""Tab 2 — Quick Convert.

Paste a URL (video, Shorts, or playlist), pick a format and bitrate, choose where
the files land, and queue it. Resolution happens on a worker thread through the
queue manager, so pasting a 300-track playlist never freezes the window.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from audix.core.downloader import ResolvedBatch, looks_like_url
from audix.core.queue_manager import QueueManager
from audix.core.task import DownloadTask
from audix.ui.widgets.format_selector import FormatSelector
from audix.utils import humanize

log = logging.getLogger("audix.ui.quick")


class QuickConvertTab(QWidget):
    """URL in, queued tasks out."""

    tasks_queued = Signal(int)          # number of tasks added

    def __init__(self, queue: QueueManager, config, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.queue = queue
        self.config = config
        self._pending_batch: Optional[ResolvedBatch] = None
        self._resolving = False

        self._build_ui()
        self._load_config()

        self.queue.batch_resolved.connect(self._on_batch_resolved)
        self.queue.resolve_failed.connect(self._on_resolve_failed)

    # ------------------------------------------------------------------ layout
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(16)

        title = QLabel("Quick Convert")
        title.setProperty("role", "title")
        root.addWidget(title)

        subtitle = QLabel(
            "Paste a YouTube video, Shorts, or playlist link. Playlists expand into "
            "one queued track per item."
        )
        subtitle.setProperty("role", "subtitle")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        # --- URL row ------------------------------------------------------
        url_row = QHBoxLayout()
        url_row.setSpacing(10)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://www.youtube.com/watch?v=…")
        self.url_input.setClearButtonEnabled(True)
        self.url_input.returnPressed.connect(self.resolve_current_url)
        self.url_input.textChanged.connect(self._on_url_changed)
        url_row.addWidget(self.url_input, 1)

        self.paste_button = QPushButton("Paste")
        self.paste_button.setToolTip("Paste from clipboard")
        self.paste_button.clicked.connect(self._paste_from_clipboard)
        url_row.addWidget(self.paste_button)

        self.fetch_button = QPushButton("Fetch")
        self.fetch_button.setProperty("variant", "primary")
        self.fetch_button.clicked.connect(self.resolve_current_url)
        url_row.addWidget(self.fetch_button)
        root.addLayout(url_row)

        self.status_label = QLabel("")
        self.status_label.setProperty("role", "hint")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        # --- options ------------------------------------------------------
        options = QHBoxLayout()
        options.setSpacing(18)

        format_group = QGroupBox("Output")
        format_layout = QVBoxLayout(format_group)
        self.format_selector = FormatSelector()
        self.format_selector.changed.connect(self._on_format_changed)
        format_layout.addWidget(self.format_selector)
        options.addWidget(format_group, 1)

        dest_group = QGroupBox("Destination")
        dest_layout = QVBoxLayout(dest_group)
        dest_layout.setSpacing(10)
        dest_row = QHBoxLayout()
        dest_row.setSpacing(8)
        self.output_input = QLineEdit()
        self.output_input.setPlaceholderText("Where files are saved")
        dest_row.addWidget(self.output_input, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._choose_output_dir)
        dest_row.addWidget(browse)
        dest_layout.addLayout(dest_row)
        hint = QLabel("Playlists get their own subfolder inside this location.")
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        dest_layout.addWidget(hint)
        dest_layout.addStretch(1)
        options.addWidget(dest_group, 1)

        root.addLayout(options)

        # --- preview ------------------------------------------------------
        preview_header = QHBoxLayout()
        self.preview_title = QLabel("Nothing fetched yet")
        self.preview_title.setProperty("role", "section")
        preview_header.addWidget(self.preview_title, 1)
        self.summary_label = QLabel("")
        self.summary_label.setProperty("role", "hint")
        preview_header.addWidget(self.summary_label, 0)
        root.addLayout(preview_header)

        self.preview_list = QListWidget()
        self.preview_list.setAlternatingRowColors(False)
        self.preview_list.setSelectionMode(QListWidget.NoSelection)
        self.preview_list.setMinimumHeight(150)
        root.addWidget(self.preview_list, 1)

        # --- actions ------------------------------------------------------
        actions = QHBoxLayout()
        actions.addStretch(1)
        self.clear_button = QPushButton("Clear")
        self.clear_button.setProperty("variant", "ghost")
        self.clear_button.clicked.connect(self.clear)
        actions.addWidget(self.clear_button)

        self.queue_button = QPushButton("Add to Queue")
        self.queue_button.setProperty("variant", "primary")
        self.queue_button.setMinimumWidth(160)
        self.queue_button.setEnabled(False)
        self.queue_button.clicked.connect(self.queue_batch)
        actions.addWidget(self.queue_button)
        root.addLayout(actions)

    # ------------------------------------------------------------------ config
    def _load_config(self) -> None:
        self.output_input.setText(self.config.output_dir)
        self.format_selector.set_values(self.config.audio_format, self.config.bitrate)

    def refresh_from_config(self) -> None:
        """Called when Settings changes the defaults."""
        self.output_input.setText(self.config.output_dir)
        self.format_selector.set_values(self.config.audio_format, self.config.bitrate)

    # ------------------------------------------------------------------ public
    def set_url(self, url: str, auto_fetch: bool = True) -> None:
        """Populate the URL field, typically from the Browser tab."""
        self.url_input.setText(url)
        if auto_fetch and looks_like_url(url):
            self.resolve_current_url()

    @Slot()
    def resolve_current_url(self) -> None:
        url = self.url_input.text().strip()
        if not looks_like_url(url):
            self._set_status("Enter a full URL starting with http:// or https://",
                             error=True)
            return
        if self._resolving:
            return

        self._resolving = True
        self.fetch_button.setEnabled(False)
        self.fetch_button.setText("Fetching…")
        self.queue_button.setEnabled(False)
        self._set_status("Reading URL…")
        self.queue.resolve_url(url)

    @Slot()
    def queue_batch(self) -> None:
        """Turn the resolved preview into queued tasks."""
        batch = self._pending_batch
        if batch is None or not batch.entries:
            return

        output_dir = self.output_input.text().strip() or self.config.output_dir
        try:
            Path(output_dir).expanduser().mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._set_status(f"Cannot write to that folder: {exc}", error=True)
            return

        tasks: List[DownloadTask] = [
            DownloadTask(
                entry=entry,
                audio_format=self.format_selector.format_key(),
                bitrate=self.format_selector.bitrate(),
                output_dir=output_dir,
                embed_metadata=self.config.embed_metadata,
                embed_thumbnail=self.config.embed_thumbnail,
                write_track_numbers=self.config.write_track_numbers,
                keep_source_file=self.config.keep_source_file,
                filename_template=self.config.filename_template,
            )
            for entry in batch.entries
        ]

        self.queue.add_tasks(tasks)
        count = len(tasks)
        self._set_status(
            f"Queued {count} track{'s' if count != 1 else ''} "
            f"as {self.format_selector.describe()}.",
            success=True,
        )
        self.tasks_queued.emit(count)
        self._pending_batch = None
        self.queue_button.setEnabled(False)

    @Slot()
    def clear(self) -> None:
        self.url_input.clear()
        self.preview_list.clear()
        self._pending_batch = None
        self.queue_button.setEnabled(False)
        self.preview_title.setText("Nothing fetched yet")
        self.summary_label.clear()
        self._set_status("")

    # --------------------------------------------------------------- callbacks
    @Slot(object)
    def _on_batch_resolved(self, batch: ResolvedBatch) -> None:
        self._resolving = False
        self.fetch_button.setEnabled(True)
        self.fetch_button.setText("Fetch")
        self._pending_batch = batch
        self._render_preview(batch)
        self.queue_button.setEnabled(bool(batch.entries))
        count = len(batch.entries)
        self._set_status(
            f"Found {count} track{'s' if count != 1 else ''}. "
            "Review below, then add to the queue.",
            success=True,
        )

    @Slot(str)
    def _on_resolve_failed(self, message: str) -> None:
        self._resolving = False
        self.fetch_button.setEnabled(True)
        self.fetch_button.setText("Fetch")
        self._pending_batch = None
        self.queue_button.setEnabled(False)
        self._set_status(message, error=True)

    def _render_preview(self, batch: ResolvedBatch) -> None:
        self.preview_list.clear()
        if batch.is_playlist:
            self.preview_title.setText(f"PLAYLIST — {batch.playlist_title.upper()}")
        else:
            self.preview_title.setText("READY TO QUEUE")

        total_seconds = 0.0
        for entry in batch.entries:
            prefix = f"{entry.playlist_index:02d}.  " if entry.playlist_index else ""
            duration = humanize.format_duration(entry.duration)
            label = f"{prefix}{humanize.elide(entry.title, 80)}"
            if entry.duration:
                total_seconds += entry.duration
                label = f"{label}    ({duration})"
            item = QListWidgetItem(label)
            item.setToolTip(entry.url)
            self.preview_list.addItem(item)

        summary = f"{len(batch.entries)} item{'s' if len(batch.entries) != 1 else ''}"
        if total_seconds:
            summary += f" · {humanize.format_duration(total_seconds)} total"
        self.summary_label.setText(summary)

    # --------------------------------------------------------------- internals
    def _on_url_changed(self, text: str) -> None:
        if self._pending_batch is not None:
            # The preview no longer matches what is typed.
            self._pending_batch = None
            self.queue_button.setEnabled(False)

    def _on_format_changed(self) -> None:
        if self._pending_batch:
            self._set_status(f"Will convert to {self.format_selector.describe()}.")

    def _paste_from_clipboard(self) -> None:
        text = (QApplication.clipboard().text() or "").strip()
        if text:
            self.url_input.setText(text)
            self.url_input.setFocus()

    def _choose_output_dir(self) -> None:
        current = self.output_input.text().strip() or self.config.output_dir
        chosen = QFileDialog.getExistingDirectory(self, "Choose output folder", current)
        if chosen:
            self.output_input.setText(chosen)

    def _set_status(self, message: str, error: bool = False,
                    success: bool = False) -> None:
        role = "error" if error else ("success" if success else "hint")
        self.status_label.setProperty("role", role)
        self.status_label.setText(message)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

