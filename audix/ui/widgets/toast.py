"""Small notes in the corner of the window.

These replace a modal dialog wherever nothing needs to stop for the answer. Each
one says what happened and, when there is a sensible next step, offers it as the
one button on the note.
"""
from __future__ import annotations

from typing import Callable, List, Optional

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton, QToolButton, QWidget,
)

from audix.ui import icons
from audix.ui.tokens import COLORS, SPACE
from audix.ui.widgets.controls import Lamp

MARGIN = SPACE["base"]
#: Clears the strip along the bottom of each page, which holds its main action.
BOTTOM_MARGIN = 84
GAP = SPACE["sm"]
WIDTH = 380
MAX_VISIBLE = 4

TONES = {"info": "primary", "success": "success", "error": "accent", "warning": "warning"}


class _Toast(QFrame):
    def __init__(self, text: str, tone: str, action: Optional[str],
                 on_action: Optional[Callable[[], None]], timeout: int,
                 on_gone: Callable[["_Toast"], None], parent: QWidget) -> None:
        super().__init__(parent)
        self.setProperty("role", "toast")
        self.setFixedWidth(WIDTH)
        self._on_gone = on_gone
        self._on_action = on_action

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 120))
        self.setGraphicsEffect(shadow)

        row = QHBoxLayout(self)
        row.setContentsMargins(SPACE["md"], SPACE["sm"] + 2, SPACE["sm"], SPACE["sm"] + 2)
        row.setSpacing(SPACE["sm"] + 2)
        row.addWidget(Lamp(COLORS[TONES.get(tone, "primary")]), 0, Qt.AlignTop)

        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.PlainText)
        row.addWidget(self.label, 1)

        if action:
            button = QPushButton(action)
            button.setProperty("variant", "tool")
            button.clicked.connect(self._act)
            row.addWidget(button, 0, Qt.AlignVCenter)

        close = QToolButton()
        close.setProperty("role", "nav")
        close.setIcon(icons.icon("close", 14, COLORS["muted"]))
        close.setToolTip("Dismiss")
        close.clicked.connect(self.dismiss)
        row.addWidget(close, 0, Qt.AlignTop)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(timeout)
        self._timer.timeout.connect(self.dismiss)
        if timeout > 0:
            self._timer.start()

    def _act(self) -> None:
        if self._on_action:
            self._on_action()
        self.dismiss()

    def dismiss(self) -> None:
        self._timer.stop()
        self.hide()
        self._on_gone(self)
        self.deleteLater()

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._timer.stop()      # never vanish from under someone reading it
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._timer.interval() > 0:
            self._timer.start()
        super().leaveEvent(event)


class Toasts(QObject):
    """Stacks notes in the bottom-right corner of a host widget."""

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self._host = host
        self._stack: List[_Toast] = []
        host.installEventFilter(self)

    def show(self, text: str, tone: str = "info", action: Optional[str] = None,
             on_action: Optional[Callable[[], None]] = None, timeout: int = 6000) -> None:
        while len(self._stack) >= MAX_VISIBLE:
            self._stack[0].dismiss()
        toast = _Toast(text, tone, action, on_action, timeout, self._remove, self._host)
        self._stack.append(toast)
        toast.show()
        toast.adjustSize()
        self._reflow()

    def _remove(self, toast: _Toast) -> None:
        if toast in self._stack:
            self._stack.remove(toast)
        self._reflow()

    def _reflow(self) -> None:
        bottom = self._host.height() - BOTTOM_MARGIN
        for toast in reversed(self._stack):
            height = toast.sizeHint().height()
            toast.setGeometry(self._host.width() - WIDTH - MARGIN, bottom - height,
                              WIDTH, height)
            toast.raise_()
            bottom -= height + GAP

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self._host and event.type() == QEvent.Resize:
            self._reflow()
        return False
