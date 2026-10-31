"""The Queue: every link lands here, and nothing starts until you choose.

Paste a link, drop one on the window, or send one from Browse. Each track becomes a
row with a tick beside it, a playlist becomes a group you can tick as a whole, and
the transport strip at the bottom runs what is selected, or everything.

This page replaces the old fetch-then-confirm flow. There is no preview step because
the list is the preview: a link's tracks appear as soon as they are read, already
selected, and unticking is all it takes to leave one out.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

from PySide6.QtCore import (
    QAbstractListModel, QModelIndex, QPointF, QRectF, QTimer, Qt, Signal, Slot,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QStackedWidget,
    QStyle, QVBoxLayout, QWidget,
)

from audix.core import links
from audix.core.downloader import Scope
from audix.core.link_queue import LinkAdded, LinkQueue, PendingLink, QueueGroup, QueueItem
from audix.ui import icons, motion, paint
from audix.ui.output_prefs import OutputPrefs
from audix.ui.theme import mono_font, ui_font
from audix.ui.thumbnails import Thumbnails
from audix.ui.tokens import COLORS, SPACE, TYPE
from audix.ui.widgets.controls import (
    FolderButton, IconKey, ParallelCombo, TextKey, add_clear_key,
)
from audix.ui.widgets.format_selector import FormatSelector
from audix.ui.widgets.row_list import ACTION_SIZE, RowDelegate, RowList
from audix.ui.widgets.well import Well
from audix.utils import humanize

log = logging.getLogger("audix.ui.queue")

ROW_ROLE = Qt.UserRole + 1

ITEM_HEIGHT = 58
GROUP_HEIGHT = 46
PENDING_HEIGHT = 54
INSET = 14
BOX = 18
THUMB_WIDTH, THUMB_HEIGHT = 72, 40
DURATION_WIDTH = 64


class QueueModel(QAbstractListModel):
    """The queue's visible rows, as a flat list."""

    def __init__(self, queue: LinkQueue, parent=None) -> None:
        super().__init__(parent)
        self.queue = queue
        self._rows = queue.visible_rows()
        queue.changed.connect(self.reload)
        queue.checks_changed.connect(self.repaint)

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt override
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        if role == ROW_ROLE:
            return row
        if role in (Qt.DisplayRole, Qt.AccessibleTextRole):
            return _describe(row)
        return None

    def reload(self) -> None:
        self.beginResetModel()
        self._rows = self.queue.visible_rows()
        self.endResetModel()

    def repaint(self) -> None:
        if self._rows:
            self.dataChanged.emit(self.index(0), self.index(len(self._rows) - 1))

    def row_at(self, index: QModelIndex):
        return self._rows[index.row()] if index.isValid() else None

    def index_of(self, row_id: str) -> QModelIndex:
        for position, row in enumerate(self._rows):
            if row.id == row_id:
                return self.index(position)
        return QModelIndex()

    def repaint_url(self, url: str) -> None:
        """Repaint the rows waiting on a thumbnail that just arrived."""
        for position, row in enumerate(self._rows):
            if isinstance(row, QueueItem) and row.entry.thumbnail_url == url:
                index = self.index(position)
                self.dataChanged.emit(index, index)


def _describe(row) -> str:
    if isinstance(row, QueueItem):
        state = "selected" if row.checked else "not selected"
        return f"{row.entry.title}, {state}"
    if isinstance(row, QueueGroup):
        return f"Playlist {row.title}"
    return row.error or f"Reading {row.url}"


class QueueDelegate(RowDelegate):
    """Paints tracks, playlist headers, and links still being read."""

    def __init__(self, queue: LinkQueue, thumbnails: Thumbnails, parent=None) -> None:
        super().__init__(parent)
        self.queue = queue
        self.thumbnails = thumbnails
        self.phase = 0
        self._title_font = ui_font(TYPE["body"][0], 600)
        self._sub_font = ui_font(TYPE["small"][0])
        self._mono_font = mono_font(TYPE["small"][0])

    def sizeHint(self, option, index):  # noqa: N802 - Qt override
        row = index.data(ROW_ROLE)
        size = super().sizeHint(option, index)
        if isinstance(row, QueueItem):
            size.setHeight(ITEM_HEIGHT)
        elif isinstance(row, QueueGroup):
            size.setHeight(GROUP_HEIGHT)
        else:
            size.setHeight(PENDING_HEIGHT)
        return size

    # -------------------------------------------------------------------- zones
    def zones(self, index, rect: QRectF) -> Dict[str, QRectF]:
        row = index.data(ROW_ROLE)
        mid = rect.center().y()
        right = rect.right() - 8
        key = QRectF(right - ACTION_SIZE, mid - ACTION_SIZE / 2, ACTION_SIZE, ACTION_SIZE)
        next_key = key.translated(-(ACTION_SIZE + 2), 0)
        box = QRectF(rect.left() + INSET, mid - BOX / 2, BOX, BOX)

        if isinstance(row, QueueItem):
            return {"box": box, "remove": key, "download": next_key}
        if isinstance(row, QueueGroup):
            chevron = QRectF(box.right() + 8, mid - 12, 24, 24)
            return {"box": box, "chevron": chevron, "remove": key}
        if row.error:
            return {"remove": key, "retry": next_key}
        return {"remove": key}

    def zone_tooltip(self, index, zone: str) -> str:
        row = index.data(ROW_ROLE)
        if zone == "remove":
            return ("Remove this playlist from the Queue"
                    if isinstance(row, QueueGroup) else "Remove from the Queue")
        if zone == "download":
            return "Download this track now"
        if zone == "retry":
            return "Try reading this link again"
        if zone == "box":
            return "Select or deselect"
        if zone == "chevron":
            return "Show or hide this playlist's tracks"
        return ""

    def row_tooltip(self, index) -> str:
        row = index.data(ROW_ROLE)
        if isinstance(row, QueueItem):
            return row.entry.title
        if isinstance(row, PendingLink):
            return row.error or row.url
        return row.title

    # ------------------------------------------------------------------ painting
    def paint(self, painter: QPainter, option, index) -> None:
        row = index.data(ROW_ROLE)
        rect = QRectF(option.rect)
        hover = bool(option.state & QStyle.State_MouseOver)

        painter.save()
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        if isinstance(row, QueueGroup):
            painter.fillRect(rect, QColor(COLORS["surface"]))
        elif hover:
            painter.fillRect(rect, QColor(COLORS["surface"]))
        painter.fillRect(QRectF(rect.left(), rect.bottom(), rect.width(), 1),
                         QColor(COLORS["surface"]))

        zones = self.zones(index, rect)
        if isinstance(row, QueueItem):
            self._paint_item(painter, rect, row, zones, index, hover)
        elif isinstance(row, QueueGroup):
            self._paint_group(painter, rect, row, zones, index, hover)
        else:
            self._paint_pending(painter, rect, row, zones, index, hover)

        if option.state & QStyle.State_HasFocus:
            painter.setPen(QColor(COLORS["primary"]))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect.adjusted(0.5, 0.5, -1.5, -1.5))
        painter.restore()

    def _paint_item(self, painter, rect, item: QueueItem, zones, index, hover) -> None:
        mid = rect.center().y()
        paint.draw_tick_box(painter, zones["box"], item.checked,
                            hover=self.is_hot(index, "box"))

        thumb = QRectF(zones["box"].right() + INSET, mid - THUMB_HEIGHT / 2,
                       THUMB_WIDTH, THUMB_HEIGHT)
        paint.draw_thumbnail(painter, thumb, self.thumbnails.get(item.entry.thumbnail_url))

        self.paint_action(painter, index, zones["download"], "download", "download", hover)
        self.paint_action(painter, index, zones["remove"], "remove", "close", hover)

        duration = QRectF(zones["download"].left() - DURATION_WIDTH - 10, rect.top(),
                          DURATION_WIDTH, rect.height())
        painter.setFont(self._mono_font)
        painter.setPen(QColor(COLORS["muted"] if item.checked else COLORS["faint"]))
        painter.drawText(duration, Qt.AlignRight | Qt.AlignVCenter,
                         humanize.format_duration(item.entry.duration))

        left = thumb.right() + INSET
        width = duration.left() - left - 12
        title = QRectF(left, mid - 19, width, 19)
        painter.setFont(self._title_font)
        painter.setPen(QColor(COLORS["ink"] if item.checked else COLORS["muted"]))
        painter.drawText(title, Qt.AlignLeft | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(item.entry.title, Qt.ElideRight,
                                                          int(width)))

        subtitle = QRectF(left, mid + 1, width, 18)
        painter.setFont(self._sub_font)
        parts = [item.entry.uploader]
        if item.entry.playlist_index and item.group_id:
            parts.insert(0, f"Track {item.entry.playlist_index}")
        line = " · ".join(part for part in parts if part)
        painter.setPen(QColor(COLORS["faint"]))
        metrics = painter.fontMetrics()
        if item.already_have:
            note = "Already downloaded"
            note_width = metrics.horizontalAdvance(note)
            room = max(0, int(width) - note_width - 30)
            line = metrics.elidedText(line, Qt.ElideRight, room)
            painter.drawText(subtitle, Qt.AlignLeft | Qt.AlignVCenter, line)
            lamp_x = subtitle.left() + metrics.horizontalAdvance(line) + (16 if line else 4)
            paint.draw_lamp(painter, QPointF(lamp_x, subtitle.center().y()),
                            COLORS["success"], radius=3.5)
            painter.setPen(QColor(COLORS["success"]))
            painter.drawText(subtitle.adjusted(lamp_x - subtitle.left() + 9, 0, 0, 0),
                             Qt.AlignLeft | Qt.AlignVCenter, note)
        else:
            painter.drawText(subtitle, Qt.AlignLeft | Qt.AlignVCenter,
                             metrics.elidedText(line, Qt.ElideRight, int(width)))

    def _paint_group(self, painter, rect, group: QueueGroup, zones, index, hover) -> None:
        items = self.queue.group_items(group.id)
        ticked = sum(item.checked for item in items)
        paint.draw_tick_box(painter, zones["box"], ticked == len(items),
                            partial=0 < ticked < len(items),
                            hover=self.is_hot(index, "box"))

        chevron = zones["chevron"]
        icons.paint(painter, "chevron_down" if group.expanded else "chevron_right",
                    chevron.adjusted(3, 3, -3, -3),
                    COLORS["ink"] if self.is_hot(index, "chevron") else COLORS["muted"])

        self.paint_action(painter, index, zones["remove"], "remove", "close", hover)

        duration = self.queue.group_duration(group.id)
        facts = [humanize.count(len(items), "track")]
        if ticked != len(items):
            facts.append(f"{ticked} selected")
        if duration:
            facts.append(humanize.format_duration(duration))
        if group.is_mix:
            facts.append("YouTube Mix")
        summary = " · ".join(facts)

        left = chevron.right() + 6
        right = zones["remove"].left() - 12
        painter.setFont(self._sub_font)
        summary_width = painter.fontMetrics().horizontalAdvance(summary)
        painter.setPen(QColor(COLORS["faint"]))
        painter.drawText(QRectF(right - summary_width, rect.top(), summary_width, rect.height()),
                         Qt.AlignRight | Qt.AlignVCenter, summary)

        painter.setFont(self._title_font)
        painter.setPen(QColor(COLORS["ink"]))
        room = int(right - summary_width - left - 16)
        painter.drawText(QRectF(left, rect.top(), room, rect.height()),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(group.title, Qt.ElideRight, room))

    def _paint_pending(self, painter, rect, pending: PendingLink, zones, index, hover) -> None:
        mid = rect.center().y()
        left = rect.left() + INSET
        self.paint_action(painter, index, zones["remove"], "remove", "close", hover)
        right = zones["remove"].left() - 12

        # The title sits in the same column as every track's, so nothing shifts when
        # this row turns into one. The thumbnail's column holds the state meanwhile.
        thumb_left = left + BOX + INSET
        if pending.error:
            self.paint_action(painter, index, zones["retry"], "retry", "retry", hover)
            right = zones["retry"].left() - 12
            paint.draw_lamp(painter, QPointF(left + 9, mid), COLORS["accent"])
            headline, color = pending.error, COLORS["accent"]
        else:
            paint.draw_ladder(painter, QRectF(thumb_left, mid - 5, THUMB_WIDTH, 10), 0,
                              COLORS["primary"], phase=self.phase)
            headline, color = "Reading link…", COLORS["ink"]

        text_left = thumb_left + THUMB_WIDTH + INSET
        width = int(right - text_left)
        painter.setFont(self._title_font)
        painter.setPen(QColor(color))
        painter.drawText(QRectF(text_left, mid - 19, width, 19), Qt.AlignLeft | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(headline, Qt.ElideRight, width))
        painter.setFont(self._sub_font)
        painter.setPen(QColor(COLORS["faint"]))
        painter.drawText(QRectF(text_left, mid + 1, width, 18), Qt.AlignLeft | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(pending.url, Qt.ElideMiddle, width))


class QueueList(RowList):
    """Adds the keyboard: Space ticks, Enter downloads, Delete removes."""

    toggle_requested = Signal(QModelIndex)
    download_requested = Signal(QModelIndex)
    remove_requested = Signal(QModelIndex)
    expand_requested = Signal(QModelIndex, bool)
    select_all_requested = Signal()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        index = self.currentIndex()
        key = event.key()
        if key == Qt.Key_Space and index.isValid():
            self.toggle_requested.emit(index)
        elif key in (Qt.Key_Return, Qt.Key_Enter) and index.isValid():
            self.download_requested.emit(index)
        elif key == Qt.Key_Delete and index.isValid():
            self.remove_requested.emit(index)
        elif key == Qt.Key_Left and index.isValid():
            self.expand_requested.emit(index, False)
        elif key == Qt.Key_Right and index.isValid():
            self.expand_requested.emit(index, True)
        elif key == Qt.Key_A and event.modifiers() & Qt.ControlModifier:
            self.select_all_requested.emit()
        else:
            super().keyPressEvent(event)


class QueueTab(QWidget):
    """Links in, chosen tracks out."""

    #: Queue item ids to download now, in list order.
    download_requested = Signal(list)
    #: Open Browse, optionally at a URL or search.
    browse_requested = Signal(str)
    #: Text that was not a link, offered as a YouTube search.
    search_requested = Signal(str)
    toast = Signal(str, str)           # message, tone

    def __init__(self, queue: LinkQueue, prefs: OutputPrefs, thumbnails: Thumbnails,
                 config, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.queue = queue
        self.prefs = prefs
        self.thumbnails = thumbnails
        self.config = config
        self._last_clicked: Optional[int] = None
        self._offered_clip = ""
        self._search_offer = ""

        self.setAcceptDrops(True)
        self._build_ui()

        self.queue.changed.connect(self._on_changed)
        self.queue.checks_changed.connect(self._refresh)
        self.queue.link_added.connect(self._on_link_added)
        self.queue.notice.connect(lambda message: self.toast.emit(message, "info"))
        self.thumbnails.ready.connect(self.model.repaint_url)
        self.prefs.changed.connect(self._load_prefs)

        self._phase_timer = QTimer(self)
        self._phase_timer.setInterval(90)
        self._phase_timer.timeout.connect(self._advance_phase)

        app = QApplication.instance()
        app.applicationStateChanged.connect(lambda _state: self._offer_clipboard())
        QApplication.clipboard().dataChanged.connect(self._offer_clipboard)

        self._on_changed()
        self._load_prefs()

    # ------------------------------------------------------------------ layout
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top = QVBoxLayout()
        top.setContentsMargins(SPACE["base"], SPACE["md"], SPACE["base"], SPACE["md"])
        top.setSpacing(SPACE["sm"])
        top.addLayout(self._build_link_row())
        self.clip_notice = self._build_clip_notice()
        top.addWidget(self.clip_notice)
        self.link_hint = QLabel("")
        self.link_hint.setProperty("role", "error")
        self.link_hint.hide()
        top.addWidget(self.link_hint)
        self.list_header = self._build_list_header()
        top.addWidget(self.list_header)
        root.addLayout(top)

        window_margin = QVBoxLayout()
        window_margin.setContentsMargins(SPACE["base"], 0, SPACE["base"], SPACE["md"])
        window_margin.addWidget(self._build_window(), 1)
        root.addLayout(window_margin, 1)

        root.addWidget(self._build_transport())

    def _build_link_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(SPACE["sm"])

        self.link_input = QLineEdit()
        self.link_input.setProperty("size", "large")
        self.link_input.setPlaceholderText("Paste a YouTube link, or several at once")
        add_clear_key(self.link_input)
        self.link_input.addAction(icons.icon("link", 16, COLORS["faint"]),
                                  QLineEdit.LeadingPosition)
        self.link_input.returnPressed.connect(self.add_current)
        self.link_input.textChanged.connect(self._on_link_edited)
        row.addWidget(self.link_input, 1)

        row.addWidget(TextKey("Paste", self._paste, icon_name="paste",
                              tooltip="Add whatever link is on your clipboard"))
        self.add_key = TextKey("Add to Queue", self.add_current, icon_name="plus",
                               tooltip="Read this link and add its tracks to the list")
        row.addWidget(self.add_key)
        return row

    def _build_clip_notice(self) -> QFrame:
        notice = QFrame()
        notice.setProperty("role", "notice")
        row = QHBoxLayout(notice)
        row.setContentsMargins(SPACE["md"], 4, 4, 4)
        row.setSpacing(SPACE["sm"])
        self.clip_label = QLabel("")
        self.clip_label.setProperty("role", "muted")
        row.addWidget(self.clip_label, 1)
        row.addWidget(TextKey("Add it", self._take_clipboard, variant="tool"))
        row.addWidget(IconKey("close", "Not now", self._dismiss_clipboard, size=14))
        notice.hide()
        return notice

    def _build_list_header(self) -> QWidget:
        """Printed on the plate above the window, not inside it."""
        header = QWidget()
        header.setProperty("role", "clear")
        row = QHBoxLayout(header)
        row.setContentsMargins(INSET + 1, 2, 0, 0)
        row.setSpacing(SPACE["sm"])

        self.select_all = QCheckBox("Select all")
        self.select_all.setTristate(True)
        self.select_all.clicked.connect(self._toggle_all)
        row.addWidget(self.select_all)

        self.summary_label = QLabel("")
        self.summary_label.setProperty("role", "muted")
        row.addSpacing(SPACE["sm"])
        row.addWidget(self.summary_label, 1)

        self.invert_key = TextKey("Invert", self.queue.invert_checks, variant="ghost",
                                  tooltip="Swap what is selected and what is not")
        row.addWidget(self.invert_key)
        row.addSpacing(SPACE["base"])
        self.remove_key = TextKey("Remove selected", self.queue.remove_checked, variant="danger")
        row.addWidget(self.remove_key)
        self.clear_key = TextKey("Clear", self.queue.clear, variant="danger",
                                 tooltip="Empty the Queue")
        row.addWidget(self.clear_key)
        return header

    def _build_window(self) -> Well:
        window = Well()

        self.stack = QStackedWidget()
        self.stack.setProperty("role", "clear")

        self.model = QueueModel(self.queue, self)
        self.list = QueueList()
        self.delegate = QueueDelegate(self.queue, self.thumbnails, self.list)
        self.list.setModel(self.model)
        self.list.setItemDelegate(self.delegate)
        self.delegate.zone_clicked.connect(self._on_zone_clicked)
        self.delegate.row_activated.connect(self._download_row)
        self.list.toggle_requested.connect(self._toggle_row)
        self.list.download_requested.connect(self._download_row)
        self.list.remove_requested.connect(self._remove_row)
        self.list.expand_requested.connect(self._expand_row)
        self.list.select_all_requested.connect(lambda: self.queue.set_all_checked(True))
        self.list.customContextMenuRequested.connect(self._show_menu)
        self.stack.addWidget(self.list)

        self.stack.addWidget(self._build_empty_state())
        window.body.addWidget(self.stack, 1)
        return window

    def _build_empty_state(self) -> QWidget:
        page = QWidget()
        page.setProperty("role", "wellPage")
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(SPACE["sm"])

        heading = QLabel("Paste a link to get started")
        heading.setProperty("role", "h1")
        heading.setAlignment(Qt.AlignCenter)
        layout.addWidget(heading)

        body = QLabel(
            "Videos, Shorts, playlists and albums all land here first,\n"
            "so you choose what to download before anything starts."
        )
        body.setProperty("role", "muted")
        body.setAlignment(Qt.AlignCenter)
        layout.addWidget(body)

        layout.addSpacing(SPACE["md"])
        row = QHBoxLayout()
        row.setAlignment(Qt.AlignCenter)
        row.addWidget(TextKey("Find something in Browse",
                              lambda: self.browse_requested.emit(""), icon_name="globe"))
        layout.addLayout(row)
        return page

    def _build_transport(self) -> QFrame:
        strip = QFrame()
        strip.setProperty("role", "strip")
        row = QHBoxLayout(strip)
        row.setContentsMargins(SPACE["base"], SPACE["md"], SPACE["base"], SPACE["md"])
        row.setSpacing(SPACE["sm"])

        self.format_selector = FormatSelector(inline=True)
        self.format_selector.changed.connect(self._on_format_chosen)
        row.addWidget(self.format_selector)

        save_label = QLabel("Save to")
        save_label.setProperty("role", "muted")
        row.addWidget(save_label)
        row.addWidget(FolderButton(self.prefs))
        row.addSpacing(6)

        run_label = QLabel("Run")
        run_label.setProperty("role", "muted")
        row.addWidget(run_label)
        row.addWidget(ParallelCombo(self.prefs))

        row.addStretch(1)
        self.download_all_key = TextKey("Download all", self.download_all)
        row.addWidget(self.download_all_key)
        self.download_key = TextKey("Download selected", self.download_selected,
                                    variant="primary", icon_name="download")
        self.download_key.setMinimumWidth(190)
        row.addWidget(self.download_key)
        return strip

    # ------------------------------------------------------------------ public
    def focus_link_field(self) -> None:
        self.link_input.setFocus()
        self.link_input.selectAll()

    @Slot()
    def add_current(self) -> None:
        text = self.link_input.text().strip()
        if not text:
            self._paste()
            return
        if self.queue.add_text(text):
            self.link_input.clear()
            return
        if text == self._search_offer:
            self.link_input.clear()
            self.search_requested.emit(text)
            return
        self._search_offer = text
        self.link_hint.setText(
            f"That is not a link, so nothing was added. Press Enter again to search "
            f"YouTube for \"{humanize.elide(text, 40)}\"."
        )
        self.link_hint.show()

    @Slot()
    def download_selected(self) -> None:
        self.download_requested.emit([item.id for item in self.queue.checked_items()])

    @Slot()
    def download_all(self) -> None:
        self.download_requested.emit([item.id for item in self.queue.items()])

    # --------------------------------------------------------------- list events
    def _on_zone_clicked(self, index: QModelIndex, zone: str, modifiers) -> None:
        row = self.model.row_at(index)
        self.list.setCurrentIndex(index)
        if zone == "remove":
            self.queue.remove([row.id])
        elif zone == "download" and isinstance(row, QueueItem):
            self.download_requested.emit([row.id])
        elif zone == "retry":
            self.queue.retry(row.id)
        elif zone == "chevron":
            self.queue.set_group_expanded(row.id, not row.expanded)
        elif isinstance(row, QueueGroup):
            if zone == "box":
                self.queue.toggle_group(row.id)
            else:
                self.queue.set_group_expanded(row.id, not row.expanded)
        elif isinstance(row, QueueItem):
            self._click_item(index, row, modifiers)

    def _click_item(self, index: QModelIndex, item: QueueItem, modifiers) -> None:
        """A click ticks one row; shift-click carries that tick across a range."""
        target = not item.checked
        if modifiers & Qt.ShiftModifier and self._last_clicked is not None:
            low, high = sorted((self._last_clicked, index.row()))
            spanned = [self.model.row_at(self.model.index(position))
                       for position in range(low, high + 1)]
            self.queue.set_checked(
                [row.id for row in spanned if isinstance(row, QueueItem)], target)
        else:
            self.queue.set_checked([item.id], target)
        self._last_clicked = index.row()

    def _toggle_row(self, index: QModelIndex) -> None:
        row = self.model.row_at(index)
        if isinstance(row, QueueGroup):
            self.queue.toggle_group(row.id)
        elif isinstance(row, QueueItem):
            self.queue.set_checked([row.id], not row.checked)

    def _download_row(self, index: QModelIndex) -> None:
        row = self.model.row_at(index)
        if isinstance(row, QueueItem):
            self.download_requested.emit([row.id])
        elif isinstance(row, QueueGroup):
            self.download_requested.emit(
                [item.id for item in self.queue.group_items(row.id) if item.checked])

    def _remove_row(self, index: QModelIndex) -> None:
        row = self.model.row_at(index)
        if row is None:
            return
        following = index.row()
        self.queue.remove([row.id])
        count = self.model.rowCount()
        if count:
            self.list.setCurrentIndex(self.model.index(min(following, count - 1)))

    def _expand_row(self, index: QModelIndex, expanded: bool) -> None:
        row = self.model.row_at(index)
        if isinstance(row, QueueGroup):
            self.queue.set_group_expanded(row.id, expanded)
            self.list.setCurrentIndex(self.model.index_of(row.id))

    def _show_menu(self, position) -> None:
        index = self.list.indexAt(position)
        row = self.model.row_at(index)
        if row is None:
            return
        menu = QMenu(self)
        if isinstance(row, QueueItem):
            self._fill_item_menu(menu, row)
        elif isinstance(row, QueueGroup):
            self._fill_group_menu(menu, row)
        else:
            if row.error:
                menu.addAction(icons.icon("retry", 16), "Try again",
                               lambda: self.queue.retry(row.id))
            menu.addAction(icons.icon("copy", 16), "Copy link", lambda: _copy(row.url))
            menu.addSeparator()
            menu.addAction(icons.icon("close", 16), "Remove",
                           lambda: self.queue.remove([row.id]))
        menu.exec(self.list.viewport().mapToGlobal(position))

    def _fill_item_menu(self, menu: QMenu, item: QueueItem) -> None:
        menu.addAction(icons.icon("download", 16), "Download now",
                       lambda: self.download_requested.emit([item.id]))
        menu.addAction("Deselect" if item.checked else "Select",
                       lambda: self.queue.set_checked([item.id], not item.checked))
        menu.addSeparator()
        menu.addAction(icons.icon("globe", 16), "Open in Browse",
                       lambda: self.browse_requested.emit(item.entry.url))
        menu.addAction(icons.icon("copy", 16), "Copy link", lambda: _copy(item.entry.url))
        if item.parent_list is not None:
            menu.addSeparator()
            label = ("Add the whole Mix" if item.parent_list.is_mix
                     else "Add the whole playlist")
            menu.addAction(icons.icon("plus", 16), label,
                           lambda: self.queue.add_link(item.parent_list.url, Scope.WHOLE_LIST))
        menu.addSeparator()
        menu.addAction(icons.icon("close", 16), "Remove",
                       lambda: self.queue.remove([item.id]))

    def _fill_group_menu(self, menu: QMenu, group: QueueGroup) -> None:
        items = self.queue.group_items(group.id)
        menu.addAction(icons.icon("download", 16), "Download selected in this playlist",
                       lambda: self.download_requested.emit(
                           [item.id for item in items if item.checked]))
        menu.addAction("Select all in this playlist",
                       lambda: self.queue.set_checked([item.id for item in items], True))
        menu.addAction("Deselect all in this playlist",
                       lambda: self.queue.set_checked([item.id for item in items], False))
        menu.addSeparator()
        menu.addAction(icons.icon("close", 16), "Remove playlist",
                       lambda: self.queue.remove([group.id]))

    # ------------------------------------------------------------------ queue
    def _on_changed(self) -> None:
        self.stack.setCurrentIndex(1 if self.queue.is_empty() else 0)
        # Keys that could only refuse have no business on an empty list.
        self.list_header.setVisible(not self.queue.is_empty())
        reading = any(isinstance(row, PendingLink) and not row.error
                      for row in self.queue.rows())
        if reading:
            self._phase_timer.start()
        else:
            self._phase_timer.stop()
        self._refresh()

    def _refresh(self) -> None:
        items = self.queue.items()
        checked = self.queue.checked_items()
        total, selected = len(items), len(checked)

        self.select_all.setEnabled(total > 0)
        self.select_all.setCheckState(
            Qt.Unchecked if selected == 0
            else Qt.Checked if selected == total else Qt.PartiallyChecked)

        duration = sum(item.entry.duration or 0.0 for item in checked)
        if total:
            parts = [f"{selected} of {humanize.count(total, 'track')} selected"]
            if duration:
                parts.append(humanize.format_duration(duration))
            self.summary_label.setText(" · ".join(parts))
        else:
            self.summary_label.setText("Nothing in the Queue yet")

        self.invert_key.setEnabled(total > 0)
        self.remove_key.setEnabled(selected > 0)
        self.remove_key.setToolTip("Remove the selected tracks from the Queue"
                                   if selected else "Select a track first.")
        self.clear_key.setEnabled(not self.queue.is_empty())

        self.download_key.setEnabled(selected > 0)
        self.download_key.setText(
            f"Download selected ({selected})" if selected else "Download selected")
        self.download_key.setToolTip(
            f"Start these {selected} now, as {self.prefs.describe()}" if selected
            else "Select at least one track first." if total
            else "Add a link first.")
        self.download_all_key.setEnabled(total > 0)
        self.download_all_key.setText(f"Download all ({total})" if total else "Download all")
        self.download_all_key.setToolTip(
            f"Start everything in the Queue, as {self.prefs.describe()}" if total
            else "Add a link first.")

    def _toggle_all(self) -> None:
        items = self.queue.items()
        self.queue.set_all_checked(not all(item.checked for item in items))

    def _on_link_added(self, added: LinkAdded) -> None:
        last = self.model.rowCount() - 1
        if last >= 0:
            self.list.scrollTo(self.model.index(last))

    def _advance_phase(self) -> None:
        if motion.reduced():
            return
        self.delegate.phase += 1
        self.list.viewport().update()

    # ---------------------------------------------------------------- link field
    def _on_link_edited(self, _text: str) -> None:
        self._search_offer = ""
        self.link_hint.hide()

    def _paste(self) -> None:
        text = (QApplication.clipboard().text() or "").strip()
        if text:
            self.link_input.setText(text)
            self.add_current()
        else:
            self.link_input.setFocus()

    # ----------------------------------------------------------------- clipboard
    def _clipboard_link(self) -> str:
        """A YouTube link on the clipboard that is not already on this list."""
        if not self.config.watch_clipboard:
            return ""
        for url in links.find_links(QApplication.clipboard().text() or ""):
            link = links.parse(url)
            if link.is_downloadable and not self.queue.contains_video(link.video_id):
                return url
        return ""

    def _offer_clipboard(self) -> None:
        url = self._clipboard_link()
        if not url or url == self._offered_clip:
            if not url:
                self.clip_notice.hide()
            return
        self._offered_clip = url
        self.clip_label.setText(f"Link on your clipboard: {humanize.elide(url, 72)}")
        self.clip_notice.show()

    def _take_clipboard(self) -> None:
        url = self._offered_clip
        self.clip_notice.hide()
        if url:
            self.queue.add_link(url)

    def _dismiss_clipboard(self) -> None:
        self.clip_notice.hide()

    # ------------------------------------------------------------------ settings
    def _load_prefs(self) -> None:
        self.format_selector.blockSignals(True)
        self.format_selector.set_values(self.prefs.audio_format, self.prefs.bitrate)
        self.format_selector.blockSignals(False)
        self._refresh()

    def _on_format_chosen(self) -> None:
        self.prefs.set_format(self.format_selector.format_key(),
                              self.format_selector.bitrate())

    # ---------------------------------------------------------------- drag and drop
    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt override
        if links.find_links(_mime_text(event.mimeData())):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self.queue.add_text(_mime_text(event.mimeData())):
            event.acceptProposedAction()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self.link_input.setFocus()
        self._offer_clipboard()


def _mime_text(mime) -> str:
    if mime.hasUrls():
        return "\n".join(url.toString() for url in mime.urls())
    return mime.text() if mime.hasText() else ""


def _copy(text: str) -> None:
    QApplication.clipboard().setText(text)
