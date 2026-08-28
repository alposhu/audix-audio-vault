"""Tab 3 — Queue & Active Downloads.

Shows every queued task with live progress, speed and ETA, plus queue-wide controls
(pause, cancel all, clear finished) and a summary strip covering active threads and
aggregate throughput.

Rows are updated in place from ``task_updated`` signals; the list is only rebuilt
when tasks are added or removed, so a busy queue does not thrash the widget tree.
"""
from __future__ import annotations

import logging
from typing import Dict

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget,
)

from audix.core.queue_manager import QueueManager
from audix.core.task import TaskState
from audix.ui.widgets.download_item import DownloadItemWidget, reveal_in_file_manager
from audix.utils import humanize

log = logging.getLogger("audix.ui.queue")


class QueueTab(QWidget):
    """Live view of the download queue."""

    #: A finished item was sent to the editor. Routed by the main window so the
    #: queue never needs a reference to the editor page.
    edit_requested = Signal(str)

    def __init__(self, queue: QueueManager, config, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.queue = queue
        self.config = config
        self._rows: Dict[str, QListWidgetItem] = {}
        self._widgets: Dict[str, DownloadItemWidget] = {}

        self._build_ui()

        self.queue.task_added.connect(self._on_task_added)
        self.queue.task_updated.connect(self._on_task_updated)
        self.queue.task_finished.connect(self._on_task_finished)
        self.queue.stats_changed.connect(self._on_stats_changed)

    # ------------------------------------------------------------------ layout
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)

        header = QHBoxLayout()
        heading = QVBoxLayout()
        title = QLabel("Queue & Active Downloads")
        title.setProperty("role", "title")
        heading.addWidget(title)
        self.summary_label = QLabel("Queue is empty.")
        self.summary_label.setProperty("role", "subtitle")
        heading.addWidget(self.summary_label)
        header.addLayout(heading, 1)

        self.pause_button = QPushButton("Pause Queue")
        self.pause_button.setMinimumWidth(130)
        self.pause_button.clicked.connect(self._toggle_pause)
        header.addWidget(self.pause_button, 0, Qt.AlignTop)

        self.cancel_all_button = QPushButton("Cancel All")
        self.cancel_all_button.setProperty("variant", "danger")
        self.cancel_all_button.clicked.connect(self.queue.cancel_all)
        header.addWidget(self.cancel_all_button, 0, Qt.AlignTop)

        self.clear_button = QPushButton("Clear Finished")
        self.clear_button.setProperty("variant", "ghost")
        self.clear_button.clicked.connect(self._clear_finished)
        header.addWidget(self.clear_button, 0, Qt.AlignTop)

        root.addLayout(header)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.NoSelection)
        self.list_widget.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list_widget.setUniformItemSizes(False)
        self.list_widget.itemDoubleClicked.connect(self._on_double_click)
        root.addWidget(self.list_widget, 1)

        self.empty_label = QLabel(
            "Nothing queued yet.\n\n"
            "Use the Quick Convert tab to paste a link, or browse YouTube in the "
            "Browser tab and send a video here."
        )
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setProperty("role", "hint")
        root.addWidget(self.empty_label, 1)

        footer = QHBoxLayout()
        self.throughput_label = QLabel("")
        self.throughput_label.setProperty("role", "hint")
        footer.addWidget(self.throughput_label, 1)
        self.concurrency_label = QLabel("")
        self.concurrency_label.setProperty("role", "hint")
        footer.addWidget(self.concurrency_label, 0)
        root.addLayout(footer)

        self._update_empty_state()
        self._refresh_summary()

    # --------------------------------------------------------------- callbacks
    @Slot(str)
    def _on_task_added(self, task_id: str) -> None:
        task = self.queue.task(task_id)
        if task is None or task_id in self._rows:
            return

        widget = DownloadItemWidget(task)
        widget.cancel_requested.connect(self.queue.cancel)
        widget.retry_requested.connect(self.queue.retry)
        widget.remove_requested.connect(self._remove_task)
        widget.edit_requested.connect(self.edit_requested)

        item = QListWidgetItem()
        item.setSizeHint(widget.sizeHint())
        item.setData(Qt.UserRole, task_id)

        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, widget)
        self._rows[task_id] = item
        self._widgets[task_id] = widget
        self._update_empty_state()

    @Slot(str)
    def _on_task_updated(self, task_id: str) -> None:
        task = self.queue.task(task_id)
        widget = self._widgets.get(task_id)
        if task is None or widget is None:
            return
        widget.update_from(task)
        self._refresh_summary()

    @Slot(str, bool, str)
    def _on_task_finished(self, task_id: str, success: bool, message: str) -> None:
        self._on_task_updated(task_id)
        if success:
            log.info("Completed: %s", message)

    @Slot(int, int, int)
    def _on_stats_changed(self, active: int, pending: int, completed: int) -> None:
        self._refresh_summary(active, pending, completed)

    # ----------------------------------------------------------------- actions
    def _toggle_pause(self) -> None:
        paused = self.queue.toggle_paused()
        self.pause_button.setText("Resume Queue" if paused else "Pause Queue")
        self.pause_button.setProperty("variant", "primary" if paused else "")
        self.pause_button.style().unpolish(self.pause_button)
        self.pause_button.style().polish(self.pause_button)
        self._refresh_summary()

    def _clear_finished(self) -> None:
        for task_id in self.queue.clear_finished():
            self._drop_row(task_id)
        self._update_empty_state()
        self._refresh_summary()

    @Slot(str)
    def _remove_task(self, task_id: str) -> None:
        task = self.queue.task(task_id)
        if task is not None and task.state.is_active:
            # Cancel now; the row disappears once the worker unwinds.
            self.queue.cancel(task_id)
            return
        self.queue.remove(task_id)
        self._drop_row(task_id)
        self._update_empty_state()

    def _drop_row(self, task_id: str) -> None:
        item = self._rows.pop(task_id, None)
        self._widgets.pop(task_id, None)
        if item is None:
            return
        row = self.list_widget.row(item)
        if row >= 0:
            self.list_widget.takeItem(row)

    def _on_double_click(self, item: QListWidgetItem) -> None:
        task_id = item.data(Qt.UserRole)
        task = self.queue.task(task_id) if task_id else None
        if task and task.state == TaskState.COMPLETED and task.output_path:
            reveal_in_file_manager(task.output_path)

    # --------------------------------------------------------------- rendering
    def _update_empty_state(self) -> None:
        empty = self.list_widget.count() == 0
        self.list_widget.setVisible(not empty)
        self.empty_label.setVisible(empty)
        self.cancel_all_button.setEnabled(not empty)
        self.clear_button.setEnabled(not empty)

    def _refresh_summary(self, active: int = None, pending: int = None,
                         completed: int = None) -> None:
        if active is None or pending is None or completed is None:
            active, pending, completed = self.queue.counts()

        tasks = self.queue.tasks()
        failed = sum(1 for t in tasks if t.state == TaskState.FAILED)

        if not tasks:
            self.summary_label.setText("Queue is empty.")
        else:
            parts = [f"{active} active", f"{pending} waiting", f"{completed} done"]
            if failed:
                parts.append(f"{failed} failed")
            state = " · ".join(parts)
            if self.queue.is_paused:
                state = f"PAUSED — {state}"
            self.summary_label.setText(state)

        total_speed = sum(
            t.speed or 0.0 for t in tasks if t.state == TaskState.DOWNLOADING
        )
        self.throughput_label.setText(
            f"Combined throughput: {humanize.format_speed(total_speed)}"
            if total_speed else ""
        )
        self.concurrency_label.setText(
            f"Worker threads: {active}/{self.queue.max_concurrent}"
        )
