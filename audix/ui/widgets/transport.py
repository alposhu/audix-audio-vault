"""Transport bar: playback controls, timecode, and level meter.

Timecodes use a tabular monospace face. This is not decoration: a proportional
digit shifts the readout horizontally on every frame during playback, which
reads as a rendering bug rather than a clock.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from audix.ui import icons
from audix.ui.theme import mono_font
from audix.ui.tokens import COLORS, TYPE
from audix.ui.widgets.meter import LevelMeter


def format_timecode(seconds: float, show_ms: bool = True) -> str:
    """``H:MM:SS.mmm`` / ``MM:SS.mmm`` - always a fixed width for its magnitude."""
    seconds = max(0.0, float(seconds))
    whole = int(seconds)
    ms = int(round((seconds - whole) * 1000))
    if ms == 1000:
        whole, ms = whole + 1, 0
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        base = f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        base = f"{minutes:02d}:{secs:02d}"
    return f"{base}.{ms:03d}" if show_ms else base


class TransportBar(QFrame):
    """Play / stop / skip, timecode readout, and output metering."""

    play_toggled = Signal()
    stop_requested = Signal()
    skip_start = Signal()
    skip_end = Signal()
    loop_toggled = Signal(bool)
    bypass_toggled = Signal(bool)

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "plateBar")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._duration = 0.0
        self._build_ui()
        self.set_enabled_state(False)

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 2)
        layout.setSpacing(14)

        # --- transport buttons ---------------------------------------------
        self.skip_start_button = self._icon_button("back", "Go to start (Home)")
        self.skip_start_button.clicked.connect(self.skip_start)
        layout.addWidget(self.skip_start_button)

        self.play_button = self._icon_button("play", "Play / pause (Space)", COLORS["well"])
        self.play_button.setProperty("variant", "primary")
        self.play_button.setFixedWidth(52)
        self.play_button.clicked.connect(self.play_toggled)
        layout.addWidget(self.play_button)

        self.stop_button = self._icon_button("stop", "Stop and return to start")
        self.stop_button.clicked.connect(self.stop_requested)
        layout.addWidget(self.stop_button)

        self.skip_end_button = self._icon_button("forward", "Go to end (End)")
        self.skip_end_button.clicked.connect(self.skip_end)
        layout.addWidget(self.skip_end_button)

        layout.addSpacing(4)
        layout.addWidget(self._separator())
        layout.addSpacing(4)

        # --- timecode -------------------------------------------------------
        clock = QVBoxLayout()
        clock.setSpacing(1)
        self.position_label = QLabel(format_timecode(0))
        self.position_label.setFont(mono_font(20, 600))
        self.position_label.setStyleSheet(f"color: {COLORS['ink']};")
        clock.addWidget(self.position_label)

        self.duration_label = QLabel("of 00:00.000")
        self.duration_label.setFont(mono_font(TYPE["small"][0]))
        self.duration_label.setStyleSheet(f"color: {COLORS['muted']};")
        clock.addWidget(self.duration_label)
        layout.addLayout(clock)

        layout.addSpacing(4)
        layout.addWidget(self._separator())
        layout.addSpacing(4)

        # --- selection readout ---------------------------------------------
        selection = QVBoxLayout()
        selection.setSpacing(1)
        caption = QLabel("Selection")
        caption.setProperty("role", "micro")
        selection.addWidget(caption)
        self.selection_label = QLabel("none")
        self.selection_label.setFont(mono_font(TYPE["small"][0]))
        self.selection_label.setStyleSheet(f"color: {COLORS['muted']};")
        selection.addWidget(self.selection_label)
        layout.addLayout(selection)

        layout.addStretch(1)

        # --- toggles --------------------------------------------------------
        self.loop_button = self._button("Loop", "Loop the selection (L)")
        self.loop_button.setCheckable(True)
        self.loop_button.setProperty("variant", "tool")
        self.loop_button.setFixedWidth(60)
        self.loop_button.toggled.connect(self.loop_toggled)
        layout.addWidget(self.loop_button)

        self.bypass_button = self._button("A / B", "Bypass effects to compare (B)")
        self.bypass_button.setCheckable(True)
        self.bypass_button.setProperty("variant", "tool")
        self.bypass_button.setFixedWidth(64)
        self.bypass_button.toggled.connect(self._on_bypass)
        layout.addWidget(self.bypass_button)

        layout.addSpacing(8)

        # --- meter ----------------------------------------------------------
        meter_box = QVBoxLayout()
        meter_box.setSpacing(2)
        self.meter = LevelMeter(2)
        self.meter.setFixedHeight(42)
        meter_box.addWidget(self.meter, 0, Qt.AlignHCenter)
        self.peak_label = QLabel("-inf dB")
        self.peak_label.setFont(mono_font(TYPE["micro"][0]))
        self.peak_label.setStyleSheet(f"color: {COLORS['muted']};")
        self.peak_label.setAlignment(Qt.AlignCenter)
        self.peak_label.setToolTip(
            "Peak output level. Shown numerically as well as on the meter, so "
            "clipping is readable without relying on colour."
        )
        meter_box.addWidget(self.peak_label)
        layout.addLayout(meter_box)

    def _button(self, text: str, tooltip: str) -> QPushButton:
        button = QPushButton(text)
        button.setToolTip(tooltip)
        button.setFixedWidth(40)
        button.setFixedHeight(32)
        return button

    def _icon_button(self, name: str, tooltip: str, color: str = None) -> QPushButton:
        button = self._button("", tooltip)
        button.setAccessibleName(tooltip)
        button.setIcon(icons.icon(name, 16, color))
        button.setIconSize(QSize(16, 16))
        return button

    def _separator(self) -> QFrame:
        line = QFrame()
        line.setProperty("role", "vdivider")
        line.setFrameShape(QFrame.VLine)
        line.setFixedWidth(1)
        line.setFixedHeight(34)
        return line

    # ------------------------------------------------------------------ state
    def set_enabled_state(self, enabled: bool, reason: str = "") -> None:
        """Enable transport, or disable it *with a stated reason*.

        A disabled control that cannot say why is the anti-pattern this product
        exists to avoid, so the reason lands in the tooltip.
        """
        for widget in (self.play_button, self.stop_button, self.skip_start_button,
                       self.skip_end_button, self.loop_button, self.bypass_button):
            widget.setEnabled(enabled)
            if not enabled and reason:
                widget.setToolTip(reason)

    def set_duration(self, seconds: float) -> None:
        self._duration = max(0.0, seconds)
        self.duration_label.setText(f"of {format_timecode(self._duration)}")

    def set_position(self, seconds: float) -> None:
        self.position_label.setText(format_timecode(seconds))

    def set_playing(self, playing: bool) -> None:
        self.play_button.setIcon(icons.icon("pause" if playing else "play", 16, COLORS["well"]))
        self.play_button.setToolTip("Pause (Space)" if playing else "Play (Space)")

    def set_selection(self, start: Optional[float], end: Optional[float]) -> None:
        if start is None or end is None or end <= start:
            self.selection_label.setText("none")
            self.selection_label.setStyleSheet(f"color: {COLORS['faint']};")
            self.loop_button.setEnabled(False)
            self.loop_button.setToolTip("Select a range first to loop it.")
        else:
            self.selection_label.setText(
                f"{format_timecode(start, False)} → {format_timecode(end, False)}"
                f"   ({end - start:.2f}s)"
            )
            self.selection_label.setStyleSheet(f"color: {COLORS['primary']};")
            self.loop_button.setEnabled(True)
            self.loop_button.setToolTip("Loop the selection (L)")

    def set_levels(self, left: float, right: float) -> None:
        self.meter.set_levels(left, right)
        from audix.core.audio.dsp import linear_to_db

        peak = max(left, right)
        if peak <= 0.0:
            self.peak_label.setText("-inf dB")
            self.peak_label.setStyleSheet(f"color: {COLORS['muted']};")
            return
        db = linear_to_db(peak)
        self.peak_label.setText(f"{db:+.1f} dB")
        colour = COLORS["accent"] if db >= -0.1 else (
            COLORS["warning"] if db >= -3 else COLORS["muted"])
        self.peak_label.setStyleSheet(f"color: {colour};")

    def reset_meters(self) -> None:
        self.meter.reset()
        self.peak_label.setText("-inf dB")
        self.peak_label.setStyleSheet(f"color: {COLORS['muted']};")

    def _on_bypass(self, checked: bool) -> None:
        self.bypass_button.setText("Original" if checked else "A / B")
        self.bypass_toggled.emit(checked)
