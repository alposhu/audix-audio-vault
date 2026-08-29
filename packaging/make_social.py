#!/usr/bin/env python3
"""Generate audix/assets/social-preview.png for GitHub's social preview.

GitHub renders this at 1280x640 wherever a repo link is unfurled - Twitter/X,
Discord, Slack, LinkedIn. A square logo uploaded here is letterboxed with dead
space on both sides, so this composes a proper landscape card instead: the
shared mark, the wordmark, a one-line description, and a waveform strip drawn
from the same peak/RMS two-tone the editor uses.

    python packaging/make_social.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

WIDTH, HEIGHT = 1280, 640

#: GitHub's documented ceiling for the social preview image.
MAX_BYTES = 1024 * 1024


def compose():
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QPainter, QPixmap

    from audix.ui.branding import draw_mark
    from audix.ui.tokens import COLORS, ui_font_stack

    canvas = QPixmap(WIDTH, HEIGHT)
    canvas.fill(QColor(COLORS["bg"]))

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)

    # --- decorative waveform band across the lower third ------------------
    # Deterministic pseudo-audio: layered sines, so the shape looks like a
    # real signal rather than noise, and is identical on every regeneration.
    band_centre = HEIGHT * 0.78
    band_height = HEIGHT * 0.17
    bar_w, gap = 5.0, 4.0
    count = int(WIDTH / (bar_w + gap))
    painter.setPen(Qt.NoPen)
    for i in range(count):
        t = i / count
        envelope = (
            0.55 + 0.45 * math.sin(t * math.pi * 3.1)
        ) * (0.35 + 0.65 * math.sin(t * math.pi))
        detail = 0.55 + 0.45 * math.sin(t * math.pi * 37.0)
        amp = max(0.06, envelope * detail)
        half = band_height * amp
        x = i * (bar_w + gap)

        painter.setBrush(QColor(COLORS["wave_peak"]))
        painter.drawRoundedRect(
            QRectF(x, band_centre - half, bar_w, half * 2), 2.5, 2.5)
        core = half * 0.55
        painter.setBrush(QColor(COLORS["wave_rms"]))
        painter.drawRoundedRect(
            QRectF(x, band_centre - core, bar_w, core * 2), 2.5, 2.5)

    # --- mark --------------------------------------------------------------
    # Centre the mark + text lockup horizontally. Measured rather than eyeballed:
    # the description line is the widest element, so the whole group is laid out
    # from its width, leaving equal margins instead of a dead right third.
    mark_size = 188
    gap_to_text = 44
    probe = QFont(ui_font_stack()[0])
    probe.setPixelSize(27)
    from PySide6.QtGui import QFontMetrics

    widest = QFontMetrics(probe).horizontalAdvance(
        "Pull audio out of YouTube and finish it into a library:")
    lockup_w = mark_size + gap_to_text + widest
    mark_x = max(72, int((WIDTH - lockup_w) / 2))
    mark_y = 118
    painter.drawPixmap(mark_x, mark_y, draw_mark(mark_size))

    # --- wordmark and copy -------------------------------------------------
    family = ui_font_stack()[0]
    text_x = mark_x + mark_size + gap_to_text

    wordmark = QFont(family)
    wordmark.setPixelSize(104)
    wordmark.setWeight(QFont.Weight.Bold)
    wordmark.setLetterSpacing(QFont.PercentageSpacing, 97)
    painter.setFont(wordmark)
    painter.setPen(QColor(COLORS["ink"]))
    painter.drawText(text_x, mark_y + 104, "audix")

    subtitle = QFont(family)
    subtitle.setPixelSize(30)
    subtitle.setWeight(QFont.Weight.Medium)
    painter.setFont(subtitle)
    painter.setPen(QColor(COLORS["primary"]))
    painter.drawText(text_x + 4, mark_y + 152, "Audio Vault")

    body = QFont(family)
    body.setPixelSize(27)
    painter.setFont(body)
    painter.setPen(QColor(COLORS["muted"]))
    painter.drawText(
        QRectF(text_x, mark_y + 172, WIDTH - text_x - 90, 90),
        Qt.TextWordWrap,
        "Pull audio out of YouTube and finish it into a library:\n"
        "converted, trimmed, leveled, tagged, and split.",
    )

    painter.end()
    return canvas


def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])   # noqa: F841

    assets = ROOT / "audix" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    target = assets / "social-preview.png"

    if not compose().save(str(target), "PNG"):
        print(f"Failed to write {target}", file=sys.stderr)
        return 1

    size = target.stat().st_size
    print(f"Wrote {target.relative_to(ROOT)}  "
          f"({WIDTH}x{HEIGHT}, {size:,} bytes)")
    if size > MAX_BYTES:
        print(f"WARNING: exceeds GitHub's 1 MB limit by "
              f"{(size - MAX_BYTES):,} bytes", file=sys.stderr)
        return 1
    print(f"Within GitHub's 1 MB limit ({size / MAX_BYTES:.0%} of it).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
