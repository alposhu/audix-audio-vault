"""The audix mark, drawn once and used everywhere.

The window icon, the executable's `.ico`, and the repository logo are all the
same drawing at different sizes. Keeping one implementation means the taskbar,
Explorer, Alt-Tab, and the README cannot drift apart — which they had, when each
was drawn separately.

The mark is the product's own signature: a symmetric waveform in the same
two-tone the editor uses, a darker peak envelope with a brighter core, on the
dark bronze plate defined in DESIGN.md.
"""
from __future__ import annotations

from typing import Tuple

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

from audix.ui.tokens import COLORS

#: Relative bar heights, symmetric about the centre. Shaped like real audio -
#: quiet edges, a loud core, a dip in the middle - rather than a linear ramp,
#: so it reads as a waveform and not as a bar chart.
BARS: Tuple[float, ...] = (
    0.22, 0.40, 0.30, 0.62, 0.86, 1.00, 0.78, 1.00, 0.86, 0.62, 0.30, 0.40, 0.22
)

#: A reduced set for small sizes. Thirteen bars turn to mush below ~32px.
BARS_SMALL: Tuple[float, ...] = (0.30, 0.66, 1.00, 0.80, 1.00, 0.66, 0.30)

CORNER = 0.22          # corner radius as a fraction of the tile
INSET = 0.135          # margin inside the tile before the bars begin
CORE_RATIO = 0.62      # inner bright core as a fraction of each bar's height

#: Below this, use the simplified bar set.
SMALL_THRESHOLD = 48


def draw_mark(size: int, with_border: bool = True) -> QPixmap:
    """Render the mark at ``size`` pixels square, transparent outside the tile."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)

    radius = size * CORNER
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(COLORS["bg"]))
    painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)

    if with_border and size >= 32:
        # A hairline edge keeps the tile's shape on a dark page background.
        painter.setBrush(Qt.NoBrush)
        pen = painter.pen()
        pen.setColor(QColor(COLORS["border"]))
        pen.setWidthF(max(1.0, size / 256))
        painter.setPen(pen)
        painter.drawRoundedRect(
            QRectF(pen.widthF() / 2, pen.widthF() / 2,
                   size - pen.widthF(), size - pen.widthF()),
            radius, radius,
        )
        painter.setPen(Qt.NoPen)

    bars = BARS if size >= SMALL_THRESHOLD else BARS_SMALL
    inset = size * INSET
    usable = size - inset * 2
    count = len(bars)
    gap = usable / (count * 2.1)
    bar_w = (usable - gap * (count - 1)) / count
    centre = size / 2
    max_half = usable / 2

    peak = QColor(COLORS["wave_peak"])
    core_colour = QColor(COLORS["wave_rms"])

    for index, amplitude in enumerate(bars):
        x = inset + index * (bar_w + gap)
        half = max_half * amplitude

        painter.setBrush(peak)
        painter.drawRoundedRect(
            QRectF(x, centre - half, bar_w, half * 2), bar_w / 2, bar_w / 2)

        core = half * CORE_RATIO
        painter.setBrush(core_colour)
        painter.drawRoundedRect(
            QRectF(x, centre - core, bar_w, core * 2), bar_w / 2, bar_w / 2)

    painter.end()
    return pixmap


def app_icon() -> QIcon:
    """Multi-resolution icon for the window and taskbar."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(draw_mark(size))
    return icon
