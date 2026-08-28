"""Format + bitrate picker, shared by Quick Convert and Settings.

Keeping this in one widget means the two tabs can never drift out of sync about
which formats exist or when a bitrate choice is meaningful (it is disabled for
lossless targets, where a bitrate would be a lie).
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QStandardItem
from PySide6.QtWidgets import QComboBox, QFormLayout, QWidget

from audix.core import formats


class FormatSelector(QWidget):
    """Two linked combo boxes: output format and bitrate."""

    changed = Signal()

    def __init__(self, parent: QWidget = None, compact: bool = False) -> None:
        super().__init__(parent)

        self.format_combo = QComboBox()
        self._populate_formats()

        self.bitrate_combo = QComboBox()
        self._populate_bitrates()

        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.setLabelAlignment(layout.labelAlignment())
        layout.addRow("Format" if compact else "Output format", self.format_combo)
        layout.addRow("Quality" if compact else "Bitrate", self.bitrate_combo)

        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        self.bitrate_combo.currentIndexChanged.connect(lambda _i: self.changed.emit())
        self._on_format_changed()

    # ----------------------------------------------------------------- content
    def _populate_formats(self) -> None:
        model = self.format_combo.model()

        def add_header(text: str) -> None:
            item = QStandardItem(text)
            item.setEnabled(False)
            model.appendRow(item)

        add_header("— Lossy —")
        for key in formats.LOSSY_KEYS:
            self.format_combo.addItem(formats.FORMATS[key].label, key)
        add_header("— Lossless —")
        for key in formats.LOSSLESS_KEYS:
            self.format_combo.addItem(formats.FORMATS[key].label, key)

    def _populate_bitrates(self) -> None:
        for preset in formats.BITRATE_PRESETS:
            if preset == formats.NATIVE_BITRATE:
                self.bitrate_combo.addItem("Native source bitrate", preset)
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

    def describe(self) -> str:
        fmt = formats.get(self.format_key())
        if fmt.lossless:
            return f"{fmt.label} · lossless"
        if self.bitrate() == formats.NATIVE_BITRATE:
            return f"{fmt.label} · native source bitrate"
        return f"{fmt.label} · {self.bitrate()} kbps"

    # --------------------------------------------------------------- internals
    def _on_format_changed(self) -> None:
        fmt = formats.FORMATS.get(self.format_key())
        if fmt is None:
            return
        lossless = fmt.lossless
        self.bitrate_combo.setEnabled(not lossless)
        self.bitrate_combo.setToolTip(
            "Lossless formats keep the full source quality; bitrate does not apply."
            if lossless else
            "Target bitrate for the encoder. 'Native' reuses the source stream's rate."
        )
        self.changed.emit()
