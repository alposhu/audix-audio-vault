"""The application shell: navigation rail plus a stacked workspace.

The rail replaced a tab bar that was already at four destinations with no room
for a fifth, and no room at all for the editor's transport. Cross-surface flows
are wired here so no page needs a reference to any other:

* Browser sends a URL to Quick Convert, or queues it with saved defaults.
* A finished download offers Edit, which loads it into the editor with its
  original yt-dlp metadata, so chapters and artwork come along.
* Settings pushes new defaults into Quick Convert and the queue.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import Qt, QThreadPool, QTimer, Slot
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QProgressBar, QStackedWidget,
    QStatusBar, QWidget,
)

from audix import __version__
from audix.core.audio import decoder as decoder_module
from audix.core.downloader import MediaEntry
from audix.core.export import ExportJob, ExportRunner
from audix.core.ffmpeg_manager import FFmpegManager
from audix.core.queue_manager import QueueManager
from audix.core.task import DownloadTask, TaskState
from audix.ui.tabs.browser_tab import BrowserTab
from audix.ui.tabs.editor_tab import EditorTab
from audix.ui.tabs.queue_tab import QueueTab
from audix.ui.tabs.quick_convert_tab import QuickConvertTab
from audix.ui.tabs.settings_tab import SettingsTab
from audix.ui.tokens import COLORS
from audix.ui.widgets.download_item import reveal_in_file_manager
from audix.ui.widgets.rail import NavigationRail, RailItem

log = logging.getLogger("audix.ui.window")

PAGE_BROWSER, PAGE_CONVERT, PAGE_QUEUE, PAGE_EDITOR, PAGE_SETTINGS = range(5)

RAIL_ITEMS = [
    RailItem("browser", "Browse", "◎", "Search YouTube inside audix"),
    RailItem("convert", "Get", "↓", "Paste a link and queue it"),
    RailItem("queue", "Queue", "≡", "Active and finished downloads"),
    RailItem("editor", "Edit", "∿", "Trim, level, and split audio"),
    RailItem("settings", "Setup", "⚙", "Defaults, profile, and dependencies"),
]


class MainWindow(QMainWindow):
    """audix main window."""

    def __init__(self, config, ffmpeg: FFmpegManager) -> None:
        super().__init__()
        self.config = config
        self.ffmpeg = ffmpeg
        self.queue = QueueManager(ffmpeg, config, parent=self)

        self._export_pool = QThreadPool(self)
        self._export_pool.setMaxThreadCount(1)      # exports are IO/CPU heavy
        self._export_runner: Optional[ExportRunner] = None

        self.setWindowTitle(f"audix — Audio Vault  v{__version__}")
        self.setWindowIcon(_app_icon())
        self.resize(1320, 860)
        self.setMinimumSize(1040, 680)

        decoder_module.cleanup_orphans()

        self._build_shell()
        self._build_status_bar()
        self._connect_signals()
        self._install_shortcuts()

        log.info("Main window ready")

    # ------------------------------------------------------------------ layout
    def _build_shell(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.rail = NavigationRail(RAIL_ITEMS)
        layout.addWidget(self.rail)

        self.pages = QStackedWidget()
        self.browser_page = BrowserTab(self.config)
        self.convert_page = QuickConvertTab(self.queue, self.config)
        self.queue_page = QueueTab(self.queue, self.config)
        self.editor_page = EditorTab(self.config, self.ffmpeg)
        self.settings_page = SettingsTab(self.config, self.queue, self.ffmpeg)

        for page in (self.browser_page, self.convert_page, self.queue_page,
                     self.editor_page, self.settings_page):
            self.pages.addWidget(page)
        layout.addWidget(self.pages, 1)

        self.setCentralWidget(central)
        self.rail.changed.connect(self.pages.setCurrentIndex)
        self.rail.install_shortcuts(self)
        self._go(PAGE_CONVERT)

    def _build_status_bar(self) -> None:
        bar = QStatusBar()
        bar.setSizeGripEnabled(True)

        self.status_label = QLabel("Ready.")
        bar.addWidget(self.status_label, 1)

        self.export_progress = QProgressBar()
        self.export_progress.setFixedWidth(180)
        self.export_progress.setRange(0, 1000)
        self.export_progress.setTextVisible(False)
        self.export_progress.hide()
        bar.addPermanentWidget(self.export_progress)

        self.queue_status_label = QLabel("")
        bar.addPermanentWidget(self.queue_status_label)

        self.ffmpeg_status_label = QLabel("")
        bar.addPermanentWidget(self.ffmpeg_status_label)

        self.setStatusBar(bar)
        self._refresh_ffmpeg_status()
        self._on_stats_changed(*self.queue.counts())

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+Q"), self, self.close)

    # ----------------------------------------------------------------- signals
    def _connect_signals(self) -> None:
        self.browser_page.send_to_convert.connect(self._on_send_to_convert)
        self.browser_page.queue_requested.connect(self._on_queue_from_browser)
        self.browser_page.status_message.connect(self.show_status)

        self.convert_page.tasks_queued.connect(self._on_tasks_queued)

        self.queue.stats_changed.connect(self._on_stats_changed)
        self.queue.task_finished.connect(self._on_task_finished)
        self.queue.autoqueue_finished.connect(self._on_autoqueue_finished)

        self.queue_page.edit_requested.connect(self._on_edit_requested)

        self.editor_page.export_requested.connect(self._on_export_requested)
        self.editor_page.status_message.connect(self.show_status)

        self.settings_page.settings_saved.connect(self._on_settings_saved)
        self.settings_page.session_clear_requested.connect(
            self.browser_page.clear_session)
        self.settings_page.user_agent_changed.connect(self._on_user_agent_changed)

    # --------------------------------------------------------------- callbacks
    def _go(self, index: int) -> None:
        self.rail.set_current(index)
        self.pages.setCurrentIndex(index)

    @Slot(str)
    def _on_send_to_convert(self, url: str) -> None:
        self._go(PAGE_CONVERT)
        self.convert_page.set_url(url, auto_fetch=True)
        self.show_status("Sent to Get. Fetching details…")

    @Slot(str)
    def _on_queue_from_browser(self, url: str) -> None:
        if not self.ffmpeg.ready:
            self._warn_not_ready()
            return
        self.show_status("Reading URL…")
        self.queue.resolve_and_enqueue(url, self._make_task_factory())

    def _make_task_factory(self):
        config = self.config

        def factory(entry: MediaEntry) -> DownloadTask:
            return DownloadTask(
                entry=entry,
                audio_format=config.audio_format,
                bitrate=config.bitrate,
                output_dir=config.output_dir,
                embed_metadata=config.embed_metadata,
                embed_thumbnail=config.embed_thumbnail,
                write_track_numbers=config.write_track_numbers,
                keep_source_file=config.keep_source_file,
                filename_template=config.filename_template,
            )

        return factory

    @Slot(int, str)
    def _on_autoqueue_finished(self, count: int, error: str) -> None:
        if error:
            self.show_status(error, 12000)
            QMessageBox.warning(self, "Could not queue that link", error)
            return
        self._go(PAGE_QUEUE)
        self.show_status(f"Queued {count} track{'s' if count != 1 else ''}.")

    @Slot(int)
    def _on_tasks_queued(self, count: int) -> None:
        self._go(PAGE_QUEUE)
        self.show_status(f"Queued {count} track{'s' if count != 1 else ''}.")

    @Slot(int, int, int)
    def _on_stats_changed(self, active: int, pending: int, completed: int) -> None:
        if active or pending:
            state = "paused" if self.queue.is_paused else "running"
            self.queue_status_label.setText(
                f"Queue {state}: {active} active · {pending} waiting")
            self.rail.set_badge(PAGE_QUEUE, f"({active + pending})")
        else:
            self.queue_status_label.setText(
                f"{completed} completed" if completed else "Queue idle")
            self.rail.set_badge(PAGE_QUEUE, "")

    @Slot(str, bool, str)
    def _on_task_finished(self, task_id: str, success: bool, message: str) -> None:
        task = self.queue.task(task_id)
        title = task.title if task else "Track"
        if success:
            self.show_status(f"Finished: {title}")
        elif message and message != "Cancelled":
            self.show_status(f"Failed: {title} — {message}", 12000)

    @Slot(str)
    def _on_edit_requested(self, task_id: str) -> None:
        """Open a finished download in the editor, carrying its metadata across."""
        task = self.queue.task(task_id)
        if task is None or not task.output_path:
            return
        path = Path(task.output_path)
        if not path.is_file():
            self.show_status(
                f"That file is no longer at {path.parent} — it may have been "
                "moved or deleted.", 12000)
            return
        self._go(PAGE_EDITOR)
        self.editor_page.load_file(path, info=getattr(task, "source_info", {}) or {})
        self.show_status(f"Opened {path.name} in the editor.")

    @Slot()
    def _on_settings_saved(self) -> None:
        self.convert_page.refresh_from_config()
        self.show_status("Settings saved.")

    @Slot()
    def _on_user_agent_changed(self) -> None:
        if self.browser_page.is_available():
            self.browser_page.apply_user_agent()
            self.show_status("User-Agent updated; the browser was reloaded.")

    # ------------------------------------------------------------------ export
    @Slot(object)
    def _on_export_requested(self, payload: dict) -> None:
        if self._export_runner is not None:
            self.show_status("An export is already running.", 8000)
            return
        job = ExportJob.from_dict(payload, self.config)

        runner = ExportRunner(job, self.ffmpeg)
        runner.signals.progress.connect(self._on_export_progress)
        runner.signals.finished.connect(self._on_export_finished)
        runner.signals.failed.connect(self._on_export_failed)
        runner.signals.cancelled.connect(self._on_export_cancelled)
        self._export_runner = runner

        self.export_progress.setValue(0)
        self.export_progress.show()
        self.show_status(
            f"Exporting {job.track_count} track{'s' if job.track_count != 1 else ''}…",
            0)
        self._export_pool.start(runner)

    @Slot(float, str)
    def _on_export_progress(self, fraction: float, stage: str) -> None:
        self.export_progress.setValue(int(fraction * 1000))
        self.status_label.setText(f"{stage}…  {fraction * 100:.0f}%")

    @Slot(list)
    def _on_export_finished(self, paths: list) -> None:
        self._export_runner = None
        self.export_progress.hide()
        count = len(paths)
        self.show_status(
            f"Exported {count} file{'s' if count != 1 else ''}.", 12000)
        if paths:
            answer = QMessageBox.information(
                self, "Export complete",
                f"Wrote {count} file{'s' if count != 1 else ''}.\n\n"
                f"{Path(paths[0]).parent}",
                QMessageBox.Open | QMessageBox.Close, QMessageBox.Close,
            )
            if answer == QMessageBox.Open:
                reveal_in_file_manager(paths[0])

    @Slot(str)
    def _on_export_failed(self, message: str) -> None:
        self._export_runner = None
        self.export_progress.hide()
        self.show_status(f"Export failed: {message}", 15000)
        QMessageBox.warning(self, "Export failed", message)

    @Slot()
    def _on_export_cancelled(self) -> None:
        self._export_runner = None
        self.export_progress.hide()
        self.show_status("Export cancelled.")

    # ------------------------------------------------------------------ helpers
    def show_status(self, message: str, timeout_ms: int = 6000) -> None:
        self.status_label.setText(message)
        if timeout_ms:
            QTimer.singleShot(
                timeout_ms,
                lambda: self.status_label.setText("Ready.")
                if self.status_label.text() == message else None,
            )

    def _refresh_ffmpeg_status(self) -> None:
        if self.ffmpeg.ready:
            self.ffmpeg_status_label.setText("FFmpeg ✓")
            self.ffmpeg_status_label.setStyleSheet(f"color: {COLORS['success']};")
            self.ffmpeg_status_label.setToolTip(self.ffmpeg.ffmpeg())
        else:
            self.ffmpeg_status_label.setText("FFmpeg ✕")
            self.ffmpeg_status_label.setStyleSheet(f"color: {COLORS['accent']};")
            self.ffmpeg_status_label.setToolTip("FFmpeg is unavailable.")

    def _warn_not_ready(self) -> None:
        QMessageBox.critical(
            self, "FFmpeg unavailable",
            "audix cannot convert audio because FFmpeg is not available.\n\n"
            "Restart the application to retry the automatic setup.",
        )

    # ---------------------------------------------------------------- shutdown
    def closeEvent(self, event) -> None:  # noqa: D102, N802
        busy = self.queue.has_unfinished_work() or self._export_runner is not None
        if busy:
            answer = QMessageBox.question(
                self, "Work in progress",
                "Downloads or an export are still running.\n\n"
                "Quit anyway? Unfinished work will be cancelled.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return

        self.show_status("Shutting down…", 0)
        if self._export_runner is not None:
            self._export_runner.cancel()
        self._export_pool.waitForDone(4000)
        self.editor_page.shutdown()
        self.browser_page.shutdown()
        self.queue.shutdown()
        decoder_module.cleanup_orphans()
        self.config.save()
        log.info("Shutdown complete")
        super().closeEvent(event)


def _app_icon() -> QIcon:
    """Generated icon: a waveform silhouette in the brand cobalt."""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(COLORS["bg"]))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(2, 2, size - 4, size - 4, 14, 14)

    painter.setBrush(QColor(COLORS["primary"]))
    for x, height in ((14, 14), (22, 30), (30, 44), (38, 26), (46, 16)):
        y = (size - height) // 2
        painter.drawRoundedRect(x, y, 5, height, 2, 2)

    painter.end()
    return QIcon(pixmap)
