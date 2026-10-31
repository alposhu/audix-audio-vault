"""The waveform canvas.

Draws a two-tone waveform: a dark min/max peak envelope with a brighter RMS body
over it. A peak-only waveform is a solid block that hides dynamics entirely,
which is exactly the information someone scrubbing for a track boundary needs.

Repaint cost is bounded by widget width, not by file duration. All amplitude
data comes from a precomputed :class:`PeakPyramid`, and the level is chosen so
each pixel maps to roughly one bucket. Scrolling a three-hour file costs the
same as scrolling a three-minute one.

Interaction follows the vocabulary users already carry from other editors:
click to position, drag to select, wheel to scroll, Ctrl+wheel to zoom around
the cursor, double-click to select everything.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from audix.ui.tokens import COLORS, mono_font_stack
from audix.utils.humanize import format_duration

log = logging.getLogger("audix.ui.waveform")

#: Height of the time ruler strip along the top.
RULER_HEIGHT = 22

#: Pixels within which a selection edge grabs the cursor.
EDGE_GRAB = 6

#: Furthest zoom, expressed as seconds visible across the whole widget.
MIN_VISIBLE_SECONDS = 0.02

#: Ceiling on display gain, so a near-silent file cannot amplify dither into
#: something that looks like content.
MAX_VERTICAL_SCALE = 64.0


@dataclass
class Marker:
    position: float
    label: str
    is_chapter: bool = False


class WaveformView(QWidget):
    """Scrollable, zoomable waveform with selection and playhead."""

    selection_changed = Signal(float, float)     # start, end seconds (equal = none)
    playhead_moved = Signal(float)               # seconds, from user interaction
    view_changed = Signal(float, float)          # visible start, end seconds
    marker_activated = Signal(float)             # double-clicked marker position

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setAutoFillBackground(False)

        self._pyramid = None
        self._duration = 0.0

        self._view_start = 0.0
        self._view_end = 0.0
        self._playhead = 0.0
        self._selection: Optional[Tuple[float, float]] = None

        self._markers: List[Marker] = []
        self._cuts: List[Tuple[float, float]] = []
        self._clip_positions: List[float] = []

        self._dragging = False
        self._drag_anchor = 0.0
        self._drag_mode = "select"           # "select" | "edge-l" | "edge-r"
        self._hover_x: Optional[int] = None

        self._analysing = False
        self._analysis_progress = 0.0

        # Vertical scale. A great deal of real source material - un-normalized
        # rips, classical, field recordings - peaks far below full scale and
        # would otherwise draw as an unreadable flat line in a tall canvas.
        # The display is fitted to the file's own peak, and the factor is shown
        # so the view never silently misrepresents level.
        self._v_scale = 1.0
        self._auto_fit_vertical = True
        self._source_peak = 1.0
        self._show_placeholder = True

        self._mono_font = QFont(mono_font_stack()[0])
        self._mono_font.setPixelSize(10)
        self._mono_font.setFixedPitch(True)

        # Cached geometry, invalidated on resize or view change.
        self._cache_key = None
        self._cache_env = None

    # ------------------------------------------------------------------ state
    def set_pyramid(self, pyramid, duration: float) -> None:
        self._pyramid = pyramid
        self._duration = max(0.0, float(duration))
        self._view_start = 0.0
        self._view_end = self._duration
        self._playhead = 0.0
        self._selection = None
        self._source_peak = max(1e-4, pyramid.peak_amplitude() if pyramid else 1.0)
        if self._auto_fit_vertical:
            self.fit_vertical()
        self._invalidate()
        self.update()
        self.view_changed.emit(self._view_start, self._view_end)

    # -------------------------------------------------------- vertical scale
    def fit_vertical(self) -> None:
        """Scale the display so the file's loudest point nearly fills the canvas."""
        self._v_scale = max(1.0, min(MAX_VERTICAL_SCALE, 0.92 / self._source_peak))
        self.update()

    def set_vertical_scale(self, scale: float) -> None:
        self._auto_fit_vertical = False
        self._v_scale = max(1.0, min(MAX_VERTICAL_SCALE, scale))
        self.update()

    def scale_vertical_by(self, factor: float) -> None:
        self.set_vertical_scale(self._v_scale * factor)

    def reset_vertical(self) -> None:
        """Return to true scale, where the canvas edge means 0 dBFS."""
        self._auto_fit_vertical = False
        self._v_scale = 1.0
        self.update()

    @property
    def vertical_scale(self) -> float:
        return self._v_scale

    @property
    def source_peak_db(self) -> float:
        from audix.core.audio.dsp import linear_to_db
        return linear_to_db(self._source_peak)

    def set_show_placeholder(self, show: bool) -> None:
        """Whether to paint the 'no audio' text. Off when an overlay owns it."""
        self._show_placeholder = show
        self.update()

    def clear(self) -> None:
        self._pyramid = None
        self._duration = 0.0
        self._view_start = self._view_end = 0.0
        self._playhead = 0.0
        self._selection = None
        self._markers = []
        self._cuts = []
        self._clip_positions = []
        self._invalidate()
        self.update()

    def set_analysing(self, active: bool, progress: float = 0.0) -> None:
        self._analysing = active
        self._analysis_progress = progress
        self.update()

    @property
    def has_audio(self) -> bool:
        return self._pyramid is not None and self._duration > 0

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def selection(self) -> Optional[Tuple[float, float]]:
        return self._selection

    @property
    def playhead(self) -> float:
        return self._playhead

    def set_playhead(self, seconds: float, follow: bool = False) -> None:
        self._playhead = max(0.0, min(seconds, self._duration))
        if follow and self.has_audio:
            self._follow_playhead()
        self.update()

    def set_selection(self, start: Optional[float], end: Optional[float]) -> None:
        if start is None or end is None or abs(end - start) < 1e-6:
            self._selection = None
        else:
            lo, hi = sorted((max(0.0, start), min(end, self._duration)))
            self._selection = (lo, hi)
        self.update()
        s, e = self._selection or (0.0, 0.0)
        self.selection_changed.emit(s, e)

    def select_all(self) -> None:
        if self.has_audio:
            self.set_selection(0.0, self._duration)

    def set_markers(self, markers: List[Marker]) -> None:
        self._markers = list(markers)
        self.update()

    def set_cuts(self, cuts: List[Tuple[float, float]]) -> None:
        self._cuts = list(cuts)
        self.update()

    def set_clip_positions(self, positions: List[float]) -> None:
        self._clip_positions = list(positions)
        self.update()

    # ------------------------------------------------------------------- zoom
    def zoom_to(self, start: float, end: float) -> None:
        if not self.has_audio or end <= start:
            return
        span = max(MIN_VISIBLE_SECONDS, min(end - start, self._duration))
        start = max(0.0, min(start, self._duration - span))
        self._view_start, self._view_end = start, start + span
        self._invalidate()
        self.update()
        self.view_changed.emit(self._view_start, self._view_end)

    def zoom_by(self, factor: float, focus_seconds: Optional[float] = None) -> None:
        """Zoom around a focal point, defaulting to the view centre."""
        if not self.has_audio:
            return
        span = self._view_end - self._view_start
        focus = focus_seconds if focus_seconds is not None else (
            self._view_start + span / 2
        )
        new_span = max(MIN_VISIBLE_SECONDS, min(span / factor, self._duration))
        ratio = (focus - self._view_start) / span if span else 0.5
        self.zoom_to(focus - new_span * ratio, focus - new_span * ratio + new_span)

    def zoom_fit(self) -> None:
        if self.has_audio:
            self.zoom_to(0.0, self._duration)

    def zoom_selection(self) -> None:
        if self._selection:
            start, end = self._selection
            pad = (end - start) * 0.05
            self.zoom_to(start - pad, end + pad)

    def scroll_by(self, seconds: float) -> None:
        span = self._view_end - self._view_start
        self.zoom_to(self._view_start + seconds, self._view_start + seconds + span)

    def _follow_playhead(self) -> None:
        """Page the view when the playhead runs off the right edge."""
        span = self._view_end - self._view_start
        if span <= 0 or span >= self._duration:
            return
        if self._playhead > self._view_end - span * 0.1:
            self.zoom_to(self._playhead - span * 0.5, self._playhead + span * 0.5)
        elif self._playhead < self._view_start:
            self.zoom_to(self._playhead, self._playhead + span)

    # -------------------------------------------------------------- mapping
    def _wave_rect(self) -> QRect:
        return QRect(0, RULER_HEIGHT, self.width(), max(1, self.height() - RULER_HEIGHT))

    def x_to_seconds(self, x: float) -> float:
        width = max(1, self.width())
        span = self._view_end - self._view_start
        return self._view_start + (x / width) * span

    def seconds_to_x(self, seconds: float) -> float:
        span = self._view_end - self._view_start
        if span <= 0:
            return 0.0
        return (seconds - self._view_start) / span * self.width()

    def _invalidate(self) -> None:
        self._cache_key = None
        self._cache_env = None

    # ------------------------------------------------------------------ input
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if not self.has_audio:
            return
        position = self.x_to_seconds(event.position().x())
        if event.button() == Qt.LeftButton:
            self._drag_mode = self._edge_at(event.position().x())
            self._dragging = True
            if self._drag_mode == "select":
                self._drag_anchor = position
                self.set_selection(None, None)
                self._playhead = position
                self.playhead_moved.emit(position)
            elif self._selection:
                # Dragging an existing edge keeps the opposite edge anchored.
                self._drag_anchor = (self._selection[1] if self._drag_mode == "edge-l"
                                     else self._selection[0])
            self.update()
        elif event.button() == Qt.MiddleButton:
            self._playhead = position
            self.playhead_moved.emit(position)
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._hover_x = int(event.position().x())
        if not self.has_audio:
            return
        if self._dragging:
            position = self.x_to_seconds(event.position().x())
            self.set_selection(self._drag_anchor, position)
        else:
            edge = self._edge_at(event.position().x())
            self.setCursor(Qt.SizeHorCursor if edge != "select" else Qt.IBeamCursor)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._dragging:
            self._dragging = False
            # A click without movement clears the selection rather than leaving
            # a zero-width one behind.
            if self._selection and self._selection[1] - self._selection[0] < 0.005:
                self.set_selection(None, None)
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if not self.has_audio:
            return
        position = self.x_to_seconds(event.position().x())
        for marker in self._markers:
            if abs(self.seconds_to_x(marker.position) - event.position().x()) < 8:
                self.marker_activated.emit(marker.position)
                return
        self.select_all()

    def wheelEvent(self, event) -> None:  # noqa: N802
        if not self.has_audio:
            return
        delta = event.angleDelta().y()
        if event.modifiers() & Qt.ShiftModifier:
            # Shift+wheel adjusts vertical (amplitude) zoom, as in most editors.
            self.scale_vertical_by(1.2 if delta > 0 else 1 / 1.2)
        elif event.modifiers() & Qt.ControlModifier:
            focus = self.x_to_seconds(event.position().x())
            self.zoom_by(1.25 if delta > 0 else 1 / 1.25, focus)
        else:
            span = self._view_end - self._view_start
            self.scroll_by(-delta / 120.0 * span * 0.12)
        event.accept()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover_x = None
        self.update()

    def _edge_at(self, x: float) -> str:
        if not self._selection:
            return "select"
        left = self.seconds_to_x(self._selection[0])
        right = self.seconds_to_x(self._selection[1])
        if abs(x - left) <= EDGE_GRAB:
            return "edge-l"
        if abs(x - right) <= EDGE_GRAB:
            return "edge-r"
        return "select"

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(900, 260)

    # ------------------------------------------------------------------ paint
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.fillRect(self.rect(), QColor(COLORS["well"]))

        if not self.has_audio:
            self._paint_empty(painter)
            painter.end()
            return

        wave = self._wave_rect()
        self._paint_ruler(painter)
        self._paint_grid(painter, wave)
        self._paint_selection_wash(painter, wave)
        self._paint_waveform(painter, wave)
        self._paint_cuts(painter, wave)
        self._paint_clips(painter, wave)
        self._paint_markers(painter)
        self._paint_selection_edges(painter, wave)
        self._paint_playhead(painter)
        self._paint_hover(painter, wave)
        if self._analysing:
            self._paint_analysing(painter)
        painter.end()

    def _paint_empty(self, painter: QPainter) -> None:
        # When an overlay owns the empty state, painting a second message here
        # draws one string on top of the other.
        if self._analysing:
            painter.setPen(QColor(COLORS["faint"]))
            font = QFont(self.font())
            font.setPixelSize(13)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignCenter, "Analysing audio…")
            self._paint_analysing(painter)
        elif self._show_placeholder:
            painter.setPen(QColor(COLORS["faint"]))
            font = QFont(self.font())
            font.setPixelSize(13)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignCenter, "No audio loaded")

    def _paint_ruler(self, painter: QPainter) -> None:
        rect = QRect(0, 0, self.width(), RULER_HEIGHT)
        painter.fillRect(rect, QColor(COLORS["surface"]))
        painter.setPen(QPen(QColor(COLORS["border"]), 1))
        painter.drawLine(0, RULER_HEIGHT - 1, self.width(), RULER_HEIGHT - 1)

        span = self._view_end - self._view_start
        if span <= 0:
            return
        step = _tick_step(span, self.width())
        painter.setFont(self._mono_font)
        metrics = QFontMetrics(self._mono_font)

        first = int(self._view_start / step) * step
        tick = first
        while tick <= self._view_end:
            x = int(self.seconds_to_x(tick))
            if 0 <= x <= self.width():
                painter.setPen(QPen(QColor(COLORS["border_hi"]), 1))
                painter.drawLine(x, RULER_HEIGHT - 6, x, RULER_HEIGHT - 1)
                label = _tick_label(tick, step)
                painter.setPen(QColor(COLORS["muted"]))
                painter.drawText(x + 4, RULER_HEIGHT - 8 + metrics.ascent() // 2, label)
            tick += step

    def _paint_grid(self, painter: QPainter, wave: QRect) -> None:
        # Centre line only: a full grid competes with the waveform for attention.
        painter.setPen(QPen(QColor(COLORS["surface_2"]), 1))
        middle = wave.top() + wave.height() // 2
        painter.drawLine(wave.left(), middle, wave.right(), middle)

    def _paint_selection_wash(self, painter: QPainter, wave: QRect) -> None:
        if not self._selection:
            return
        left = int(self.seconds_to_x(self._selection[0]))
        right = int(self.seconds_to_x(self._selection[1]))
        if right < left:
            left, right = right, left
        wash = QColor(COLORS["primary"])
        wash.setAlpha(38)
        painter.fillRect(QRect(left, wave.top(), max(1, right - left), wave.height()),
                         wash)

    def _paint_waveform(self, painter: QPainter, wave: QRect) -> None:
        envelope = self._envelope(wave.width())
        if envelope is None:
            return
        minimum, maximum, rms = envelope

        middle = wave.top() + wave.height() / 2
        half = wave.height() / 2 - 2
        scale = self._v_scale

        def to_y(value: float) -> float:
            # Clamp after scaling so an amplified quiet file cannot draw
            # outside its own canvas.
            return middle - max(-1.0, min(1.0, value * scale)) * half

        # Peak envelope: the outer, darker silhouette.
        painter.setPen(QPen(QColor(COLORS["wave_peak"]), 1))
        for x in range(len(maximum)):
            top = to_y(float(maximum[x]))
            bottom = to_y(float(minimum[x]))
            if bottom - top < 1:
                bottom = top + 1
            painter.drawLine(int(x), int(top), int(x), int(bottom))

        # RMS body: the brighter inner shape that makes dynamics legible.
        painter.setPen(QPen(QColor(COLORS["wave_rms"]), 1))
        for x in range(len(rms)):
            level = min(1.0, float(rms[x]) * scale) * half
            if level < 0.5:
                continue
            painter.drawLine(int(x), int(middle - level), int(x), int(middle + level))

        self._paint_scale_badge(painter, wave)

    def _paint_scale_badge(self, painter: QPainter, wave: QRect) -> None:
        """State the display gain, so a fitted view never misleads about level."""
        if self._v_scale <= 1.001:
            return
        text = f"×{self._v_scale:.1f} view   peak {self.source_peak_db:+.1f} dBFS"
        painter.setFont(self._mono_font)
        metrics = QFontMetrics(self._mono_font)
        width = metrics.horizontalAdvance(text) + 12
        box = QRect(wave.right() - width - 8, wave.top() + 8, width, 18)
        painter.fillRect(box, QColor(COLORS["surface_2"]))
        painter.setPen(QColor(COLORS["muted"]))
        painter.drawText(box, Qt.AlignCenter, text)

    def _envelope(self, width: int):
        """Cached (min, max, rms) arrays for the current view and width."""
        key = (round(self._view_start, 6), round(self._view_end, 6), width)
        if key == self._cache_key and self._cache_env is not None:
            return self._cache_env
        if self._pyramid is None or width <= 0:
            return None
        rate = self._pyramid.sample_rate
        start_frame = int(self._view_start * rate)
        end_frame = int(self._view_end * rate)
        try:
            envelope = self._pyramid.envelope(start_frame, end_frame, width)
        except Exception as exc:  # noqa: BLE001 - drawing must never crash the app
            log.debug("Envelope computation failed: %s", exc)
            return None
        self._cache_key, self._cache_env = key, envelope
        return envelope

    def _paint_cuts(self, painter: QPainter, wave: QRect) -> None:
        """Removed spans are hatched, so a cut reads as absence, not selection."""
        if not self._cuts:
            return
        colour = QColor(COLORS["well"])
        colour.setAlpha(200)
        pen = QPen(QColor(COLORS["accent"]), 1, Qt.DashLine)
        for start, end in self._cuts:
            left = int(self.seconds_to_x(start))
            right = int(self.seconds_to_x(end))
            if right < 0 or left > self.width():
                continue
            rect = QRect(left, wave.top(), max(1, right - left), wave.height())
            painter.fillRect(rect, colour)
            painter.setPen(pen)
            painter.drawRect(rect)

    def _paint_clips(self, painter: QPainter, wave: QRect) -> None:
        """Clipping markers. Paired with a numeric readout elsewhere in the UI,
        so the information does not depend on perceiving the colour red."""
        if not self._clip_positions:
            return
        painter.setPen(QPen(QColor(COLORS["accent"]), 2))
        for position in self._clip_positions:
            x = int(self.seconds_to_x(position))
            if 0 <= x <= self.width():
                painter.drawLine(x, wave.top(), x, wave.top() + 6)

    def _paint_markers(self, painter: QPainter) -> None:
        if not self._markers:
            return
        painter.setFont(self._mono_font)
        for marker in self._markers:
            x = int(self.seconds_to_x(marker.position))
            if not (0 <= x <= self.width()):
                continue
            colour = QColor(COLORS["primary"] if marker.is_chapter else COLORS["muted"])
            painter.setPen(QPen(colour, 1, Qt.DashLine))
            painter.drawLine(x, RULER_HEIGHT, x, self.height())
            # Flag in the ruler
            painter.setPen(QPen(colour, 1))
            painter.fillRect(QRect(x, 2, 3, RULER_HEIGHT - 6), colour)
            if marker.label:
                painter.drawText(x + 6, RULER_HEIGHT - 8, marker.label[:28])

    def _paint_selection_edges(self, painter: QPainter, wave: QRect) -> None:
        if not self._selection:
            return
        painter.setPen(QPen(QColor(COLORS["primary"]), 1))
        for value in self._selection:
            x = int(self.seconds_to_x(value))
            painter.drawLine(x, wave.top(), x, wave.bottom())
            painter.fillRect(QRect(x - 2, wave.top(), 4, 10),
                             QColor(COLORS["primary"]))
            painter.fillRect(QRect(x - 2, wave.bottom() - 10, 4, 10),
                             QColor(COLORS["primary"]))

    def _paint_playhead(self, painter: QPainter) -> None:
        x = int(self.seconds_to_x(self._playhead))
        if not (-2 <= x <= self.width() + 2):
            return
        painter.setPen(QPen(QColor(COLORS["ink"]), 1))
        painter.drawLine(x, RULER_HEIGHT, x, self.height())
        # Grab handle in the ruler.
        path = QPainterPath()
        path.moveTo(x - 5, 2)
        path.lineTo(x + 5, 2)
        path.lineTo(x, 12)
        path.closeSubpath()
        painter.fillPath(path, QColor(COLORS["ink"]))

    def _paint_hover(self, painter: QPainter, wave: QRect) -> None:
        if self._hover_x is None or self._dragging:
            return
        painter.setPen(QPen(QColor(COLORS["border_hi"]), 1, Qt.DotLine))
        painter.drawLine(self._hover_x, wave.top(), self._hover_x, wave.bottom())

        seconds = self.x_to_seconds(self._hover_x)
        label = format_duration(seconds)
        painter.setFont(self._mono_font)
        metrics = QFontMetrics(self._mono_font)
        width = metrics.horizontalAdvance(label) + 10
        x = min(max(self._hover_x + 6, 0), self.width() - width)
        box = QRect(x, wave.bottom() - 20, width, 16)
        painter.fillRect(box, QColor(COLORS["surface_3"]))
        painter.setPen(QColor(COLORS["ink"]))
        painter.drawText(box, Qt.AlignCenter, label)

    def _paint_analysing(self, painter: QPainter) -> None:
        """A determinate strip, because the user must know work is bounded."""
        bar = QRect(0, self.height() - 3, self.width(), 3)
        painter.fillRect(bar, QColor(COLORS["surface_2"]))
        filled = int(self.width() * max(0.0, min(self._analysis_progress, 1.0)))
        painter.fillRect(QRect(0, self.height() - 3, filled, 3),
                         QColor(COLORS["primary"]))


def _tick_step(span_seconds: float, width_px: int) -> float:
    """Choose a ruler interval giving readable, round-numbered ticks."""
    target_ticks = max(2, width_px // 90)
    raw = span_seconds / target_ticks
    for step in (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30,
                 60, 120, 300, 600, 900, 1800, 3600):
        if raw <= step:
            return float(step)
    return 3600.0


def _tick_label(seconds: float, step: float) -> str:
    if step < 1:
        return f"{seconds:.2f}"
    return format_duration(seconds)
