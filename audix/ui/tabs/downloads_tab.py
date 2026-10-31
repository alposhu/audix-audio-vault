"""Downloads: every item, what it is doing, and everything audix knows about it.

The list shows one row per item in fixed columns, so a number changing never moves
anything else. Selecting a row opens the inspector over the right of the list,
leaving every column it does not cover exactly where it was. It shows the signal path
through each stage, the stream that was fetched, where the file went, and how long
each step took.

Rows rank by what needs attention: running work first, then what is waiting, then
failures, then the finished. Anything that finishes or fails while you are on
another page stays lit until you have come here and seen it.

Tasks update far more often than a person can read, and a dozen parallel downloads
could easily spend the whole UI thread on repaints, so changes are collected and
applied together a few times a second.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPointF, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMenu, QPushButton, QScrollArea, QStackedWidget, QStyle, QVBoxLayout,
    QWidget,
)

from audix.core import formats
from audix.core.download_manager import DownloadManager
from audix.core.history import DownloadHistory
from audix.core.task import DownloadTask, TaskState
from audix.ui import icons, motion, paint
from audix.ui.desktop import open_file, reveal_in_file_manager
from audix.ui.output_prefs import OutputPrefs
from audix.ui.theme import mono_font, ui_font
from audix.ui.thumbnails import Thumbnails
from audix.ui.tokens import COLORS, SPACE, STATE_COLORS, TYPE
from audix.ui.widgets.controls import IconKey, Lamp, ParallelCombo, TextKey, add_clear_key
from audix.ui.widgets.row_list import ACTION_SIZE, RowDelegate, RowList
from audix.ui.widgets.well import Well
from audix.utils import humanize

log = logging.getLogger("audix.ui.downloads")

TASK_ROLE = Qt.UserRole + 1

ROW_HEIGHT = 60
THUMB_WIDTH, THUMB_HEIGHT = 64, 36
INSPECTOR_WIDTH = 320

THUMB_PREVIEW_HEIGHT = 136

#: Below this page width the control row drops its parallelism selector.
CONTROLS_FULL_WIDTH = 1180

#: How often collected task updates reach the screen.
REFRESH_MS = 120

ALL, ACTIVE, WAITING, FINISHED, FAILED = "all", "active", "waiting", "finished", "failed"

FILTERS = ((ALL, "All"), (ACTIVE, "Running"), (WAITING, "Waiting"),
           (FINISHED, "Finished"), (FAILED, "Failed"))


def _bucket(task: DownloadTask) -> str:
    state = task.state
    if state.is_active:
        return ACTIVE
    if state in (TaskState.PENDING, TaskState.PAUSED):
        return WAITING
    if state == TaskState.COMPLETED:
        return FINISHED
    return FAILED


def _rank(task: DownloadTask, waiting_order: Dict[str, int]) -> tuple:
    """Running, then paused, waiting, failed, and finished, newest finished first."""
    state = task.state
    if state.is_active:
        return (0, task.started_at or 0)
    if state == TaskState.PAUSED:
        return (1, task.added_at)
    if state == TaskState.PENDING:
        return (2, waiting_order.get(task.id, 0))
    if state in (TaskState.FAILED, TaskState.CANCELLED):
        return (3, -(task.finished_at or 0))
    return (4, -(task.finished_at or 0))


class DownloadsModel(QAbstractListModel):
    """Tasks after filtering and ranking, refreshed in batches."""

    def __init__(self, manager: DownloadManager, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.filter = ALL
        self.search = ""
        self._ids: List[str] = []
        self._dirty: Set[str] = set()
        self._rebuild_needed = False
        self.unseen: Set[str] = set()

        manager.task_added.connect(self._mark_structure)
        manager.task_removed.connect(self._mark_structure)
        manager.task_updated.connect(self._mark_dirty)

    # -------------------------------------------------------------------- reads
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt override
        return 0 if parent.isValid() else len(self._ids)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._ids):
            return None
        task = self.manager.task(self._ids[index.row()])
        if task is None:
            return None
        if role == TASK_ROLE:
            return task
        if role in (Qt.DisplayRole, Qt.AccessibleTextRole):
            return f"{task.title}, {task.state.value}"
        return None

    def task_at(self, index: QModelIndex) -> Optional[DownloadTask]:
        return self.data(index, TASK_ROLE)

    def index_of(self, task_id: str) -> QModelIndex:
        try:
            return self.index(self._ids.index(task_id))
        except ValueError:
            return QModelIndex()

    # ------------------------------------------------------------------ updates
    def _mark_structure(self, _task_id: str) -> None:
        self._rebuild_needed = True

    def _mark_dirty(self, task_id: str) -> None:
        self._dirty.add(task_id)

    def set_view(self, bucket: str, search: str) -> None:
        self.filter = bucket
        self.search = search.casefold().strip()
        self.flush(force=True)

    def flush(self, force: bool = False) -> bool:
        """Apply collected changes. Returns whether anything changed."""
        had_work = bool(self._dirty) or self._rebuild_needed or force
        if not had_work:
            return False
        order = self._ranked_ids()
        if force or self._rebuild_needed or order != self._ids:
            self.layoutAboutToBeChanged.emit()
            self._ids = order
            self.layoutChanged.emit()
        elif self._ids:
            positions = {task_id: row for row, task_id in enumerate(self._ids)}
            for task_id in self._dirty:
                row = positions.get(task_id)
                if row is not None:
                    index = self.index(row)
                    self.dataChanged.emit(index, index)
        self._dirty.clear()
        self._rebuild_needed = False
        return True

    def repaint_url(self, url: str) -> None:
        for row, task_id in enumerate(self._ids):
            task = self.manager.task(task_id)
            if task is not None and task.entry.thumbnail_url == url:
                index = self.index(row)
                self.dataChanged.emit(index, index)

    def _ranked_ids(self) -> List[str]:
        waiting = {task_id: position
                   for position, task_id in enumerate(self.manager.waiting_order())}
        tasks = [task for task in self.manager.tasks() if self._passes(task)]
        tasks.sort(key=lambda task: _rank(task, waiting))
        return [task.id for task in tasks]

    def _passes(self, task: DownloadTask) -> bool:
        if self.filter != ALL and _bucket(task) != self.filter:
            return False
        if self.search:
            text = f"{task.title} {task.entry.uploader} {task.entry.playlist_title}".casefold()
            return self.search in text
        return True


@dataclass
class Columns:
    """Where each column sits for a given row width. Shared with the header."""

    state: QRectF
    thumb: QRectF
    title: QRectF
    ladder: QRectF
    percent: QRectF
    size: Optional[QRectF]
    speed: Optional[QRectF]
    eta: Optional[QRectF]
    actions: QRectF


def columns_for(rect: QRectF, covered: float = 0.0) -> Columns:
    """Lay out one row. Narrow windows give up speed and time first, then size.

    ``covered`` is how much of the right edge a panel is hiding. Columns never move
    for it, but one it would cut through is left out instead of showing half a figure.
    """
    top, height = rect.top(), rect.height()
    width = rect.width()
    show_speed = width >= 900
    show_size = width >= 760

    def cell(x: float, w: float) -> QRectF:
        return QRectF(x, top, w, height)

    right = rect.right() - 8
    actions = cell(right - (ACTION_SIZE + 2) * 3, (ACTION_SIZE + 2) * 3)
    x = actions.left() - 10

    eta = speed = size = None
    if show_speed:
        eta = cell(x - 58, 58)
        speed = cell(eta.left() - 88, 84)
        x = speed.left() - 4
    if show_size:
        size = cell(x - 124, 120)
        x = size.left() - 4
    percent = cell(x - 42, 38)
    ladder = cell(percent.left() - 124, 118)

    state = cell(rect.left() + 12, 112)
    thumb = QRectF(state.right() + 8, top + (height - THUMB_HEIGHT) / 2,
                   THUMB_WIDTH, THUMB_HEIGHT)
    title = cell(thumb.right() + 12, ladder.left() - thumb.right() - 28)

    edge = rect.right() - covered

    def uncovered(column: Optional[QRectF]) -> Optional[QRectF]:
        return column if column is not None and column.right() <= edge else None

    return Columns(state, thumb, title, ladder, percent, uncovered(size), uncovered(speed),
                   uncovered(eta), actions)


def row_actions(task: DownloadTask) -> List[tuple]:
    """(zone, icon) pairs, left to right, for what can be done to a task right now."""
    state = task.state
    if state == TaskState.COMPLETED:
        return [("open", "play"), ("folder", "folder"), ("edit", "wave")]
    if state == TaskState.PAUSED:
        return [("resume", "play"), ("cancel", "close")]
    if state == TaskState.PENDING:
        return [("top", "top"), ("pause", "pause"), ("cancel", "close")]
    if state in (TaskState.FAILED, TaskState.CANCELLED):
        return [("retry", "retry"), ("remove", "close")]
    if state.can_pause:
        return [("pause", "pause"), ("cancel", "close")]
    return [("cancel", "close")]


ACTION_TIPS = {
    "open": "Open the file",
    "folder": "Show in folder",
    "edit": "Open in the editor",
    "resume": "Resume from where it stopped",
    "pause": "Pause, keeping what has been downloaded",
    "cancel": "Stop this download and delete what it fetched",
    "top": "Move to the front of the line",
    "retry": "Try this download again",
    "remove": "Remove from this list",
}


class DownloadsDelegate(RowDelegate):
    """Paints one task across the fixed columns."""

    def __init__(self, thumbnails: Thumbnails, model: DownloadsModel, parent=None) -> None:
        super().__init__(parent)
        self.thumbnails = thumbnails
        self.model_ref = model
        self.phase = 0
        self.selected_id = ""
        self.covered = 0.0
        self._title_font = ui_font(TYPE["body"][0], 600)
        self._sub_font = ui_font(TYPE["small"][0])
        self._state_font = ui_font(TYPE["small"][0], 500)
        self._mono_font = mono_font(TYPE["small"][0])

    def sizeHint(self, option, index):  # noqa: N802 - Qt override
        size = super().sizeHint(option, index)
        size.setHeight(ROW_HEIGHT)
        return size

    def zones(self, index, rect: QRectF) -> Dict[str, QRectF]:
        task = index.data(TASK_ROLE)
        if task is None:
            return {}
        area = columns_for(rect).actions
        mid = rect.center().y()
        step = ACTION_SIZE + 2
        keys = row_actions(task)
        zones = {}
        for position, (zone, _icon) in enumerate(keys):
            x = area.right() - step * (len(keys) - position)
            zones[zone] = QRectF(x, mid - ACTION_SIZE / 2, ACTION_SIZE, ACTION_SIZE)
        return zones

    def zone_tooltip(self, index, zone: str) -> str:
        return ACTION_TIPS.get(zone, "")

    def row_tooltip(self, index) -> str:
        task = index.data(TASK_ROLE)
        if task is None:
            return ""
        return task.message if task.state == TaskState.FAILED else task.title

    def paint(self, painter: QPainter, option, index) -> None:
        task: DownloadTask = index.data(TASK_ROLE)
        if task is None:
            return
        rect = QRectF(option.rect)
        hover = bool(option.state & QStyle.State_MouseOver)
        unseen = task.id in self.model_ref.unseen

        painter.save()
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        if task.id == self.selected_id:
            painter.fillRect(rect, QColor(COLORS["surface_2"]))
        elif unseen:
            painter.fillRect(rect, _wash(STATE_COLORS[task.state.value]))
        elif hover:
            painter.fillRect(rect, QColor(COLORS["surface"]))
        painter.fillRect(QRectF(rect.left(), rect.bottom(), rect.width(), 1),
                         QColor(COLORS["surface"]))

        cols = columns_for(rect, self.covered)
        self._paint_state(painter, cols.state, task)
        paint.draw_thumbnail(painter, cols.thumb, self.thumbnails.get(task.entry.thumbnail_url))
        self._paint_title(painter, cols.title, task)
        self._paint_progress(painter, cols, task)
        self._paint_figures(painter, cols, task)

        zones = self.zones(index, rect)
        for zone, icon_name in row_actions(task):
            self.paint_action(painter, index, zones[zone], zone, icon_name, hover,
                              danger=zone in ("cancel", "remove"))

        if option.state & QStyle.State_HasFocus:
            painter.setPen(QColor(COLORS["primary"]))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect.adjusted(0.5, 0.5, -1.5, -1.5))
        painter.restore()

    def _paint_state(self, painter: QPainter, rect: QRectF, task: DownloadTask) -> None:
        color = STATE_COLORS[task.state.value]
        lit = task.state not in (TaskState.PENDING, TaskState.PAUSED, TaskState.CANCELLED)
        paint.draw_lamp(painter, QPointF(rect.left() + 6, rect.center().y()), color, lit)
        painter.setFont(self._state_font)
        painter.setPen(QColor(COLORS["ink"] if lit else COLORS["muted"]))
        painter.drawText(rect.adjusted(20, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter,
                         task.state.value)

    def _paint_title(self, painter: QPainter, rect: QRectF, task: DownloadTask) -> None:
        width = int(rect.width())
        mid = rect.center().y()
        painter.setFont(self._title_font)
        painter.setPen(QColor(COLORS["ink"]))
        painter.drawText(QRectF(rect.left(), mid - 19, width, 19),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(task.title, Qt.ElideRight, width))

        painter.setFont(self._sub_font)
        line = _subtitle(task)
        failed = task.state == TaskState.FAILED
        painter.setPen(QColor(COLORS["accent" if failed else "faint"]))
        painter.drawText(QRectF(rect.left(), mid + 1, width, 18),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(line, Qt.ElideRight, width))

    def _paint_progress(self, painter: QPainter, cols: Columns, task: DownloadTask) -> None:
        mid = cols.ladder.center().y()
        bar = QRectF(cols.ladder.left(), mid - 6, cols.ladder.width(), 12)
        color = STATE_COLORS[task.state.value]
        if task.state == TaskState.RESOLVING:
            paint.draw_ladder(painter, bar, 0, color, phase=self.phase)
            text = ""
        elif task.state == TaskState.PENDING:
            paint.draw_ladder(painter, bar, 0, color)
            text = ""
        else:
            paint.draw_ladder(painter, bar, task.progress, color)
            text = f"{task.progress * 100:.0f}%"
        painter.setFont(self._mono_font)
        painter.setPen(QColor(COLORS["muted"]))
        painter.drawText(cols.percent, Qt.AlignRight | Qt.AlignVCenter, text)

    def _paint_figures(self, painter: QPainter, cols: Columns, task: DownloadTask) -> None:
        painter.setFont(self._mono_font)
        running = task.state == TaskState.DOWNLOADING
        painter.setPen(QColor(COLORS["muted"]))
        if cols.size is not None:
            painter.drawText(cols.size, Qt.AlignRight | Qt.AlignVCenter, _size_text(task))
        if cols.speed is not None:
            painter.drawText(cols.speed, Qt.AlignRight | Qt.AlignVCenter,
                             humanize.format_speed(task.speed) if running else "—")
        if cols.eta is not None:
            painter.drawText(cols.eta, Qt.AlignRight | Qt.AlignVCenter,
                             humanize.format_eta(task.eta) if running and task.eta else "—")


def _wash(color: str) -> QColor:
    wash = QColor(color)
    wash.setAlpha(26)
    return wash


def _subtitle(task: DownloadTask) -> str:
    state = task.state
    if state == TaskState.FAILED:
        return task.message or "Failed"
    if state == TaskState.COMPLETED:
        saved = Path(task.output_path).parent.name if task.output_path else ""
        parts = [_spec(task), f"in {saved}" if saved else "",
                 humanize.format_ago(task.finished_at)]
        return " · ".join(part for part in parts if part)
    if task.message and state != TaskState.CANCELLED:
        return task.message
    parts = [task.entry.uploader, task.entry.playlist_title, _spec(task)]
    return " · ".join(part for part in parts if part)


def _spec(task: DownloadTask) -> str:
    fmt = formats.get(task.audio_format)
    if fmt.lossless:
        return fmt.label
    if task.bitrate == formats.NATIVE_BITRATE:
        return f"{fmt.label}, source bitrate"
    return f"{fmt.label} {task.bitrate}"


def _size_text(task: DownloadTask) -> str:
    if task.state == TaskState.COMPLETED:
        return humanize.format_bytes(task.output_bytes)
    if task.total_bytes:
        done = task.downloaded_bytes / (1024 * 1024)
        total = task.total_bytes / (1024 * 1024)
        return f"{done:.1f} / {total:.1f} MB"
    return "—"


class SignalPath(QWidget):
    """The stages a track passes through, as a small block diagram."""

    STEPS = [("RESOLVING", "Prepare"), ("DOWNLOADING", "Download"),
             ("CONVERTING", "Convert"), ("TAGGING", "Tag")]

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(56)
        self.setProperty("role", "clear")
        self._task: Optional[DownloadTask] = None

    def set_task(self, task: Optional[DownloadTask]) -> None:
        self._task = task
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        task = self._task
        if task is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        count = len(self.STEPS)
        width = self.width()
        step = (width - 2) / count
        y = 10.0

        current = next((i for i, (name, _) in enumerate(self.STEPS)
                        if TaskState[name] == task.state), None)
        for position, (name, label) in enumerate(self.STEPS):
            x = 1 + step * position + step / 2
            times = task.stage_times.get(name)
            done = bool(times and len(times) == 2) or task.state == TaskState.COMPLETED
            active = position == current
            failed_here = task.state == TaskState.FAILED and times and not done

            if position:
                painter.setPen(QPen(QColor(COLORS["primary" if done or active else "border"]), 1.5))
                painter.drawLine(QPointF(x - step + 6, y), QPointF(x - 6, y))

            color = (COLORS["accent"] if failed_here
                     else COLORS["success"] if done
                     else COLORS["primary"] if active
                     else COLORS["border_hi"])
            paint.draw_lamp(painter, QPointF(x, y), color, lit=done or active or bool(failed_here))

            painter.setFont(ui_font(TYPE["micro"][0], 500))
            painter.setPen(QColor(COLORS["ink"] if done or active else COLORS["faint"]))
            painter.drawText(QRectF(x - step / 2, y + 8, step, 16), Qt.AlignCenter, label)

            if times and len(times) == 2:
                painter.setFont(mono_font(TYPE["micro"][0]))
                painter.setPen(QColor(COLORS["faint"]))
                painter.drawText(QRectF(x - step / 2, y + 25, step, 16), Qt.AlignCenter,
                                 _stage_seconds(times[1] - times[0]))
        painter.end()


def _stage_seconds(seconds: float) -> str:
    return f"{seconds:.1f}s" if seconds < 60 else humanize.format_eta(seconds)


class Inspector(QFrame):
    """Everything audix knows about one item."""

    closed = Signal()
    action = Signal(str, str)           # zone, task id

    def __init__(self, thumbnails: Thumbnails, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.thumbnails = thumbnails
        self.setProperty("role", "sidePanel")
        self.setFixedWidth(INSPECTOR_WIDTH)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(26)
        shadow.setOffset(-6, 0)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.setGraphicsEffect(shadow)
        self._task: Optional[DownloadTask] = None
        self._rows: Dict[str, QLabel] = {}
        self._captions: Dict[str, QLabel] = {}
        self._holders: Dict[str, QWidget] = {}
        self._shown_thumb = ""
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 0, 0, 0)
        outer.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(SPACE["base"], SPACE["sm"], SPACE["sm"], SPACE["xs"])
        head.setSpacing(SPACE["sm"])
        self.state_lamp = Lamp()
        head.addWidget(self.state_lamp)
        self.state_label = QLabel("")
        self.state_label.setProperty("role", "body")
        head.addWidget(self.state_label, 1)
        self.browse_key = IconKey("globe", "Open in Browse",
                                  lambda: self._emit("browse"), size=15)
        self.copy_key = IconKey("copy", "Copy link", lambda: self._emit("copy"), size=15)
        head.addWidget(self.browse_key)
        head.addWidget(self.copy_key)
        head.addSpacing(SPACE["sm"])
        head.addWidget(IconKey("close", "Close details", self.closed, size=15))
        outer.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll, 1)

        body = QWidget()
        body.setProperty("role", "panelBody")
        scroll.setWidget(body)
        column = QVBoxLayout(body)
        column.setContentsMargins(SPACE["base"], 0, SPACE["base"], SPACE["sm"])
        column.setSpacing(SPACE["sm"])

        self.thumb = QLabel()
        self.thumb.setFixedSize(INSPECTOR_WIDTH - 2 * SPACE["base"] - 2, THUMB_PREVIEW_HEIGHT)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setStyleSheet(f"background-color: {COLORS['well']};")
        column.addWidget(self.thumb)

        self.title_label = QLabel("")
        self.title_label.setProperty("role", "h2")
        self.title_label.setWordWrap(True)
        self.title_label.setTextFormat(Qt.PlainText)
        self.title_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        column.addWidget(self.title_label)

        self.channel_label = QLabel("")
        self.channel_label.setProperty("role", "muted")
        self.channel_label.setTextFormat(Qt.PlainText)
        column.addWidget(self.channel_label)

        column.addSpacing(SPACE["xs"])
        self.signal_path = SignalPath()
        column.addWidget(self.signal_path)

        self.error_label = QLabel("")
        self.error_label.setProperty("role", "error")
        self.error_label.setWordWrap(True)
        self.error_label.setTextFormat(Qt.PlainText)
        self.error_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        column.addWidget(self.error_label)

        grid = QVBoxLayout()
        grid.setSpacing(3)
        for key in ("Speed", "Time left", "Source stream", "Saved as", "Size", "Length",
                    "Playlist", "Started", "Finished", "Elapsed", "Average speed"):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            caption = QLabel(key)
            caption.setProperty("role", "hint")
            caption.setFixedWidth(96)
            self._captions[key] = caption
            row.addWidget(caption, 0, Qt.AlignTop)
            value = QLabel("—")
            value.setProperty("role", "body")
            value.setStyleSheet(f"font-size: {TYPE['small'][0]}px;")
            value.setWordWrap(True)
            value.setTextFormat(Qt.PlainText)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row.addWidget(value, 1)
            holder = QWidget()
            holder.setProperty("role", "clear")
            holder.setLayout(row)
            grid.addWidget(holder)
            self._rows[key] = value
            self._holders[key] = holder
        column.addLayout(grid)

        column.addSpacing(SPACE["sm"])
        self.path_label = QLabel("")
        self.path_label.setProperty("role", "hint")
        self.path_label.setWordWrap(True)
        self.path_label.setTextFormat(Qt.PlainText)
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        column.addWidget(self.path_label)
        column.addSpacing(SPACE["base"])
        column.addStretch(1)

        # Pinned below the scrolling detail, so the next move is always in one place.
        footer = QFrame()
        footer.setProperty("role", "strip")
        self.actions = QGridLayout(footer)
        self.actions.setContentsMargins(SPACE["md"], SPACE["md"], SPACE["md"], SPACE["md"])
        self.actions.setSpacing(SPACE["xs"])
        self.open_key = self._action("Open file", "open", "play", 0, 0, 2, "primary")
        self.folder_key = self._action("Show in folder", "folder", "folder", 1, 0)
        self.edit_key = self._action("Edit audio", "edit", "wave", 1, 1)
        self.retry_key = self._action("Download again", "retry", "retry", 2, 0)
        self.remove_key = self._action("Remove", "remove", "trash", 2, 1, 1, "danger")
        self.remove_key.setToolTip("Remove from this list. The file stays put.")
        self.resume_key = self._action("Resume", "resume", "play", 3, 0, 2, "primary")
        self.pause_key = self._action("Pause", "pause", "pause", 4, 0)
        self.cancel_key = self._action("Cancel", "cancel", "close", 4, 1, 1, "danger")
        outer.addWidget(footer)

    def _action(self, text: str, zone: str, icon_name: str, row: int, column: int,
                span: int = 1, variant: str = "") -> QPushButton:
        key = TextKey(text, lambda: self._emit(zone), variant=variant, icon_name=icon_name)
        self.actions.addWidget(key, row, column, 1, span)
        return key

    def _emit(self, zone: str) -> None:
        if self._task is not None:
            self.action.emit(zone, self._task.id)

    def show_task(self, task: Optional[DownloadTask]) -> None:
        self._task = task
        self.update_from_task()

    def task_id(self) -> str:
        return self._task.id if self._task else ""

    def update_from_task(self) -> None:
        task = self._task
        if task is None:
            return
        entry = task.entry
        self.state_lamp.set_state(STATE_COLORS[task.state.value],
                                  task.state not in (TaskState.PENDING, TaskState.PAUSED,
                                                     TaskState.CANCELLED))
        self.state_label.setText(task.message if task.state == TaskState.PAUSED
                                 else task.state.value)
        self.title_label.setText(task.title)
        self.channel_label.setText(entry.uploader)
        self.channel_label.setVisible(bool(entry.uploader))
        self.signal_path.set_task(task)
        self._refresh_thumb()

        failed = task.state == TaskState.FAILED
        self.error_label.setText(task.message if failed else "")
        self.error_label.setVisible(failed)

        spec = formats.get(task.audio_format)
        quality = ("lossless" if spec.lossless else "source bitrate"
                   if task.bitrate == formats.NATIVE_BITRATE else f"{task.bitrate} kbps")
        speed = _average_speed(task)
        running = task.state == TaskState.DOWNLOADING
        rows = {
            "Speed": humanize.format_speed(task.speed),
            "Time left": humanize.format_eta(task.eta) if task.eta else "—",
            "Source stream": task.source_format or "—",
            "Saved as": f"{spec.label}, {quality}",
            "Size": _size_text(task),
            "Length": humanize.format_duration(entry.duration),
            "Playlist": entry.playlist_title or "—",
            "Started": humanize.format_clock(task.started_at),
            "Finished": humanize.format_clock(task.finished_at),
            "Elapsed": humanize.format_eta(task.elapsed) if task.elapsed else "—",
            "Average speed": humanize.format_speed(speed) if speed else "—",
        }
        for key, value in rows.items():
            self._rows[key].setText(value)

        finished = task.state == TaskState.COMPLETED
        self._captions["Elapsed"].setText("Took" if task.state.is_terminal else "Elapsed")
        self._holders["Speed"].setVisible(running)
        self._holders["Time left"].setVisible(running)
        self._holders["Playlist"].setVisible(bool(entry.playlist_title))
        self._holders["Finished"].setVisible(bool(task.finished_at))
        self._holders["Average speed"].setVisible(finished and bool(speed))
        exists = finished and bool(task.output_path) and os.path.isfile(task.output_path)
        self.path_label.setText(task.output_path if exists else
                                "This file has been moved or deleted." if finished else "")
        self.path_label.setVisible(bool(self.path_label.text()))

        terminal = task.state.is_terminal
        self.open_key.setVisible(exists)
        self.folder_key.setVisible(exists)
        self.edit_key.setVisible(exists)
        self.retry_key.setVisible(terminal)
        self.retry_key.setText("Download again" if finished else "Try again")
        self.resume_key.setVisible(task.state == TaskState.PAUSED)
        self.pause_key.setVisible(task.state.can_pause)
        self.cancel_key.setVisible(not terminal)
        self.remove_key.setVisible(terminal)

    def _refresh_thumb(self) -> None:
        url = self._task.entry.thumbnail_url if self._task else ""
        if url == self._shown_thumb:
            return                  # this runs on every refresh; scaling must not
        pixmap = self.thumbnails.get(url)
        if pixmap is None:
            self._shown_thumb = ""
            self.thumb.setPixmap(icons.pixmap("note", 42, COLORS["border_hi"]))
        else:
            self._shown_thumb = url
            self.thumb.setPixmap(_cover(pixmap, self.thumb.width(), self.thumb.height()))


def _cover(pixmap: QPixmap, width: int, height: int) -> QPixmap:
    """Scale to fill the frame, cropping any overflow, like a video player does."""
    app = QApplication.instance()
    ratio = app.devicePixelRatio() if app else 1.0
    scaled = pixmap.scaled(round(width * ratio), round(height * ratio),
                           Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x = (scaled.width() - round(width * ratio)) // 2
    y = (scaled.height() - round(height * ratio)) // 2
    cropped = scaled.copy(x, y, round(width * ratio), round(height * ratio))
    cropped.setDevicePixelRatio(ratio)
    return cropped


def _average_speed(task: DownloadTask) -> Optional[float]:
    times = task.stage_times.get("DOWNLOADING")
    if not times or len(times) < 2 or not task.total_bytes:
        return None
    seconds = times[1] - times[0]
    return task.total_bytes / seconds if seconds > 0 else None


class ColumnHeader(QWidget):
    """Captions above the list, drawn from the same geometry as the rows."""

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(26)
        self.setProperty("role", "clear")
        self.covered = 0.0

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.fillRect(self.rect(), QColor(COLORS["well"]))
        painter.fillRect(QRectF(0, self.height() - 1, self.width(), 1),
                         QColor(COLORS["surface"]))
        painter.setFont(ui_font(TYPE["micro"][0], 500))
        painter.setPen(QColor(COLORS["faint"]))
        rect = QRectF(self.rect())
        cols = columns_for(rect, self.covered)

        left = Qt.AlignLeft | Qt.AlignVCenter
        right = Qt.AlignRight | Qt.AlignVCenter
        painter.drawText(cols.state, left, "Status")
        painter.drawText(QRectF(cols.thumb.left(), 0, cols.title.right() - cols.thumb.left(),
                                rect.height()), left, "Track")
        painter.drawText(cols.ladder, left, "Progress")
        if cols.size is not None:
            painter.drawText(cols.size, right, "Size")
        if cols.speed is not None:
            painter.drawText(cols.speed, right, "Speed")
        if cols.eta is not None:
            painter.drawText(cols.eta, right, "Left")
        painter.end()


class OverallMeter(QWidget):
    """The batch as one ladder: how far through everything in progress you are."""

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(16)
        self.setProperty("role", "clear")
        self._fraction = 0.0
        self._color = COLORS["primary"]

    def set_value(self, fraction: float, color: str) -> None:
        self._fraction = fraction
        self._color = color
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        paint.draw_ladder(painter, QRectF(self.rect()), self._fraction, self._color)
        painter.end()


class DownloadsTab(QWidget):
    """Live view of every download."""

    edit_requested = Signal(str)          # task id
    browse_requested = Signal(str)        # url
    queue_requested = Signal()            # go to the Queue
    attention_changed = Signal(int, bool) # unseen items, whether any of them failed
    activity = Signal(float, int, int)    # bytes/sec, running, waiting

    def __init__(self, manager: DownloadManager, history: DownloadHistory, prefs: OutputPrefs,
                 thumbnails: Thumbnails, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.history = history
        self.prefs = prefs
        self.thumbnails = thumbnails
        self._page_visible = False

        self._build_ui()

        manager.task_finished.connect(self._on_task_finished)
        thumbnails.ready.connect(self.model.repaint_url)
        thumbnails.ready.connect(lambda _url: self.inspector.update_from_task())

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self.model.flush(force=True)
        self._refresh_summary()

    # ------------------------------------------------------------------ layout
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE["base"], SPACE["md"], SPACE["base"], SPACE["md"])
        root.setSpacing(SPACE["sm"])

        root.addLayout(self._build_summary())
        root.addLayout(self._build_controls())

        window = Well()
        self.column_header = ColumnHeader()
        window.body.addWidget(self.column_header)

        self.stack = QStackedWidget()
        self.stack.setProperty("role", "clear")
        self.model = DownloadsModel(self.manager, self)
        self.list = RowList()
        self.delegate = DownloadsDelegate(self.thumbnails, self.model, self.list)
        self.list.setModel(self.model)
        self.list.setItemDelegate(self.delegate)
        self.delegate.zone_clicked.connect(self._on_zone_clicked)
        self.delegate.row_activated.connect(self._on_row_activated)
        self.list.customContextMenuRequested.connect(self._show_menu)
        self.stack.addWidget(self.list)
        self.stack.addWidget(self._build_empty_state())
        window.body.addWidget(self.stack, 1)
        root.addWidget(window, 1)

        self.inspector = Inspector(self.thumbnails)
        self.inspector.closed.connect(lambda: self._select(""))
        self.inspector.action.connect(self._perform)
        window.set_side_panel(self.inspector)
        self.inspector.hide()

    def _build_summary(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(SPACE["base"])
        self.summary_label = QLabel("")
        self.summary_label.setProperty("role", "h2")
        row.addWidget(self.summary_label, 1)
        self.left_label = QLabel("")
        self.left_label.setProperty("role", "muted")
        row.addWidget(self.left_label)
        self.speed_label = QLabel("")
        self.speed_label.setFont(mono_font(TYPE["h2"][0], 600))
        self.speed_label.setStyleSheet(f"color: {COLORS['ink']};")
        row.addWidget(self.speed_label)
        column.addLayout(row)

        self.overall = OverallMeter()
        column.addWidget(self.overall)
        return column

    def _build_controls(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(SPACE["xs"])

        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        self.filter_keys: Dict[str, QPushButton] = {}
        for bucket, label in FILTERS:
            key = QPushButton(label)
            key.setProperty("variant", "selector")
            key.setCheckable(True)
            key.setCursor(Qt.PointingHandCursor)
            key.clicked.connect(lambda _c=False, b=bucket: self._apply_view(b))
            self.filter_group.addButton(key)
            self.filter_keys[bucket] = key
            row.addWidget(key)
        self.filter_keys[ALL].setChecked(True)

        row.addSpacing(SPACE["md"])
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Find a track")
        add_clear_key(self.search_input)
        self.search_input.setMinimumWidth(130)
        self.search_input.setMaximumWidth(220)
        self.search_input.addAction(icons.icon("search", 16, COLORS["faint"]),
                                    QLineEdit.LeadingPosition)
        self.search_input.textChanged.connect(lambda _t: self._apply_view())
        row.addWidget(self.search_input)
        row.addStretch(1)

        self.parallel_combo = ParallelCombo(self.prefs)
        row.addWidget(self.parallel_combo)
        row.addSpacing(SPACE["xs"])
        self.pause_key = TextKey("Pause all", self._toggle_pause, icon_name="pause")
        self.pause_key.setMinimumWidth(116)
        row.addWidget(self.pause_key)
        self.retry_key = TextKey("Retry failed", self._retry_failed, icon_name="retry")
        row.addWidget(self.retry_key)

        # Set apart from the keys that keep things running, so a slip cannot land here.
        row.addSpacing(SPACE["2xl"])
        self.clear_key = TextKey("Clear finished", self._clear_finished, variant="ghost")
        row.addWidget(self.clear_key)
        self.cancel_key = TextKey("Cancel all", self.manager.cancel_all, variant="danger")
        row.addWidget(self.cancel_key)
        return row

    def _build_empty_state(self) -> QWidget:
        page = QWidget()
        page.setProperty("role", "wellPage")
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(SPACE["sm"])

        self.empty_heading = QLabel("Nothing has been downloaded yet")
        self.empty_heading.setProperty("role", "h1")
        self.empty_heading.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.empty_heading)

        self.empty_body = QLabel(
            "Pick tracks in the Queue and press Download.\n"
            "Each one shows up here with its progress, speed, and time left."
        )
        self.empty_body.setProperty("role", "muted")
        self.empty_body.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.empty_body)

        layout.addSpacing(SPACE["md"])
        row = QHBoxLayout()
        row.setAlignment(Qt.AlignCenter)
        self.empty_key = TextKey("Go to the Queue", self.queue_requested)
        row.addWidget(self.empty_key)
        layout.addLayout(row)
        return page

    # ----------------------------------------------------------------- refresh
    def _tick(self) -> None:
        changed = self.model.flush()
        animating = any(task.state == TaskState.RESOLVING for task in self.manager.tasks())
        if animating and not motion.reduced():
            self.delegate.phase += 1
            self.list.viewport().update()
        if changed:
            self.stack.setCurrentIndex(0 if self.model.rowCount() else 1)
            self._refresh_summary()
            self.inspector.update_from_task()

    def _refresh_summary(self) -> None:
        tasks = self.manager.tasks()
        buckets = {ACTIVE: 0, WAITING: 0, FINISHED: 0, FAILED: 0}
        for task in tasks:
            buckets[_bucket(task)] += 1
        active, waiting = buckets[ACTIVE], buckets[WAITING]
        finished, failed = buckets[FINISHED], buckets[FAILED]
        cancelled = sum(task.state == TaskState.CANCELLED for task in tasks)

        for bucket, label in FILTERS:
            count = len(tasks) if bucket == ALL else buckets[bucket]
            self.filter_keys[bucket].setText(f"{label} {count}" if count else label)

        parts = []
        if active:
            parts.append(f"{active} running")
        if waiting:
            parts.append(f"{waiting} waiting")
        if finished:
            parts.append(f"{finished} finished")
        if failed - cancelled:
            parts.append(f"{failed - cancelled} failed")
        if cancelled:
            parts.append(f"{cancelled} cancelled")
        self.summary_label.setText(" · ".join(parts) or "Downloads")

        speed = self.current_speed()
        self.activity.emit(speed, active, waiting)
        self.speed_label.setText(humanize.format_speed(speed) if speed else "")
        self.left_label.setText(self._time_left_text(tasks))

        batch = [task for task in tasks if not task.state.is_terminal]
        if batch:
            fraction = sum(task.progress for task in batch) / len(batch)
            self.overall.set_value(fraction, COLORS["primary"])
        else:
            self.overall.set_value(1.0 if finished else 0.0, COLORS["success"])

        held = self.manager.is_paused
        self.pause_key.setText("Resume all" if held else "Pause all")
        self.pause_key.setIcon(icons.icon("play" if held else "pause", 16))
        self.pause_key.setEnabled(held or active + waiting > 0)
        self.pause_key.setToolTip(
            "Carry on from where everything stopped" if held
            else "Hold every download, keeping what has been fetched" if active + waiting
            else "Nothing is running.")
        self.retry_key.setVisible(any(t.state == TaskState.FAILED for t in tasks))
        self.clear_key.setEnabled(finished + failed > 0)
        self.clear_key.setToolTip("Remove finished items from this list. Your files stay put."
                                  if finished + failed else "Nothing has finished yet.")
        self.cancel_key.setEnabled(active + waiting > 0)
        self.cancel_key.setToolTip("Stop every download and delete what they fetched"
                                   if active + waiting else "Nothing is running.")

    def current_speed(self) -> float:
        return sum(task.speed or 0.0 for task in self.manager.tasks()
                   if task.state == TaskState.DOWNLOADING)

    @staticmethod
    def _time_left_text(tasks: List[DownloadTask]) -> str:
        """How long is left, claiming no more than the figures can support.

        Nothing is known about a track until it starts, so while others are still to
        come, this can only speak for the ones running now.
        """
        running = [task.eta for task in tasks
                   if task.state == TaskState.DOWNLOADING and task.eta]
        if not running:
            return ""
        left = humanize.format_eta(max(running))
        unknown = (TaskState.RESOLVING, TaskState.PENDING, TaskState.PAUSED)
        more_to_come = any(task.state in unknown for task in tasks)
        return f"These tracks: about {left} left" if more_to_come else f"About {left} left"

    # ------------------------------------------------------------------- views
    def _apply_view(self, bucket: Optional[str] = None) -> None:
        bucket = bucket or self.model.filter
        self.model.set_view(bucket, self.search_input.text())
        self.stack.setCurrentIndex(0 if self.model.rowCount() else 1)
        filtered = bool(self.manager.tasks())
        self.empty_heading.setText("Nothing matches" if filtered
                                   else "Nothing has been downloaded yet")
        self.empty_body.setVisible(not filtered)
        self.empty_key.setVisible(not filtered)

    def show_filter(self, bucket: str) -> None:
        self.filter_keys[bucket].setChecked(True)
        self._apply_view(bucket)

    # ----------------------------------------------------------------- actions
    def _on_zone_clicked(self, index: QModelIndex, zone: str, _modifiers) -> None:
        task = self.model.task_at(index)
        if task is None:
            return
        if zone:
            self._perform(zone, task.id)
        else:
            self._select("" if self.delegate.selected_id == task.id else task.id)

    def _on_row_activated(self, index: QModelIndex) -> None:
        task = self.model.task_at(index)
        if task is not None and task.state == TaskState.COMPLETED:
            self._perform("open", task.id)

    def _perform(self, zone: str, task_id: str) -> None:
        task = self.manager.task(task_id)
        if task is None:
            return
        if zone == "open":
            if not open_file(task.output_path):
                self._select(task_id)
        elif zone == "folder":
            reveal_in_file_manager(task.output_path)
        elif zone == "edit":
            self.edit_requested.emit(task_id)
        elif zone == "resume":
            self.manager.resume(task_id)
        elif zone == "pause":
            self.manager.pause(task_id)
        elif zone == "cancel":
            self.manager.cancel(task_id)
        elif zone == "top":
            self.manager.prioritize(task_id)
        elif zone == "retry":
            self.history.remove([task_id])
            self.manager.retry(task_id)
        elif zone == "remove":
            self.history.remove([task_id])
            if self.delegate.selected_id == task_id:
                self._select("")
            self.manager.remove(task_id)
        elif zone == "browse":
            self.browse_requested.emit(task.entry.url)
        elif zone == "copy":
            QApplication.clipboard().setText(task.entry.url)

    def _select(self, task_id: str) -> None:
        self.delegate.selected_id = task_id
        task = self.manager.task(task_id) if task_id else None
        self.inspector.show_task(task)
        self.inspector.setVisible(task is not None)
        covered = float(INSPECTOR_WIDTH + 1) if task is not None else 0.0
        self.delegate.covered = covered
        self.column_header.covered = covered
        self.column_header.update()
        self.list.viewport().update()

    def _show_menu(self, position) -> None:
        task = self.model.task_at(self.list.indexAt(position))
        if task is None:
            return
        menu = QMenu(self)
        for zone, icon_name in row_actions(task):
            menu.addAction(icons.icon(icon_name, 16), ACTION_TIPS[zone],
                           lambda z=zone: self._perform(z, task.id))
        menu.addSeparator()
        menu.addAction(icons.icon("globe", 16), "Open in Browse",
                       lambda: self._perform("browse", task.id))
        menu.addAction(icons.icon("copy", 16), "Copy link",
                       lambda: self._perform("copy", task.id))
        menu.exec(self.list.viewport().mapToGlobal(position))

    def _toggle_pause(self) -> None:
        if self.manager.is_paused:
            self.manager.resume_all()
        else:
            self.manager.pause_all()
        self._refresh_summary()

    def _retry_failed(self) -> None:
        self.manager.retry_failed()

    def _clear_finished(self) -> None:
        removed = self.manager.clear_finished()
        self.history.remove(removed)
        if self.delegate.selected_id in removed:
            self._select("")

    # --------------------------------------------------------- what changed lately
    def _on_task_finished(self, task_id: str, success: bool, message: str) -> None:
        task = self.manager.task(task_id)
        if task is None:
            return
        if success:
            self.history.add(task)
        if not self._page_visible and task.state in (TaskState.COMPLETED, TaskState.FAILED):
            self.model.unseen.add(task_id)
            self._report_attention()

    def _report_attention(self) -> None:
        failed = any(task is not None and task.state == TaskState.FAILED
                     for task in map(self.manager.task, self.model.unseen))
        self.attention_changed.emit(len(self.model.unseen), failed)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        # First to go when space runs out, because the Queue page has the same control.
        self.parallel_combo.setVisible(self.width() >= CONTROLS_FULL_WIDTH)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self._page_visible = True
        self.attention_changed.emit(0, False)

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().hideEvent(event)
        self._page_visible = False
        # Rows stay lit for the whole visit, so you can see which ones changed.
        self.model.unseen.clear()
        self.list.viewport().update()
