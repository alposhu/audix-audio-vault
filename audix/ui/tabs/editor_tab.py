"""The editor workspace.

Layout: header / waveform / transport / tool panel. The waveform gets every
pixel not claimed by a control, because it is the thing being worked on.

Two principles from PRODUCT.md are load-bearing here:

* **Never refuse silently.** Every control that is unavailable explains why in
  its tooltip and in the status line, rather than sitting greyed out.
* **Preview before commit.** Gain, EQ, and fades feed the live preview chain, so
  a change is audible during playback and A/B comparable against the original.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QEvent, QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QGroupBox,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QSlider, QVBoxLayout, QWidget,
)

from audix.core import chapters as chapters_module
from audix.core import formats
from audix.core.audio import analysis, decoder, engine as engine_module, peaks
from audix.core.edits import EditDocument, FadeCurve, NormalizeMode
from audix.core.ffmpeg_manager import FFmpegManager
from audix.ui import icons
from audix.ui.theme import mono_font
from audix.ui.tokens import COLORS, SPACE, TYPE
from audix.ui.widgets.transport import TransportBar, format_timecode
from audix.ui.widgets.waveform import Marker, WaveformView
from audix.ui.widgets.well import Well
from audix.utils import humanize

log = logging.getLogger("audix.ui.editor")

TOOL_PANEL_WIDTH = 330

#: UI refresh rate while playing. 30 Hz is smooth for a playhead without
#: spending the main thread on repaints.
POLL_INTERVAL_MS = 33


class _AnalysisWorker(QObject):
    """Decodes a file and builds its peak pyramid off the UI thread."""

    progress = Signal(float, str)          # 0..1, stage
    finished = Signal(object, object)      # AudioBuffer, PeakPyramid
    failed = Signal(str)

    def __init__(self, ffmpeg: str, ffprobe: str, path: Path) -> None:
        super().__init__()
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.path = path
        self._cancel = None

    @Slot()
    def run(self) -> None:
        import threading

        self._cancel = threading.Event()
        try:
            buffer = decoder.decode(
                self.ffmpeg, self.ffprobe, self.path,
                progress=lambda f: self.progress.emit(f * 0.6, "Decoding audio"),
                cancel_event=self._cancel,
            )
        except decoder.DecodeCancelled:
            self.failed.emit("Cancelled.")
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("Decode failed")
            self.failed.emit(str(exc))
            return

        try:
            pyramid = peaks.build(
                buffer,
                progress=lambda f: self.progress.emit(0.6 + f * 0.4,
                                                      "Analysing waveform"),
                cancel_event=self._cancel,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("Peak analysis failed")
            buffer.close()
            self.failed.emit(str(exc))
            return

        self.finished.emit(buffer, pyramid)

    def cancel(self) -> None:
        if self._cancel is not None:
            self._cancel.set()


class EditorTab(QWidget):
    """Single-track audio editor."""

    export_requested = Signal(object)      # ExportJob-shaped dict
    status_message = Signal(str)

    def __init__(self, config, ffmpeg: FFmpegManager, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.config = config
        self.ffmpeg = ffmpeg

        self.document = EditDocument()
        self.engine = engine_module.PlaybackEngine()

        self._buffer = None
        self._pyramid = None
        self._source: Optional[Path] = None
        self._info: dict = {}
        self._chapters: List[chapters_module.Chapter] = []
        self._thread: Optional[QThread] = None
        self._worker: Optional[_AnalysisWorker] = None
        self._suppress = False

        self._build_ui()
        self._install_shortcuts()

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll_engine)

        self._update_enablement()

    # ------------------------------------------------------------------ layout
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ------------------------------------------------ main column
        main = QVBoxLayout()
        main.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["base"], SPACE["base"])
        main.setSpacing(SPACE["md"])

        main.addLayout(self._build_header())

        self.waveform = WaveformView()
        self.waveform.selection_changed.connect(self._on_selection_changed)
        self.waveform.playhead_moved.connect(self._on_playhead_moved)
        self.waveform.marker_activated.connect(self._on_marker_activated)
        well = Well()
        well.body.addWidget(self.waveform)
        main.addWidget(well, 1)

        main.addLayout(self._build_zoom_bar())

        self.transport = TransportBar()
        self.transport.play_toggled.connect(self._toggle_play)
        self.transport.stop_requested.connect(self._stop)
        self.transport.skip_start.connect(lambda: self._seek(0.0))
        self.transport.skip_end.connect(lambda: self._seek(self._duration()))
        self.transport.loop_toggled.connect(self._on_loop_toggled)
        self.transport.bypass_toggled.connect(self._on_bypass_toggled)
        main.addWidget(self.transport)

        self.status_label = QLabel("")
        self.status_label.setProperty("role", "hint")
        self.status_label.setWordWrap(True)
        main.addWidget(self.status_label)

        self.export_progress = QProgressBar()
        self.export_progress.setRange(0, 1000)
        self.export_progress.setTextVisible(False)
        self.export_progress.hide()
        main.addWidget(self.export_progress)

        root.addLayout(main, 1)

        # ------------------------------------------------ tool panel
        root.addWidget(self._build_tool_panel(), 0)

        self._empty_overlay = None
        self._show_empty_state()

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(SPACE["md"])

        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title_label = QLabel("Editor")
        self.title_label.setProperty("role", "display")
        titles.addWidget(self.title_label)
        self.subtitle_label = QLabel("Nothing loaded")
        self.subtitle_label.setProperty("role", "muted")
        titles.addWidget(self.subtitle_label)
        row.addLayout(titles, 1)

        self.open_button = QPushButton("Open audio…")
        self.open_button.clicked.connect(self.choose_file)
        row.addWidget(self.open_button)

        self.close_button = QPushButton("Close")
        self.close_button.setProperty("variant", "ghost")
        self.close_button.setToolTip("Unload this file")
        self.close_button.clicked.connect(self.close_file)
        row.addWidget(self.close_button)

        self.undo_button = QPushButton("Undo")
        self.undo_button.setProperty("variant", "ghost")
        self.undo_button.clicked.connect(self.undo)
        row.addWidget(self.undo_button)

        self.redo_button = QPushButton("Redo")
        self.redo_button.setProperty("variant", "ghost")
        self.redo_button.clicked.connect(self.redo)
        row.addWidget(self.redo_button)
        return row

    def _build_zoom_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(SPACE["sm"])

        self.edit_summary_label = QLabel("No edits")
        self.edit_summary_label.setProperty("role", "hint")
        row.addWidget(self.edit_summary_label, 1)

        amp_caption = QLabel("Amplitude")
        amp_caption.setProperty("role", "micro")
        row.addWidget(amp_caption)

        for label, tooltip, handler in (
            ("chevron_down", "Show less amplitude (Shift+wheel)",
             lambda: self.waveform.scale_vertical_by(1 / 1.4)),
            ("chevron_up", "Magnify quiet audio (Shift+wheel)",
             lambda: self.waveform.scale_vertical_by(1.4)),
            ("1:1", "True scale — canvas edge is 0 dBFS",
             self.waveform.reset_vertical),
            ("Fit", "Fit the waveform to this file's loudest point",
             self.waveform.fit_vertical),
        ):
            row.addWidget(self._zoom_key(label, tooltip, handler))

        divider = QFrame()
        divider.setProperty("role", "vdivider")
        divider.setFrameShape(QFrame.VLine)
        divider.setFixedWidth(1)
        divider.setFixedHeight(18)
        row.addWidget(divider)

        time_caption = QLabel("Time")
        time_caption.setProperty("role", "micro")
        row.addWidget(time_caption)

        for label, tooltip, handler in (
            ("minus", "Zoom out (Ctrl+3)", lambda: self.waveform.zoom_by(1 / 1.6)),
            ("plus", "Zoom in (Ctrl+1)", lambda: self.waveform.zoom_by(1.6)),
            ("Fit", "Zoom to the whole file (Ctrl+2)", self.waveform.zoom_fit),
            ("Selection", "Zoom to selection (Ctrl+E)", self.waveform.zoom_selection),
        ):
            row.addWidget(self._zoom_key(label, tooltip, handler))
        return row

    def _zoom_key(self, label: str, tooltip: str, handler) -> QPushButton:
        """A quiet key showing either a word or, for a named glyph, a drawn icon."""
        is_icon = label.islower() or label.startswith("chevron")
        button = QPushButton("" if is_icon else label)
        if is_icon:
            button.setIcon(icons.icon(label, 14, COLORS["muted"]))
            button.setAccessibleName(tooltip)
        button.setProperty("variant", "ghost")
        button.setToolTip(tooltip)
        button.setFixedHeight(26)
        button.clicked.connect(handler)
        return button

    def _build_tool_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setFixedWidth(TOOL_PANEL_WIDTH)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {COLORS['surface']}; "
            f"border-left: 1px solid {COLORS['border']}; }}"
        )

        container = QWidget()
        column = QVBoxLayout(container)
        column.setContentsMargins(SPACE["base"], SPACE["lg"], SPACE["base"], SPACE["lg"])
        column.setSpacing(SPACE["md"])

        column.addWidget(self._group_selection())
        column.addWidget(self._group_levels())
        column.addWidget(self._group_eq())
        column.addWidget(self._group_time())
        column.addWidget(self._group_chapters())
        column.addWidget(self._group_export())
        column.addStretch(1)

        scroll.setWidget(container)
        return scroll

    # --- tool groups -------------------------------------------------------
    def _group_selection(self) -> QGroupBox:
        group = QGroupBox("Selection")
        layout = QVBoxLayout(group)
        layout.setSpacing(SPACE["sm"])

        grid = QHBoxLayout()
        grid.setSpacing(SPACE["sm"])
        self.trim_button = self._tool("Trim to selection",
                                      "Keep only the selected range", self.trim_to_selection)
        self.delete_button = self._tool("Delete selection",
                                        "Remove the selected range", self.delete_selection)
        grid.addWidget(self.trim_button)
        grid.addWidget(self.delete_button)
        layout.addLayout(grid)

        row2 = QHBoxLayout()
        row2.setSpacing(SPACE["sm"])
        self.fade_in_button = self._tool("Fade in", "Fade up across the selection",
                                         lambda: self.apply_fade(True))
        self.fade_out_button = self._tool("Fade out", "Fade down across the selection",
                                          lambda: self.apply_fade(False))
        row2.addWidget(self.fade_in_button)
        row2.addWidget(self.fade_out_button)
        layout.addLayout(row2)

        self.silence_button = self._tool(
            "Strip silence at ends",
            "Trim leading and trailing silence automatically",
            self.strip_silence,
        )
        layout.addWidget(self.silence_button)

        self.select_all_button = self._tool("Select all", "Select the whole file (Ctrl+A)",
                                            self.waveform.select_all)
        layout.addWidget(self.select_all_button)
        return group

    def _group_levels(self) -> QGroupBox:
        group = QGroupBox("Levels")
        layout = QVBoxLayout(group)
        layout.setSpacing(SPACE["sm"])

        self.gain_slider, self.gain_readout = self._slider_row(
            layout, "Gain", -24, 24, 0, " dB",
            "Applied live during playback so you can hear it immediately.",
        )
        self.gain_slider.valueChanged.connect(self._on_gain_changed)
        self.gain_slider.sliderPressed.connect(self.document.begin)
        self.gain_slider.sliderReleased.connect(self._commit_slider)

        layout.addSpacing(4)
        norm_label = QLabel("Normalize")
        norm_label.setProperty("role", "micro")
        layout.addWidget(norm_label)

        self.normalize_combo = QComboBox()
        self.normalize_combo.addItem("Off", NormalizeMode.NONE)
        self.normalize_combo.addItem("Loudness (EBU R128)", NormalizeMode.LOUDNESS)
        self.normalize_combo.addItem("Peak", NormalizeMode.PEAK)
        self.normalize_combo.setToolTip(
            "Loudness matches perceived volume using a two-pass measurement, the "
            "way streaming services do. Peak only scales the loudest sample."
        )
        self.normalize_combo.currentIndexChanged.connect(self._on_normalize_changed)
        layout.addWidget(self.normalize_combo)

        self.target_combo = QComboBox()
        for key, (value, label) in analysis.LOUDNESS_TARGETS.items():
            self.target_combo.addItem(label, value)
        self.target_combo.currentIndexChanged.connect(self._on_target_changed)
        layout.addWidget(self.target_combo)

        self.loudness_label = QLabel("Not measured")
        self.loudness_label.setProperty("role", "hint")
        self.loudness_label.setWordWrap(True)
        layout.addWidget(self.loudness_label)

        self.measure_button = self._tool(
            "Measure loudness", "Run an EBU R128 measurement pass", self.measure_loudness)
        layout.addWidget(self.measure_button)
        return group

    def _group_eq(self) -> QGroupBox:
        group = QGroupBox("Equalizer")
        layout = QVBoxLayout(group)
        layout.setSpacing(SPACE["sm"])

        self.eq_low, self.eq_low_readout = self._slider_row(
            layout, "Low · 100 Hz", -15, 15, 0, " dB", "Low shelf")
        self.eq_mid, self.eq_mid_readout = self._slider_row(
            layout, "Mid · 1 kHz", -15, 15, 0, " dB", "Peaking band")
        self.eq_high, self.eq_high_readout = self._slider_row(
            layout, "High · 8 kHz", -15, 15, 0, " dB", "High shelf")

        for slider in (self.eq_low, self.eq_mid, self.eq_high):
            slider.valueChanged.connect(self._on_eq_changed)
            slider.sliderPressed.connect(self.document.begin)
            slider.sliderReleased.connect(self._commit_slider)

        presets = QHBoxLayout()
        presets.setSpacing(SPACE["xs"])
        for name, values in (("Flat", (0, 0, 0)), ("Bass", (6, 0, 1)),
                             ("Voice", (-3, 4, 2)), ("Bright", (0, 1, 5))):
            button = QPushButton(name)
            button.setProperty("variant", "ghost")
            button.setFixedHeight(24)
            button.clicked.connect(lambda _c=False, v=values: self._apply_eq_preset(v))
            presets.addWidget(button)
        layout.addLayout(presets)
        return group

    def _group_time(self) -> QGroupBox:
        # "&&" escapes the mnemonic: a single "&" renders as an accelerator
        # underscore, so the title displayed as "Time _pitch".
        group = QGroupBox("Time && pitch")
        layout = QVBoxLayout(group)
        layout.setSpacing(SPACE["sm"])

        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.25, 4.0)
        self.speed_spin.setSingleStep(0.05)
        self.speed_spin.setValue(1.0)
        self.speed_spin.setSuffix("×  speed")
        self.speed_spin.valueChanged.connect(self._on_speed_changed)
        layout.addWidget(self.speed_spin)

        self.preserve_pitch_check = QCheckBox("Keep pitch when changing speed")
        self.preserve_pitch_check.setChecked(True)
        self.preserve_pitch_check.toggled.connect(self._on_speed_changed)
        layout.addWidget(self.preserve_pitch_check)

        self.pitch_spin = QDoubleSpinBox()
        self.pitch_spin.setRange(-12.0, 12.0)
        self.pitch_spin.setSingleStep(1.0)
        self.pitch_spin.setValue(0.0)
        self.pitch_spin.setSuffix("  semitones")
        self.pitch_spin.valueChanged.connect(self._on_pitch_changed)
        layout.addWidget(self.pitch_spin)

        self.reverse_check = QCheckBox("Reverse")
        self.reverse_check.toggled.connect(self._on_reverse_changed)
        layout.addWidget(self.reverse_check)

        note = QLabel(
            "Speed, pitch and reverse are applied on export. Preview plays at "
            "normal speed."
        )
        note.setProperty("role", "hint")
        note.setWordWrap(True)
        layout.addWidget(note)
        return group

    def _group_chapters(self) -> QGroupBox:
        group = QGroupBox("Chapters")
        layout = QVBoxLayout(group)
        layout.setSpacing(SPACE["sm"])

        self.chapter_status = QLabel("No chapters detected")
        self.chapter_status.setProperty("role", "hint")
        self.chapter_status.setWordWrap(True)
        layout.addWidget(self.chapter_status)

        self.chapter_list = QListWidget()
        self.chapter_list.setMaximumHeight(150)
        self.chapter_list.itemDoubleClicked.connect(self._on_chapter_activated)
        self.chapter_list.setToolTip("Double-click a chapter to jump to it.")
        layout.addWidget(self.chapter_list)

        self.split_check = QCheckBox("Split into separate tracks on export")
        self.split_check.setToolTip(
            "Writes one tagged file per chapter, numbered in order."
        )
        layout.addWidget(self.split_check)
        return group

    def _group_export(self) -> QGroupBox:
        group = QGroupBox("Export")
        layout = QVBoxLayout(group)
        layout.setSpacing(SPACE["sm"])

        self.format_combo = QComboBox()
        for key in list(formats.LOSSY_KEYS) + list(formats.LOSSLESS_KEYS):
            self.format_combo.addItem(formats.FORMATS[key].label, key)
        layout.addWidget(self.format_combo)

        self.bitrate_combo = QComboBox()
        for preset in formats.BITRATE_PRESETS:
            label = ("Native source bitrate" if preset == formats.NATIVE_BITRATE
                     else f"{preset} kbps")
            self.bitrate_combo.addItem(label, preset)
        layout.addWidget(self.bitrate_combo)
        self.format_combo.currentIndexChanged.connect(self._on_export_format_changed)

        self.output_duration_label = QLabel("")
        self.output_duration_label.setProperty("role", "hint")
        layout.addWidget(self.output_duration_label)

        self.export_button = QPushButton("Export")
        self.export_button.setProperty("variant", "primary")
        self.export_button.clicked.connect(self.export)
        layout.addWidget(self.export_button)

        self.revert_button = QPushButton("Revert all edits")
        self.revert_button.setProperty("variant", "danger")
        self.revert_button.clicked.connect(self.revert)
        layout.addWidget(self.revert_button)
        return group

    # --- small builders ----------------------------------------------------
    def _tool(self, text: str, tooltip: str, handler) -> QPushButton:
        button = QPushButton(text)
        button.setProperty("variant", "tool")
        button.setToolTip(tooltip)
        button.clicked.connect(handler)
        return button

    def _slider_row(self, parent_layout, label: str, minimum: int, maximum: int,
                    value: int, suffix: str, tooltip: str):
        header = QHBoxLayout()
        caption = QLabel(label)
        caption.setProperty("role", "micro")
        header.addWidget(caption, 1)
        readout = QLabel(f"{value}{suffix}")
        readout.setFont(mono_font(TYPE["small"][0]))
        readout.setStyleSheet(f"color: {COLORS['muted']};")
        header.addWidget(readout)
        parent_layout.addLayout(header)

        slider = QSlider(Qt.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        slider.setToolTip(tooltip)
        slider.setProperty("suffix", suffix)
        parent_layout.addWidget(slider)
        return slider, readout

    # ---------------------------------------------------------------- shortcuts
    def _install_shortcuts(self) -> None:
        bindings = (
            ("Space", self._toggle_play),
            ("Ctrl+Z", self.undo),
            ("Ctrl+Shift+Z", self.redo),
            ("Ctrl+Y", self.redo),
            ("Ctrl+A", self.waveform.select_all),
            ("Ctrl+E", self.waveform.zoom_selection),
            ("Ctrl+1", lambda: self.waveform.zoom_by(1.6)),
            ("Ctrl+2", self.waveform.zoom_fit),
            ("Ctrl+3", lambda: self.waveform.zoom_by(1 / 1.6)),
            ("Home", lambda: self._seek(0.0)),
            ("End", lambda: self._seek(self._duration())),
            ("Delete", self.delete_selection),
            ("B", lambda: self.transport.bypass_button.toggle()),
            ("L", lambda: self.transport.loop_button.toggle()),
        )
        for sequence, handler in bindings:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(handler)

    # ------------------------------------------------------------------ loading
    def choose_file(self) -> None:
        start = self.config.output_dir
        path, _ = QFileDialog.getOpenFileName(
            self, "Open audio file", start,
            "Audio (*.mp3 *.flac *.wav *.m4a *.aac *.ogg *.opus *.aiff *.wma);;All files (*)",
        )
        if path:
            self.load_file(Path(path))

    def load_file(self, path: Path, info: Optional[dict] = None) -> None:
        """Load a file for editing, decoding and analysing on a worker thread."""
        if not self.ffmpeg.ready:
            self._set_status("FFmpeg is not available, so audio cannot be decoded.",
                             error=True)
            return
        path = Path(path)
        if not path.is_file():
            self._set_status(f"File not found: {path}", error=True)
            return

        self._cancel_analysis()
        self._release_audio()

        self._source = path
        self._info = info or {}
        self.document = EditDocument()

        self.title_label.setText(humanize.elide(path.stem, 52))
        self.subtitle_label.setText("Decoding…")
        self.waveform.set_analysing(True, 0.0)
        self._hide_empty_state()
        self._set_status(f"Reading {path.name}…")

        self._thread = QThread(self)
        self._worker = _AnalysisWorker(self.ffmpeg.ffmpeg(), self.ffmpeg.ffprobe(), path)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_analysis_progress)
        self._worker.finished.connect(self._on_analysis_finished)
        self._worker.failed.connect(self._on_analysis_failed)
        self._thread.start()
        self._update_enablement()

    @Slot(float, str)
    def _on_analysis_progress(self, fraction: float, stage: str) -> None:
        self.waveform.set_analysing(True, fraction)
        self.subtitle_label.setText(f"{stage}…  {fraction * 100:.0f}%")

    @Slot(object, object)
    def _on_analysis_finished(self, buffer, pyramid) -> None:
        self._stop_thread()
        self._buffer = buffer
        self._pyramid = pyramid

        self.waveform.set_analysing(False)
        self.waveform.set_pyramid(pyramid, buffer.duration)
        self.engine.load(buffer)
        self.transport.set_duration(buffer.duration)
        self.transport.meter.set_channels(buffer.channels)

        channels = "stereo" if buffer.channels == 2 else f"{buffer.channels} ch"
        self.subtitle_label.setText(
            f"{humanize.format_duration(buffer.duration)}  ·  "
            f"{buffer.sample_rate / 1000:.1f} kHz  ·  {channels}"
        )

        clip_report = analysis.detect_clipping(pyramid)
        self.waveform.set_clip_positions(clip_report.positions)

        self._detect_chapters()
        self._sync_controls_from_state()
        self._update_enablement()

        message = f"Loaded {self._source.name}."
        if clip_report.is_clipping:
            message += (f"  {clip_report.count} clipped region"
                        f"{'s' if clip_report.count != 1 else ''} "
                        f"(peak {clip_report.peak_db:+.1f} dBFS).")
        self._set_status(message)
        self.status_message.emit(message)

    @Slot(str)
    def _on_analysis_failed(self, message: str) -> None:
        self._stop_thread()
        self.waveform.set_analysing(False)
        failed = self._source.name if self._source else "that file"
        self.close_file()
        self._set_status(f"Could not load {failed}: {message}", error=True)

    def _detect_chapters(self) -> None:
        self._chapters = []
        self.chapter_list.clear()
        if self._info:
            self._chapters = chapters_module.from_info(
                self._info, self._buffer.duration if self._buffer else None)

        if not self._chapters:
            self.chapter_status.setText(
                "No chapters detected. audix reads YouTube chapter markers and "
                "timestamps in the description."
            )
            self.split_check.setEnabled(False)
            self.split_check.setToolTip(
                "Enabled when the source has chapters or description timestamps."
            )
            self.waveform.set_markers([])
            return

        self.chapter_status.setText(chapters_module.describe(self._chapters))
        markers = []
        for chapter in self._chapters:
            item = QListWidgetItem(
                f"{chapter.index:02d}.  {humanize.elide(chapter.title, 30)}"
                f"   {humanize.format_duration(chapter.duration)}"
            )
            item.setData(Qt.UserRole, chapter.start)
            self.chapter_list.addItem(item)
            markers.append(Marker(chapter.start, f"{chapter.index:02d}", True))
        self.waveform.set_markers(markers)
        self.split_check.setEnabled(True)
        self.split_check.setToolTip("Writes one tagged file per chapter.")
        self.split_check.setChecked(self.config.chapter_split_by_default)

    # ------------------------------------------------------------------ edits
    def _selection(self):
        return self.waveform.selection

    def trim_to_selection(self) -> None:
        selection = self._selection()
        if not selection:
            self._set_status("Select a range first, then trim to keep only that part.",
                             error=True)
            return
        start, end = selection
        self.document.mutate(trim_start=start, trim_end=end)
        self._after_edit(f"Trimmed to {format_timecode(start, False)}–"
                         f"{format_timecode(end, False)}.")

    def delete_selection(self) -> None:
        selection = self._selection()
        if not selection:
            self._set_status("Select a range first, then delete it.", error=True)
            return
        start, end = selection
        self.document.snapshot()
        self.document.state.add_cut(start, end)
        self.waveform.set_selection(None, None)
        self._after_edit(f"Removed {end - start:.2f}s.")

    def apply_fade(self, fade_in: bool) -> None:
        selection = self._selection()
        if selection:
            start, end = selection
            duration = end - start
        else:
            duration = float(self.config.default_fade_seconds)
            total = self._duration()
            start = 0.0 if fade_in else max(0.0, total - duration)
        self.document.snapshot()
        self.document.state.add_fade(start, duration, fade_in, FadeCurve.EQUAL_POWER)
        self._after_edit(f"Fade {'in' if fade_in else 'out'} over {duration:.2f}s.")

    def strip_silence(self) -> None:
        if self._pyramid is None:
            return
        start, end = analysis.trim_bounds(
            self._pyramid, float(self.config.silence_threshold_db))
        if end <= start:
            self._set_status("This file appears to be silent throughout.", error=True)
            return
        total = self._duration()
        if start < 0.01 and end > total - 0.01:
            self._set_status("No leading or trailing silence to remove.")
            return
        self.document.mutate(trim_start=start, trim_end=end)
        self.waveform.set_selection(None, None)
        self._after_edit(
            f"Stripped silence: kept {format_timecode(start, False)}–"
            f"{format_timecode(end, False)} ({total - (end - start):.2f}s removed)."
        )

    def measure_loudness(self) -> None:
        if self._source is None:
            return
        self.loudness_label.setText("Measuring…")
        self.measure_button.setEnabled(False)
        # Measurement is a full decode pass; keep the UI responsive.
        QTimer.singleShot(10, self._run_measurement)

    def _run_measurement(self) -> None:
        try:
            result = analysis.measure_loudness(self.ffmpeg.ffmpeg(), self._source)
        finally:
            self.measure_button.setEnabled(True)
        if result is None:
            self.loudness_label.setText("Measurement failed.")
            return
        self._measurement = result
        target = self.target_combo.currentData() or -14.0
        self.loudness_label.setText(
            f"{result.describe()}\nNeeds {result.gain_to(target):+.1f} dB "
            f"to reach {target:.0f} LUFS."
        )

    def revert(self) -> None:
        if self.document.state.is_pristine:
            self._set_status("There are no edits to revert.")
            return
        answer = QMessageBox.question(
            self, "Revert all edits?",
            "This returns the file to how it was loaded.\n\n"
            "Your original download is untouched either way — audix never "
            "overwrites the source.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.document.reset()
            self._sync_controls_from_state()
            self._after_edit("Reverted all edits.")

    def undo(self) -> None:
        if not self.document.undo():
            self._set_status("Nothing to undo.")
            return
        self._sync_controls_from_state()
        self._after_edit("Undone.")

    def redo(self) -> None:
        if not self.document.redo():
            self._set_status("Nothing to redo.")
            return
        self._sync_controls_from_state()
        self._after_edit("Redone.")

    # ------------------------------------------------------------- control sync
    def _on_gain_changed(self, value: int) -> None:
        self.gain_readout.setText(f"{value:+d} dB")
        if self._suppress:
            return
        self.document.state.gain_db = float(value)
        self.engine.chain.gain_db = float(value)
        self._refresh_summary()

    def _on_eq_changed(self) -> None:
        low, mid, high = (self.eq_low.value(), self.eq_mid.value(), self.eq_high.value())
        self.eq_low_readout.setText(f"{low:+d} dB")
        self.eq_mid_readout.setText(f"{mid:+d} dB")
        self.eq_high_readout.setText(f"{high:+d} dB")
        if self._suppress:
            return
        state = self.document.state
        state.eq_low_db, state.eq_mid_db, state.eq_high_db = float(low), float(mid), float(high)
        self.engine.chain.eq_low_db = float(low)
        self.engine.chain.eq_mid_db = float(mid)
        self.engine.chain.eq_high_db = float(high)
        self._refresh_summary()

    def _apply_eq_preset(self, values) -> None:
        self.document.begin()
        self._suppress = True
        self.eq_low.setValue(values[0])
        self.eq_mid.setValue(values[1])
        self.eq_high.setValue(values[2])
        self._suppress = False
        self._on_eq_changed()
        self.document.checkpoint()

    def _commit_slider(self) -> None:
        if self.document.checkpoint():
            self._refresh_summary()

    def _on_normalize_changed(self, _index: int) -> None:
        if self._suppress:
            return
        mode = self.normalize_combo.currentData()
        self.document.mutate(normalize=mode)
        self.target_combo.setEnabled(mode is NormalizeMode.LOUDNESS)
        self.measure_button.setEnabled(mode is not NormalizeMode.NONE)
        self._refresh_summary()

    def _on_target_changed(self, _index: int) -> None:
        if self._suppress:
            return
        self.document.state.normalize_target = float(self.target_combo.currentData())
        self._refresh_summary()

    def _on_speed_changed(self) -> None:
        if self._suppress:
            return
        self.document.state.speed = float(self.speed_spin.value())
        self.document.state.preserve_pitch = self.preserve_pitch_check.isChecked()
        self._refresh_summary()

    def _on_pitch_changed(self) -> None:
        if self._suppress:
            return
        self.document.state.pitch_semitones = float(self.pitch_spin.value())
        self._refresh_summary()

    def _on_reverse_changed(self) -> None:
        if self._suppress:
            return
        self.document.state.reverse = self.reverse_check.isChecked()
        self._refresh_summary()

    def _on_export_format_changed(self) -> None:
        key = self.format_combo.currentData()
        if key:
            self.bitrate_combo.setEnabled(not formats.get(key).lossless)
            self.bitrate_combo.setToolTip(
                "Lossless formats keep full quality; bitrate does not apply."
                if formats.get(key).lossless else "Target encoder bitrate."
            )

    def _sync_controls_from_state(self) -> None:
        """Push document state into the widgets without re-triggering edits."""
        state = self.document.state
        self._suppress = True
        self.gain_slider.setValue(int(state.gain_db))
        self.eq_low.setValue(int(state.eq_low_db))
        self.eq_mid.setValue(int(state.eq_mid_db))
        self.eq_high.setValue(int(state.eq_high_db))
        self.speed_spin.setValue(state.speed)
        self.preserve_pitch_check.setChecked(state.preserve_pitch)
        self.pitch_spin.setValue(state.pitch_semitones)
        self.reverse_check.setChecked(state.reverse)
        index = self.normalize_combo.findData(state.normalize)
        if index >= 0:
            self.normalize_combo.setCurrentIndex(index)
        self._suppress = False

        self.engine.chain.gain_db = state.gain_db
        self.engine.chain.eq_low_db = state.eq_low_db
        self.engine.chain.eq_mid_db = state.eq_mid_db
        self.engine.chain.eq_high_db = state.eq_high_db
        self._sync_preview_fades()
        self._refresh_summary()

    def _sync_preview_fades(self) -> None:
        from audix.core.audio.engine import FadeSpec

        self.engine.chain.fades = [
            FadeSpec(f.start, f.duration, f.fade_in, f.curve.value)
            for f in self.document.state.fades
        ]

    def _after_edit(self, message: str) -> None:
        self._sync_preview_fades()
        self.waveform.set_cuts([(c.start, c.end) for c in self.document.state.cuts])
        self._refresh_summary()
        self._update_enablement()
        self._set_status(message)

    def _refresh_summary(self) -> None:
        items = self.document.state.summary()
        self.edit_summary_label.setText(" · ".join(items) if items else "No edits")
        if self._buffer is not None:
            predicted = self.document.state.output_duration(self._buffer.duration)
            self.output_duration_label.setText(
                f"Output length: {humanize.format_duration(predicted)}"
            )

    # -------------------------------------------------------------- transport
    def _duration(self) -> float:
        return self._buffer.duration if self._buffer is not None else 0.0

    def _toggle_play(self) -> None:
        if self._buffer is None:
            return
        if not self.engine.available:
            self._set_status(engine_module.backend_error(), error=True)
            return
        if self.engine.is_playing:
            self.engine.pause()
            self._timer.stop()
            self.transport.set_playing(False)
            self.transport.reset_meters()
        else:
            if self.engine.play():
                self._timer.start()
                self.transport.set_playing(True)
            else:
                self._set_status("Could not open an audio output device.", error=True)

    def _stop(self) -> None:
        self.engine.stop()
        self._timer.stop()
        self.transport.set_playing(False)
        self.transport.reset_meters()
        self._seek(0.0)

    def _seek(self, seconds: float) -> None:
        self.engine.seek_seconds(seconds)
        self.waveform.set_playhead(seconds)
        self.transport.set_position(seconds)

    def _on_playhead_moved(self, seconds: float) -> None:
        self.engine.seek_seconds(seconds)
        self.transport.set_position(seconds)

    def _on_selection_changed(self, start: float, end: float) -> None:
        has_selection = end > start
        self.transport.set_selection(start if has_selection else None,
                                     end if has_selection else None)
        if has_selection and self.transport.loop_button.isChecked():
            self._apply_loop(True)
        self._update_enablement()

    def _on_loop_toggled(self, checked: bool) -> None:
        self._apply_loop(checked)

    def _apply_loop(self, enabled: bool) -> None:
        selection = self._selection()
        if enabled and selection and self._buffer is not None:
            self.engine.set_loop(self._buffer.seconds_to_frame(selection[0]),
                                 self._buffer.seconds_to_frame(selection[1]))
        else:
            self.engine.set_loop(None, None)

    def _on_bypass_toggled(self, checked: bool) -> None:
        self.engine.chain.bypass = checked
        self._set_status("Hearing the original file." if checked
                         else f"Hearing your edits: {self.engine.chain.describe()}")

    def _on_marker_activated(self, position: float) -> None:
        self._seek(position)

    def _on_chapter_activated(self, item: QListWidgetItem) -> None:
        position = item.data(Qt.UserRole)
        if position is not None:
            self._seek(float(position))
            self.waveform.set_playhead(float(position), follow=True)

    def _poll_engine(self) -> None:
        """Pull state from the audio thread rather than being pushed to."""
        snapshot = self.engine.snapshot()
        self.waveform.set_playhead(snapshot.seconds, follow=True)
        self.transport.set_position(snapshot.seconds)
        self.transport.set_levels(snapshot.peak_left, snapshot.peak_right)
        if not snapshot.playing:
            self._timer.stop()
            self.transport.set_playing(False)
            self.transport.reset_meters()

    # ------------------------------------------------------------------ export
    def export(self) -> None:
        if self._buffer is None or self._source is None:
            return
        fmt = formats.get(self.format_combo.currentData() or "mp3")
        split = self.split_check.isChecked() and bool(self._chapters)

        if split:
            directory = QFileDialog.getExistingDirectory(
                self, "Choose a folder for the split tracks", self.config.output_dir)
            if not directory:
                return
            destination = Path(directory)
        else:
            suggested = str(Path(self.config.output_dir) /
                            f"{self._source.stem} (edited).{fmt.ext}")
            path, _ = QFileDialog.getSaveFileName(
                self, "Export audio", suggested,
                f"{fmt.label} (*.{fmt.ext});;All files (*)")
            if not path:
                return
            destination = Path(path)

        self.export_requested.emit({
            "source": self._source,
            "destination": destination,
            "state": self.document.state.copy(),
            "audio_format": fmt.key,
            "bitrate": self.bitrate_combo.currentData() or "320",
            "source_duration": self._buffer.duration,
            "chapters": self._chapters if split else [],
            "info": self._info,
            "split": split,
        })

    # ------------------------------------------------------------ enablement
    def _update_enablement(self) -> None:
        """Enable or disable controls, always with a reason attached.

        A disabled control that cannot explain itself is the exact failure this
        product is defined against, so every branch here sets a tooltip.
        """
        loaded = self._buffer is not None
        selection = self._selection() is not None

        no_file = "Load an audio file first."
        no_selection = "Select a range on the waveform first."

        for widget in (self.trim_button, self.delete_button,
                       self.fade_in_button, self.fade_out_button):
            enabled = loaded and selection
            widget.setEnabled(enabled)
            if not loaded:
                widget.setToolTip(no_file)
            elif not selection:
                widget.setToolTip(no_selection)

        for widget in (self.silence_button, self.select_all_button,
                       self.export_button, self.revert_button,
                       self.close_button, self.measure_button, self.gain_slider,
                       self.eq_low, self.eq_mid, self.eq_high,
                       self.speed_spin, self.pitch_spin, self.reverse_check,
                       self.normalize_combo, self.format_combo):
            widget.setEnabled(loaded)
            if not loaded:
                widget.setToolTip(no_file)

        self.undo_button.setEnabled(self.document.can_undo)
        self.undo_button.setToolTip(
            f"Undo ({self.document.undo_depth} step"
            f"{'s' if self.document.undo_depth != 1 else ''})"
            if self.document.can_undo else "Nothing to undo yet."
        )
        self.redo_button.setEnabled(self.document.can_redo)
        self.redo_button.setToolTip(
            "Redo" if self.document.can_redo else "Nothing to redo."
        )

        if not self.engine.available:
            self.transport.set_enabled_state(False, engine_module.backend_error())
        else:
            self.transport.set_enabled_state(loaded, no_file)

    # -------------------------------------------------------------- empty state
    def _show_empty_state(self) -> None:
        self.waveform.set_show_placeholder(False)
        if self._empty_overlay is not None:
            self._empty_overlay.setVisible(True)
            return
        overlay = QFrame(self.waveform)
        overlay.setObjectName("emptyOverlay")
        # Scoped to the frame itself. An unscoped `background: transparent`
        # cascades into every child, which silently erased the primary button's
        # fill and left its dark label invisible on the dark canvas.
        overlay.setStyleSheet("QFrame#emptyOverlay { background: transparent; }")
        layout = QVBoxLayout(overlay)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(SPACE["sm"])

        heading = QLabel("Nothing loaded yet")
        heading.setProperty("role", "h1")
        heading.setAlignment(Qt.AlignCenter)
        layout.addWidget(heading)

        body = QLabel(
            "Open an audio file, or finish a download and choose Edit on it.\n\n"
            "Trim, fade, level, EQ — and if the video had chapters, split the\n"
            "whole thing into separately tagged tracks in one action.\n\n"
            "Your original file is never modified."
        )
        body.setProperty("role", "muted")
        body.setAlignment(Qt.AlignCenter)
        layout.addWidget(body)

        button = QPushButton("Open audio…")
        button.setProperty("variant", "primary")
        button.clicked.connect(self.choose_file)
        layout.addWidget(button, 0, Qt.AlignCenter)

        self._empty_overlay = overlay
        overlay.setGeometry(self.waveform.rect())
        overlay.show()
        self.waveform.installEventFilter(self)

    def _hide_empty_state(self) -> None:
        self.waveform.set_show_placeholder(True)
        if self._empty_overlay is not None:
            self._empty_overlay.setVisible(False)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt override
        # Follows the waveform itself, which settles its size after this page does.
        if watched is self.waveform and event.type() == QEvent.Resize:
            self._empty_overlay.setGeometry(self.waveform.rect())
        return super().eventFilter(watched, event)

    # ------------------------------------------------------------------ status
    def set_export_progress(self, fraction: Optional[float], stage: str) -> None:
        """Show how a running export is going. ``None`` means it has ended."""
        self.export_progress.setVisible(fraction is not None)
        if fraction is None:
            self._set_status("")
        else:
            self.export_progress.setValue(int(fraction * 1000))
            self._set_status(f"{stage}…  {fraction * 100:.0f}%")

    def _set_status(self, message: str, error: bool = False) -> None:
        self.status_label.setProperty("role", "error" if error else "hint")
        self.status_label.setText(message)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    # ---------------------------------------------------------------- teardown
    def _cancel_analysis(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
        self._stop_thread()

    def _stop_thread(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(4000)
            self._thread = None
        self._worker = None

    def _release_audio(self) -> None:
        self._timer.stop()
        self.engine.unload()
        if self._buffer is not None:
            self._buffer.close()
        self._buffer = None
        self._pyramid = None
        self.waveform.clear()

    def close_file(self) -> None:
        """Unload the current file and return every control to its empty state.

        Without this, closing or failing to load a file left the previous
        file's title, duration, timecode, selection and edit summary on screen,
        describing audio that was no longer loaded.
        """
        self._cancel_analysis()
        self._release_audio()
        self._source = None
        self._info = {}
        self._chapters = []
        self.document = EditDocument()

        self.title_label.setText("Editor")
        self.subtitle_label.setText("Nothing loaded")
        self.edit_summary_label.setText("No edits")
        self.output_duration_label.setText("")
        self.loudness_label.setText("Not measured")

        self.chapter_list.clear()
        self.chapter_status.setText("No chapters detected")
        self.split_check.setChecked(False)
        self.split_check.setEnabled(False)
        self.split_check.setToolTip(
            "Enabled when the source has chapters or description timestamps.")

        self.transport.set_duration(0.0)
        self.transport.set_position(0.0)
        self.transport.set_selection(None, None)
        self.transport.set_playing(False)
        self.transport.reset_meters()

        self._sync_controls_from_state()
        self._show_empty_state()
        self._update_enablement()
        self._set_status("")

    def shutdown(self) -> None:
        self._cancel_analysis()
        self._release_audio()
