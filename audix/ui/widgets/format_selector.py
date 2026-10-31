"""Format + bitrate picker, shared by the Queue and Settings.

Keeping this in one widget means the two pages can never drift out of sync about
which formats exist or when a bitrate choice is meaningful (it is disabled for
lossless targets, where a bitrate would be a lie).
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QStandardItem
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from audix.core import formats


class FormatSelector(QWidget):
    """Two linked combo boxes: output format and bitrate."""

    changed = Signal()

    def __init__(self, parent: QWidget = None, inline: bool = False,
                 label_width: int = 56) -> None:
        super().__init__(parent)
        self.setProperty("role", "clear")

        self.format_combo = QComboBox()
        self._populate_formats()

        self.bitrate_combo = QComboBox()
        self._populate_bitrates()

        if inline:
            self._lay_out_inline()
        else:
            self._lay_out_stacked(label_width)

        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        self.bitrate_combo.currentIndexChanged.connect(lambda _i: self.changed.emit())
        self._on_format_changed()

    def _lay_out_stacked(self, label_width: int) -> None:
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)
        for text, combo in (("Format", self.format_combo), ("Quality", self.bitrate_combo)):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(0)
            label = QLabel(text)
            label.setFixedWidth(label_width)
            row.addWidget(label)
            row.addWidget(combo, 1)
            column.addLayout(row)

    def _lay_out_inline(self) -> None:
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        for text, combo in (("Format", self.format_combo), ("Quality", self.bitrate_combo)):
            label = QLabel(text)
            label.setProperty("role", "muted")
            row.addWidget(label)
            row.addWidget(combo)
            row.addSpacing(6)

    # ----------------------------------------------------------------- content
    def _populate_formats(self) -> None:
        model = self.format_combo.model()

        def add_header(text: str) -> None:
            item = QStandardItem(text)
            item.setEnabled(False)
            model.appendRow(item)

        add_header("Lossy")
        for key in formats.LOSSY_KEYS:
            self.format_combo.addItem(formats.FORMATS[key].label, key)
        add_header("Lossless")
        for key in formats.LOSSLESS_KEYS:
            self.format_combo.addItem(formats.FORMATS[key].label, key)

    def _populate_bitrates(self) -> None:
        for preset in formats.BITRATE_PRESETS:
            if preset == formats.NATIVE_BITRATE:
                self.bitrate_combo.addItem("Source bitrate", preset)
            else:
                self.bitrate_combo.addItem(f"{preset} kbps", preset)

    # ------------------------------------------------------------------ public
    def format_key(self) -> str:
        data = self.format_combo.currentData()
        return data if data else "mp3"

    def bitrate(self) -> str:
        data = self.bitrate_combo.currentData()
        return data if data else "320"

    def set_values(self, format_key: str, bitrate: str) -> None:
        """Select ``format_key`` / ``bitrate``, falling back to defaults if unknown."""
        index = self.format_combo.findData(format_key)
        if index < 0:
            index = self.format_combo.findData("mp3")
        if index >= 0:
            self.format_combo.setCurrentIndex(index)

        index = self.bitrate_combo.findData(bitrate)
        if index < 0:
            index = self.bitrate_combo.findData("320")
        if index >= 0:
            self.bitrate_combo.setCurrentIndex(index)
        self._on_format_changed()

    # --------------------------------------------------------------- internals
    def _on_format_changed(self) -> None:
        fmt = formats.FORMATS.get(self.format_key())
        if fmt is None:
            return
        lossless = fmt.lossless
        self.bitrate_combo.setEnabled(not lossless)
        self.bitrate_combo.setToolTip(
            "Lossless formats keep the full source quality, so a bitrate does not apply."
            if lossless else
            "Target bitrate for the encoder. Source bitrate reuses the stream's own rate."
        )
        self.changed.emit()
