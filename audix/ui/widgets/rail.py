"""The navigation rail.

Replaces the tab bar. A tab bar was already at four destinations with no room
for a fifth, and no room at all for the editor's transport bar; a vertical rail
scales past that and gives the workspace its full width back.

Each item is icon-over-label so the destination is identifiable at a glance and
still readable — an icon-only rail forces users to learn glyphs, which for a
five-item app is a cost with no benefit.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QLabel, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from audix.ui.tokens import COLORS, SPACE

RAIL_WIDTH = 76


@dataclass
class RailItem:
    key: str
    label: str
    glyph: str
    tooltip: str


class NavigationRail(QWidget):
    """Vertical destination switcher."""

    changed = Signal(int)          # index

    def __init__(self, items: List[RailItem], parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "rail")
        self.setFixedWidth(RAIL_WIDTH)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        self._items = items
        self._buttons: List[QToolButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, SPACE["md"], 6, SPACE["md"])
        layout.setSpacing(4)

        wordmark = QLabel("audix")
        wordmark.setAlignment(Qt.AlignCenter)
        wordmark.setStyleSheet(
            f"color: {COLORS['primary']}; font-weight: 700; font-size: 13px;"
            "letter-spacing: 0.5px; padding-bottom: 6px;"
        )
        layout.addWidget(wordmark)

        for index, item in enumerate(items):
            button = self._make_button(item, index)
            self._buttons.append(button)
            self._group.addButton(button, index)
            layout.addWidget(button)

        layout.addStretch(1)

        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color: {COLORS['faint']}; font-size: 10px;")
        layout.addWidget(self._status)

        self._group.idClicked.connect(self._on_clicked)
        if self._buttons:
            self._buttons[0].setChecked(True)

    def _make_button(self, item: RailItem, index: int) -> QToolButton:
        button = QToolButton()
        button.setProperty("role", "railitem")
        button.setText(f"{item.glyph}\n{item.label}")
        button.setToolTip(f"{item.tooltip}   (Ctrl+{index + 1})")
        button.setCheckable(True)
        button.setAutoRaise(True)
        button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        button.setFixedSize(QSize(RAIL_WIDTH - 12, 54))
        button.setCursor(Qt.PointingHandCursor)
        return button

    # ------------------------------------------------------------------ public
    def set_current(self, index: int) -> None:
        if 0 <= index < len(self._buttons):
            self._buttons[index].setChecked(True)

    def current(self) -> int:
        return self._group.checkedId()

    def set_badge(self, index: int, text: str) -> None:
        """Append a small count to a destination (e.g. active downloads)."""
        if not (0 <= index < len(self._buttons)):
            return
        item = self._items[index]
        label = f"{item.label} {text}" if text else item.label
        self._buttons[index].setText(f"{item.glyph}\n{label}")

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def install_shortcuts(self, target: QWidget) -> None:
        """Ctrl+1..N jump between destinations."""
        for index in range(len(self._buttons)):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index + 1}"), target)
            shortcut.activated.connect(
                lambda checked=False, i=index: self._activate(i)
            )

    def _activate(self, index: int) -> None:
        self.set_current(index)
        self.changed.emit(index)

    def _on_clicked(self, index: int) -> None:
        self.changed.emit(index)
