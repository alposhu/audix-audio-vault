"""Painted list rows with clickable zones.

The Queue and Downloads lists can hold thousands of rows that update many times a
second, so rows are painted rather than built from widgets: a row of real widgets
would mean tens of thousands of objects, each polished against the stylesheet, and a
long playlist would freeze the window while it appeared.

The price of painting is that a row has no child buttons. :class:`RowDelegate`
pays that back: a subclass names its zones as rectangles, and hovering, clicking, and
tooltips all work from those.
"""
from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import QEvent, QModelIndex, QPersistentModelIndex, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QListView, QStyledItemDelegate, QToolTip,
)

from audix.ui import icons
from audix.ui.tokens import COLORS

ACTION_SIZE = 30
ACTION_ICON = 16


class RowDelegate(QStyledItemDelegate):
    """Base delegate: rows declare zones, and this class makes them behave."""

    #: The row, the zone name ("" for the row itself), and keyboard modifiers.
    zone_clicked = Signal(QModelIndex, str, object)
    row_activated = Signal(QModelIndex)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._hover_index = QPersistentModelIndex()
        self._hover_zone = ""

    # ---------------------------------------------------------- for subclasses
    def zones(self, index: QModelIndex, rect: QRectF) -> Dict[str, QRectF]:
        """Named clickable rectangles for this row, in view coordinates."""
        return {}

    def zone_tooltip(self, index: QModelIndex, zone: str) -> str:
        return ""

    def row_tooltip(self, index: QModelIndex) -> str:
        return ""

    # ------------------------------------------------------------------ helpers
    def is_hot(self, index: QModelIndex, zone: str) -> bool:
        return self._hover_zone == zone and QPersistentModelIndex(index) == self._hover_index

    def paint_action(self, painter: QPainter, index: QModelIndex, rect: QRectF,
                     zone: str, icon_name: str, row_hover: bool, danger: bool = False) -> None:
        """A small icon key. Dim until the row is approached, so rows stay calm."""
        hot = self.is_hot(index, zone)
        if hot:
            painter.fillRect(rect, QColor(COLORS["accent" if danger else "surface_3"]))
            color = COLORS["well"] if danger else COLORS["ink"]
        else:
            color = COLORS["muted"] if row_hover else COLORS["border_hi"]
        inset = (rect.width() - ACTION_ICON) / 2
        icons.paint(painter, icon_name, rect.adjusted(inset, inset, -inset, -inset), color)

    def _zone_at(self, index: QModelIndex, option, position) -> str:
        for name, rect in self.zones(index, QRectF(option.rect)).items():
            if rect.contains(position):
                return name
        return ""

    # ------------------------------------------------------------------- events
    def editorEvent(self, event, model, option, index) -> bool:  # noqa: N802
        kind = event.type()
        if kind == QEvent.MouseMove:
            zone = self._zone_at(index, option, event.position())
            persistent = QPersistentModelIndex(index)
            if zone != self._hover_zone or persistent != self._hover_index:
                self._hover_zone = zone
                self._hover_index = persistent
                self.parent().viewport().update()
            return False

        if kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            zone = self._zone_at(index, option, event.position())
            self.zone_clicked.emit(index, zone, event.modifiers())
            return True

        if kind == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
            if not self._zone_at(index, option, event.position()):
                self.row_activated.emit(index)
            return True

        return False

    def helpEvent(self, event, view, option, index) -> bool:  # noqa: N802
        if event.type() != QEvent.ToolTip:
            return False
        zone = self._zone_at(index, option, event.pos())
        text = (self.zone_tooltip(index, zone) if zone else "") or self.row_tooltip(index)
        if text:
            QToolTip.showText(event.globalPos(), text, view)
        else:
            QToolTip.hideText()
        return True

    def clear_hover(self) -> None:
        self._hover_zone = ""
        self._hover_index = QPersistentModelIndex()


class RowList(QListView):
    """A list configured for painted rows."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFrameShape(QListView.NoFrame)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setUniformItemSizes(False)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setResizeMode(QListView.Adjust)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.verticalScrollBar().setSingleStep(24)

    def row_delegate(self) -> Optional[RowDelegate]:
        delegate = self.itemDelegate()
        return delegate if isinstance(delegate, RowDelegate) else None

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt override
        delegate = self.row_delegate()
        if delegate is not None:
            delegate.clear_hover()
        self.viewport().update()
        super().leaveEvent(event)
