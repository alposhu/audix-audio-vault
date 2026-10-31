"""The receiver's small instruments: lamps, tick ladders, and tick boxes.

Shared by the painted list rows and the widgets around them, so a lamp in a row and
a lamp in the inspector cannot drift apart.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

from audix.ui import icons
from audix.ui.tokens import COLORS

#: Lit tick width and the gap beside it, in pixels. Fixed, so a ladder keeps the
#: same grain at any width instead of stretching.
TICK = 2.0
TICK_GAP = 2.0


def draw_lamp(painter: QPainter, center: QPointF, color: str, lit: bool = True,
              radius: float = 4.0) -> None:
    """A status lamp. An unlit lamp is an outline, so state survives without color."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    if lit:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(center, radius, radius)
    else:
        painter.setPen(QPen(QColor(color), 1.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(center, radius - 0.75, radius - 0.75)
    painter.restore()


def draw_ladder(painter: QPainter, rect: QRectF, fraction: float, color: str,
                phase: Optional[int] = None) -> None:
    """A row of ticks filling left to right: audix's progress bar.

    ``phase`` draws a short chasing run instead, for work of unknown length, such as
    reading a link before any size is known.
    """
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, False)
    step = TICK + TICK_GAP
    count = max(1, int((rect.width() + TICK_GAP) // step))
    unlit = QColor(COLORS["border"])
    lit = QColor(color)
    if phase is None:
        lit_count = round(max(0.0, min(fraction, 1.0)) * count)
        lit_ticks = range(lit_count)
    else:
        start = phase % count
        lit_ticks = {(start + offset) % count for offset in range(max(4, count // 6))}

    for index in range(count):
        x = rect.left() + index * step
        painter.fillRect(QRectF(x, rect.top(), TICK, rect.height()),
                         lit if index in lit_ticks else unlit)
    painter.restore()


def draw_tick_box(painter: QPainter, rect: QRectF, checked: bool, partial: bool = False,
                  hover: bool = False) -> None:
    """The selection box in list rows, matching ``QCheckBox`` in the stylesheet."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    box = rect.adjusted(0.5, 0.5, -0.5, -0.5)
    filled = checked or partial
    painter.setPen(QPen(QColor(COLORS["primary"] if filled or hover else COLORS["border_hi"]), 1))
    painter.setBrush(QColor(COLORS["primary"] if filled else COLORS["well"]))
    painter.drawRoundedRect(box, 3, 3)
    if checked:
        icons.paint(painter, "check", rect.adjusted(2, 2, -2, -2), COLORS["well"])
    elif partial:
        painter.fillRect(QRectF(rect.left() + 4, rect.center().y() - 1,
                                rect.width() - 8, 2), QColor(COLORS["well"]))
    painter.restore()


def draw_thumbnail(painter: QPainter, rect: QRectF, pixmap: Optional[QPixmap]) -> None:
    """Video artwork in a sharp-cornered frame, or a quiet tile until it arrives."""
    painter.save()
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    if pixmap is None or pixmap.isNull():
        painter.fillRect(rect, QColor(COLORS["surface"]))
        size = min(rect.width(), rect.height()) * 0.5
        icons.paint(painter, "note",
                    QRectF(rect.center().x() - size / 2, rect.center().y() - size / 2,
                           size, size),
                    COLORS["border_hi"])
    else:
        painter.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))
    painter.setPen(QPen(QColor(0, 0, 0, 110), 1))
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))
    painter.restore()
