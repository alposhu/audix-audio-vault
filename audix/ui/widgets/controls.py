"""Small controls bound to the shared output settings."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QAction, QPainter
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QLineEdit, QPushButton, QSizePolicy, QToolButton, QWidget,
)

from audix.ui import icons, paint
from audix.ui.output_prefs import PARALLEL_CHOICES, PARALLEL_TOOLTIP, OutputPrefs
from audix.ui.tokens import COLORS


class Lamp(QWidget):
    """A status lamp for places outside painted rows."""

    def __init__(self, color: str = COLORS["primary"], lit: bool = True,
                 parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self.setProperty("role", "clear")
        self._color = color
        self._lit = lit

    def set_state(self, color: str, lit: bool = True) -> None:
        self._color = color
        self._lit = lit
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        paint.draw_lamp(painter, QPointF(6, 6), self._color, self._lit)
        painter.end()


def add_clear_key(field: QLineEdit) -> None:
    """Give a field its clear key, drawn from the app's icon set, not the platform's."""
    field.setClearButtonEnabled(True)
    action = field.findChild(QAction, "_q_qlineeditclearaction")
    if action is not None:
        action.setIcon(icons.icon("close", 14, COLORS["muted"]))


class ParallelCombo(QComboBox):
    """How many tracks run together. Every instance shows the same value."""

    def __init__(self, prefs: OutputPrefs, parent=None) -> None:
        super().__init__(parent)
        self.prefs = prefs
        self.setToolTip(PARALLEL_TOOLTIP)
        for value, label in PARALLEL_CHOICES:
            self.addItem(label, value)
        self._sync()
        self.activated.connect(self._on_chosen)
        prefs.changed.connect(self._sync)

    def _sync(self) -> None:
        index = self.findData(self.prefs.parallel)
        if index < 0:
            # A value from older Settings that is not on the list: show the nearest.
            nearest = min(PARALLEL_CHOICES, key=lambda c: abs(c[0] - self.prefs.parallel))
            index = self.findData(nearest[0])
        self.setCurrentIndex(index)

    def _on_chosen(self, _index: int) -> None:
        self.prefs.set_parallel(self.currentData())


class FolderButton(QToolButton):
    """Shows where audio will land; clicking chooses somewhere else."""

    def __init__(self, prefs: OutputPrefs, parent=None) -> None:
        super().__init__(parent)
        self.prefs = prefs
        self.setProperty("role", "key")
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setIcon(icons.icon("folder", 16, COLORS["muted"]))
        self.setIconSize(QSize(16, 16))
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setMinimumWidth(116)
        self.setMaximumWidth(230)
        self.clicked.connect(self._choose)
        self._sync()
        prefs.changed.connect(self._sync)

    def _sync(self) -> None:
        folder = Path(self.prefs.output_dir)
        self.setText(self.fontMetrics().elidedText(
            folder.name or str(folder), Qt.ElideMiddle, self.maximumWidth() - 50))
        self.setToolTip(f"Saving to {folder}. Click to choose another folder.")

    def _choose(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose where audio is saved", self.prefs.output_dir)
        if chosen:
            self.prefs.set_output_dir(chosen)


class IconKey(QToolButton):
    """A plain toolbar key showing an icon, with a tooltip for its name."""

    def __init__(self, icon_name: str, tooltip: str, slot=None, parent=None,
                 size: int = 18) -> None:
        super().__init__(parent)
        self.setProperty("role", "nav")
        self.setIcon(icons.icon(icon_name, size, COLORS["muted"]))
        self.setIconSize(QSize(size, size))
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setFixedSize(34, 34)
        self.setCursor(Qt.PointingHandCursor)
        if slot is not None:
            self.clicked.connect(slot)


class TextKey(QPushButton):
    """A key with an optional leading icon and one of the theme's variants."""

    def __init__(self, text: str, slot=None, variant: str = "", icon_name: str = "",
                 tooltip: str = "", parent=None) -> None:
        super().__init__(text, parent)
        if variant:
            self.setProperty("variant", variant)
        if icon_name:
            ink = COLORS["well"] if variant == "primary" else COLORS["ink"]
            self.setIcon(icons.icon(icon_name, 16, ink))
            self.setIconSize(QSize(16, 16))
        if tooltip:
            self.setToolTip(tooltip)
        if slot is not None:
            self.clicked.connect(slot)
