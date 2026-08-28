"""Segmented level meter with peak hold.

Colour follows the standard broadcast convention (green / amber / red by zone),
but the numeric dBFS readout beside it carries the same information, so the
meter remains usable without colour perception.
"""
from __future__ import annotations

from typing import List

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from audix.ui.tokens import COLORS

#: Segment boundaries in dBFS, quietest first.
FLOOR_DB = -60.0
WARN_DB = -18.0
HOT_DB = -3.0

SEGMENTS = 22

#: How fast the peak-hold marker falls, in dB per update tick.
PEAK_DECAY_DB = 0.7


class LevelMeter(QWidget):
    """Stereo (or mono) output meter driven by polled engine snapshots."""

    def __init__(self, channels: int = 2, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.channels = max(1, channels)
        self._levels: List[float] = [FLOOR_DB] * self.channels
        self._holds: List[float] = [FLOOR_DB] * self.channels
        self.setFixedWidth(10 * self.channels + 4)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setToolTip("Output level. Peak hold falls back slowly.")

    def set_channels(self, channels: int) -> None:
        channels = max(1, channels)
        if channels == self.channels:
            return
        self.channels = channels
        self._levels = [FLOOR_DB] * channels
        self._holds = [FLOOR_DB] * channels
        self.setFixedWidth(10 * channels + 4)
        self.update()

    def set_levels(self, *amplitudes: float) -> None:
        """Feed linear amplitudes (0..1); converted to dBFS internally."""
        from audix.core.audio.dsp import linear_to_db

        for index in range(self.channels):
            value = amplitudes[index] if index < len(amplitudes) else 0.0
            db = linear_to_db(value) if value > 0 else FLOOR_DB
            self._levels[index] = max(FLOOR_DB, db)
            if db >= self._holds[index]:
                self._holds[index] = db
            else:
                self._holds[index] = max(FLOOR_DB, self._holds[index] - PEAK_DECAY_DB)
        self.update()

    def reset(self) -> None:
        self._levels = [FLOOR_DB] * self.channels
        self._holds = [FLOOR_DB] * self.channels
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(10 * self.channels + 4, 120)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(COLORS["surface_2"]))

        height = self.height()
        segment_height = max(2, height // SEGMENTS)

        for channel in range(self.channels):
            x = 2 + channel * 10
            level = self._levels[channel]
            hold = self._holds[channel]

            for index in range(SEGMENTS):
                # Segment 0 is at the bottom (quietest).
                fraction = (index + 1) / SEGMENTS
                db = FLOOR_DB + fraction * (0.0 - FLOOR_DB)
                y = height - (index + 1) * segment_height

                lit = level >= db
                colour = QColor(self._zone_color(db))
                if not lit:
                    colour.setAlpha(38)
                painter.fillRect(QRect(x, y, 8, segment_height - 1), colour)

            # Peak-hold marker
            if hold > FLOOR_DB:
                fraction = (hold - FLOOR_DB) / (0.0 - FLOOR_DB)
                y = int(height - fraction * height)
                painter.fillRect(QRect(x, max(0, y - 1), 8, 2),
                                 QColor(COLORS["ink"]))
        painter.end()

    @staticmethod
    def _zone_color(db: float) -> str:
        if db >= HOT_DB:
            return COLORS["accent"]
        if db >= WARN_DB:
            return COLORS["warning"]
        return COLORS["success"]
