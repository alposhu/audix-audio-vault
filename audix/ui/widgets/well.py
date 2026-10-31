"""A window recessed into the faceplate.

Content lives behind the plate, not on top of it, so a well has to read as a hole
rather than a dark card. Light comes from above: the top edge falls into shadow, a
soft shade drops onto the glass beneath it, and the lower lip catches the light.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

SHADE_DEPTH = 10
SHADE_ALPHA = 150


class _Shade(QWidget):
    """The shadow the plate casts into the well. Lets every click through."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setProperty("role", "clear")

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        fade = QLinearGradient(0, 0, 0, self.height())
        fade.setColorAt(0.0, QColor(0, 0, 0, SHADE_ALPHA))
        fade.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(self.rect(), fade)
        painter.end()


class Well(QFrame):
    """A recessed frame. Add content to :attr:`body`.

    A side panel floats over the right of the well instead of joining its layout, so
    opening one leaves everything it does not cover exactly where it was.
    """

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "window")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(1, 2, 1, 1)
        self.body.setSpacing(0)
        self._shade = _Shade(self)
        self._panel: Optional[QWidget] = None

    def set_side_panel(self, panel: QWidget) -> None:
        self._panel = panel
        panel.setParent(self)
        self._seat()

    def _seat(self) -> None:
        self._shade.setGeometry(1, 2, self.width() - 2, SHADE_DEPTH)
        self._shade.raise_()
        if self._panel is not None:
            width = self._panel.width()
            self._panel.setGeometry(self.width() - width - 1, 2, width, self.height() - 3)
            self._panel.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._seat()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self._seat()
