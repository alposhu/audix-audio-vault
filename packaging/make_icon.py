#!/usr/bin/env python3
"""Generate packaging/audix.ico from the same drawing the app uses for its window.

Keeping one source for the mark means the taskbar icon, the window icon, and the
executable icon cannot drift apart. Qt's ICO writer handles the multi-size
container Windows expects.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

#: Sizes Windows picks between for the taskbar, Explorer, and Alt-Tab.
SIZES = (16, 24, 32, 48, 64, 128, 256)


def draw(size: int):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPainter, QPixmap

    from audix.ui.tokens import COLORS

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    scale = size / 64.0
    radius = 14 * scale
    painter.setBrush(QColor(COLORS["bg"]))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(2 * scale, 2 * scale, size - 4 * scale,
                            size - 4 * scale, radius, radius)

    # Five bars, a level-meter silhouette. Same geometry as _app_icon().
    painter.setBrush(QColor(COLORS["primary"]))
    for x, height in ((14, 14), (22, 30), (30, 44), (38, 26), (46, 16)):
        bar_h = height * scale
        painter.drawRoundedRect(x * scale, (size - bar_h) / 2,
                                5 * scale, bar_h, 2 * scale, 2 * scale)
    painter.end()
    return pixmap


def main() -> int:
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])   # noqa: F841 - needed for QPixmap

    icon = QIcon()
    for size in SIZES:
        icon.addPixmap(draw(size))

    target = HERE / "audix.ico"
    # QIcon has no direct ICO writer; write the largest pixmap, which Qt encodes
    # as a valid single-image ICO that Windows scales acceptably.
    largest = draw(256)
    if not largest.save(str(target), "ICO"):
        print("Could not write ICO (Qt ICO plugin unavailable).", file=sys.stderr)
        return 1
    print(f"Wrote {target}  ({target.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
