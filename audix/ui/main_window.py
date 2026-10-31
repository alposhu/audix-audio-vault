"""The application shell: the tuning dial above a stacked workspace.

Cross-surface flows are wired here so no page needs a reference to any other:

* Browse and the Queue hand over tracks, and this window turns them into downloads
  using the shared output settings.
* A finished download offers Edit, which loads it into the editor with its
  original yt-dlp metadata, so chapters and artwork come along.
* Settings pushes new defaults to every page through the shared output settings.

Notes that once took a modal dialog or a status bar are toasts now, so nothing here
stops the user to report something that does not need an answer.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QThreadPool, Slot
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow, QMessageBox, QStackedWidget, QVBoxLayout, QWidget

from audix import __version__
from audix.core.audio import decoder as decoder_module
from audix.core.download_manager import DownloadManager
from audix.core.downloader import MediaEntry, Scope
from audix.core.export import ExportJob, ExportRunner
from audix.core.ffmpeg_manager import FFmpegManager
from audix.core.history import DownloadHistory
from audix.core.link_queue import LinkAdded, LinkQueue
from audix.core.task import TaskState
from audix.ui.desktop import reveal_in_file_manager
from audix.ui.output_prefs import OutputPrefs
from audix.ui.tabs.browser_tab import BrowserTab
from audix.ui.tabs.downloads_tab import FAILED, DownloadsTab
from audix.ui.tabs.editor_tab import EditorTab
from audix.ui.tabs.queue_tab import QueueTab
from audix.ui.tabs.settings_tab import SettingsTab
from audix.ui.thumbnails import Thumbnails
from audix.ui.tokens import COLORS
from audix.ui.widgets.dial import Station, TuningDial
from audix.ui.widgets.toast import Toasts
from audix.utils import humanize

log = logging.getLogger("audix.ui.window")

PAGE_BROWSER, PAGE_QUEUE, PAGE_DOWNLOADS, PAGE_EDITOR, PAGE_SETTINGS = range(5)

STATIONS = [
    Station("browser", "Browse", "Find something on YouTube"),
    Station("queue", "Queue", "Choose what to download"),
    Station("downloads", "Downloads", "Everything running and finished"),
    Station("editor", "Edit", "Trim, level, and split audio"),
    Station("settings", "Settings", "Defaults, sign-in, and dependencies"),
]


class MainWindow(QMainWindow):
    """audix main window."""

    def __init__(self, config, ffmpeg: FFmpegManager) -> None:
        super().__init__()
        self.config = config
        self.ffmpeg = ffmpeg

        self.history = DownloadHistory()
        self.prefs = OutputPrefs(config, parent=self)
        self.thumbnails = Thumbnails(parent=self)
        self.downloads = DownloadManager(ffmpeg, config, parent=self)
        self.link_queue = LinkQueue(config, self.history, parent=self)

        self._export_pool = QThreadPool(self)
        self._export_pool.setMaxThreadCount(1)      # exports are IO/CPU heavy
        self._export_runner: Optional[ExportRunner] = None
        self._unseen = 0
        self._unseen_failed = False

        self.setWindowTitle("audix")
        self.setWindowIcon(_app_icon())
        self.resize(1320, 860)
        self.setMinimumSize(1040, 680)

        decoder_module.cleanup_orphans()

        self._build_shell()
        self._connect_signals()
        self._install_shortcuts()

        self.downloads.restore(self.history.tasks())
        self._refresh_badges()

        log.info("Main window ready (v%s)", __version__)

    # ------------------------------------------------------------------ layout
    def _build_shell(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.dial = TuningDial(STATIONS)
        layout.addWidget(self.dial)

        self.pages = QStackedWidget()
        self.browser_page = BrowserTab(self.config, self.prefs, self.thumbnails, self.history)
        self.queue_page = QueueTab(self.link_queue, self.prefs, self.thumbnails, self.config)
        self.downloads_page = DownloadsTab(self.downloads, self.history, self.prefs,
                                           self.thumbnails)
        self.editor_page = EditorTab(self.config, self.ffmpeg)
        self.settings_page = SettingsTab(self.config, self.prefs, self.ffmpeg)

        for page in (self.browser_page, self.queue_page, self.downloads_page,
                     self.editor_page, self.settings_page):
            self.pages.addWidget(page)
        layout.addWidget(self.pages, 1)

        self.setCentralWidget(central)
        self.toasts = Toasts(central)
        self.dial.changed.connect(self.pages.setCurrentIndex)
        self.dial.signal.clicked.connect(lambda: self._go(PAGE_DOWNLOADS))
        self.dial.install_shortcuts(self)
        self._go(PAGE_QUEUE, animate=False)

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+Q"), self, self.close)

    # ----------------------------------------------------------------- signals
    def _connect_signals(self) -> None:
        self.browser_page.download_requested.connect(self._on_download_from_browser)
        self.browser_page.queue_requested.connect(self._on_queue_from_browser)
        self.browser_page.link_requested.connect(self._on_link_from_browser)
        self.browser_page.list_requested.connect(self._on_list_from_browser)
        self.browser_page.toast.connect(self.show_toast)

        self.queue_page.download_requested.connect(self._on_download_from_queue)
        self.queue_page.browse_requested.connect(self._open_in_browser)
        self.queue_page.search_requested.connect(self._search_in_browser)
        self.queue_page.toast.connect(self.show_toast)

        self.link_queue.changed.connect(self._refresh_badges)
        self.link_queue.link_added.connect(self._on_link_added)
        self.link_queue.link_failed.connect(self._on_link_failed)

        self.downloads.stats_changed.connect(lambda *_counts: self._refresh_badges())
        self.downloads.task_finished.connect(self._on_task_finished)

        self.downloads_page.edit_requested.connect(self._on_edit_requested)
        self.downloads_page.browse_requested.connect(self._open_in_browser)
        self.downloads_page.queue_requested.connect(lambda: self._go(PAGE_QUEUE))
        self.downloads_page.attention_changed.connect(self._on_attention_changed)
        self.downloads_page.activity.connect(self.dial.signal.set_activity)

        self.editor_page.export_requested.connect(self._on_export_requested)

        self.prefs.changed.connect(self._on_prefs_changed)
        self.settings_page.session_clear_requested.connect(self.browser_page.clear_session)
        self.settings_page.user_agent_changed.connect(self._on_user_agent_changed)

    # --------------------------------------------------------------- navigation
    def _go(self, index: int, animate: bool = True) -> None:
        self.dial.set_current(index, animate)
        self.pages.setCurrentIndex(index)

    def show_toast(self, message: str, tone: str = "info") -> None:
        self.toasts.show(message, tone)

    # ------------------------------------------------------------- starting work
    def _start(self, entries: List[MediaEntry]) -> int:
        """Turn tracks into downloads. Returns how many actually started."""
        if not entries:
            return 0
        self.downloads.add_tasks(self.prefs.make_tasks(entries))
        return len(entries)

    def _can_start(self) -> bool:
        """Check everything that could stop a download, before any track moves."""
        if not self.ffmpeg.ready:
            QMessageBox.critical(
                self, "FFmpeg unavailable",
                "audix cannot convert audio because FFmpeg is not available.\n\n"
                "Restart the application to retry the automatic setup.",
            )
            return False
        try:
            Path(self.config.output_dir).expanduser().mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.toasts.show(f"That folder cannot be written to: {exc}", "error",
                             "Open Settings", lambda: self._go(PAGE_SETTINGS))
            return False
        return True

    @Slot(list)
    def _on_download_from_queue(self, item_ids: list) -> None:
        if not item_ids or not self._can_start():
            return
        started = self._start(self.link_queue.take(item_ids))
        if self.link_queue.is_empty():
            self._go(PAGE_DOWNLOADS)
        else:
            self.toasts.show(f"{humanize.count(started, 'track')} started.", "info",
                             "View", lambda: self._go(PAGE_DOWNLOADS))

    @Slot(object)
    def _on_download_from_browser(self, entry: MediaEntry) -> None:
        if not self._can_start():
            return
        self._start([entry])
        self.toasts.show(f"Downloading {humanize.elide(entry.title, 60)}", "info",
                         "View", lambda: self._go(PAGE_DOWNLOADS))

    @Slot(object)
    def _on_queue_from_browser(self, entry: MediaEntry) -> None:
        if self.link_queue.add_entry(entry):
            self.toasts.show(f"Added to Queue: {humanize.elide(entry.title, 60)}", "info",
                             "View", lambda: self._go(PAGE_QUEUE))

    @Slot(str)
    def _on_link_from_browser(self, url: str) -> None:
        self.link_queue.add_link(url)

    @Slot(str)
    def _on_list_from_browser(self, url: str) -> None:
        self.link_queue.add_link(url, Scope.WHOLE_LIST)
        self._go(PAGE_QUEUE)

    @Slot(str)
    def _open_in_browser(self, url: str) -> None:
        self._go(PAGE_BROWSER)
        if url and self.browser_page.is_available():
            self.browser_page.navigate(url)

    @Slot(str)
    def _search_in_browser(self, query: str) -> None:
        self._go(PAGE_BROWSER)
        if self.browser_page.is_available():
            self.browser_page.search(query)

    # ------------------------------------------------------------------ feedback
    @Slot(object)
    def _on_link_added(self, added: LinkAdded) -> None:
        on_queue = self.pages.currentIndex() == PAGE_QUEUE
        title = humanize.elide(added.title, 50)
        if added.parent_list is not None:
            kind = "Mix" if added.parent_list.is_mix else "playlist"
            url = added.parent_list.url
            self.toasts.show(
                f"Added just this video. It was playing from a {kind}.", "info",
                f"Add the {kind}",
                lambda: self.link_queue.add_link(url, Scope.WHOLE_LIST), 9000)
        elif not on_queue:
            summary = (f"{humanize.count(added.count, 'track')} from {title}"
                       if added.is_playlist else title)
            self.toasts.show(f"Added to Queue: {summary}", "info", "View",
                             lambda: self._go(PAGE_QUEUE))

    @Slot(str, str)
    def _on_link_failed(self, _url: str, message: str) -> None:
        self.toasts.show(message, "error", "View", lambda: self._go(PAGE_QUEUE), 9000)

    @Slot(str, bool, str)
    def _on_task_finished(self, task_id: str, success: bool, message: str) -> None:
        if self.pages.currentIndex() == PAGE_DOWNLOADS:
            return
        task = self.downloads.task(task_id)
        title = humanize.elide(task.title if task else "A track", 50)
        if task is not None and task.state == TaskState.FAILED:
            self.toasts.show(f"Could not download {title}. {message}", "error", "View",
                             lambda: self._show_failed(), 9000)
        elif success and not self.downloads.unfinished():
            folder = task.output_path if task else ""
            self.toasts.show("Every download has finished.", "success", "Show files",
                             lambda: reveal_in_file_manager(folder))

    def _show_failed(self) -> None:
        self._go(PAGE_DOWNLOADS)
        self.downloads_page.show_filter(FAILED)

    @Slot(int, bool)
    def _on_attention_changed(self, count: int, failed: bool) -> None:
        self._unseen = count
        self._unseen_failed = failed
        self._refresh_badges()

    def _refresh_badges(self) -> None:
        items = len(self.link_queue.items())
        self.dial.set_badge(PAGE_QUEUE, str(items) if items else "")
        active, pending, _completed = self.downloads.counts()
        running = active + pending
        # The count says how much is going on; the lamp, kept apart from it, says that
        # something changed. A busy count must never hide an unseen failure.
        lamp = ""
        if self._unseen:
            lamp = COLORS["accent" if self._unseen_failed else "success"]
        self.dial.set_badge(PAGE_DOWNLOADS,
                            str(running or self._unseen) if running or self._unseen else "",
                            lamp)

    # ------------------------------------------------------------------- editing
    @Slot(str)
    def _on_edit_requested(self, task_id: str) -> None:
        """Open a finished download in the editor, carrying its metadata across."""
        task = self.downloads.task(task_id)
        if task is None or not task.output_path:
            return
        path = Path(task.output_path)
        if not path.is_file():
            self.show_toast(
                f"That file is no longer in {path.parent}. It may have been moved "
                "or deleted.", "error")
            return
        self._go(PAGE_EDITOR)
        self.editor_page.load_file(path, info=getattr(task, "source_info", {}) or {})

    @Slot()
    def _on_prefs_changed(self) -> None:
        self.downloads.set_concurrency(self.prefs.parallel)

    @Slot()
    def _on_user_agent_changed(self) -> None:
        if self.browser_page.is_available():
            self.browser_page.apply_user_agent()

    # ------------------------------------------------------------------ export
    @Slot(object)
    def _on_export_requested(self, payload: dict) -> None:
        if self._export_runner is not None:
            self.show_toast("An export is already running.")
            return
        job = ExportJob.from_dict(payload, self.config)

        runner = ExportRunner(job, self.ffmpeg)
        runner.signals.progress.connect(self._on_export_progress)
        runner.signals.finished.connect(self._on_export_finished)
        runner.signals.failed.connect(self._on_export_failed)
        runner.signals.cancelled.connect(self._on_export_cancelled)
        self._export_runner = runner

        self.editor_page.set_export_progress(0.0, "Exporting")
        self._export_pool.start(runner)

    @Slot(float, str)
    def _on_export_progress(self, fraction: float, stage: str) -> None:
        self.editor_page.set_export_progress(fraction, stage)

    @Slot(list)
    def _on_export_finished(self, paths: list) -> None:
        self._export_runner = None
        self.editor_page.set_export_progress(None, "")
        count = len(paths)
        if paths:
            self.toasts.show(f"Exported {humanize.count(count, 'file')}.", "success",
                             "Show files", lambda: reveal_in_file_manager(paths[0]), 12000)

    @Slot(str)
    def _on_export_failed(self, message: str) -> None:
        self._export_runner = None
        self.editor_page.set_export_progress(None, "")
        self.toasts.show(f"The export failed. {message}", "error", timeout=15000)

    @Slot()
    def _on_export_cancelled(self) -> None:
        self._export_runner = None
        self.editor_page.set_export_progress(None, "")
        self.show_toast("Export cancelled.")

    # ---------------------------------------------------------------- shutdown
    def closeEvent(self, event) -> None:  # noqa: D102, N802
        unfinished = self.downloads.unfinished()
        if unfinished or self._export_runner is not None:
            parts = []
            if unfinished:
                parts.append(f"{humanize.count(len(unfinished), 'download')} still "
                             "unfinished. They go back to your Queue, ready to run again.")
            if self._export_runner is not None:
                parts.append("An export is running and will be cancelled.")
            answer = QMessageBox.question(
                self, "Quit audix?", "\n\n".join(parts),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return

        if self._export_runner is not None:
            self._export_runner.cancel()
        self._export_pool.waitForDone(4000)
        self.editor_page.shutdown()
        self.browser_page.shutdown()
        self.link_queue.return_entries(task.entry for task in unfinished)
        self.downloads.shutdown()
        self.link_queue.shutdown()
        decoder_module.cleanup_orphans()
        self.config.save()
        log.info("Shutdown complete")
        super().closeEvent(event)


def _app_icon() -> QIcon:
    """The shared audix mark. Same drawing as the .ico and the repo logo."""
    from audix.ui.branding import app_icon

    return app_icon()
