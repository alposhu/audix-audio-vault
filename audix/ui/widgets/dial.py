"""The tuning dial: audix's navigation and its one lit object.

A wide strip of backlit glass with a printed scale runs across the top of the
window. Each destination is a station on that scale, and a red needle glides to
whichever one is tuned in. The numerals printed at each station are real: they are
the Alt+number shortcut for it.

Stations are real buttons laid over the painted glass, so focus, tooltips, and
screen readers all work without any special handling.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import log
from typing import List, Optional

from PySide6.QtCore import (
    Property, QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, Signal,
)
from PySide6.QtGui import (
    QColor, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractButton, QButtonGroup, QHBoxLayout, QLabel, QSizePolicy, QStyle, QStyleOption,
    QWidget,
)

from audix import __app_name__
from audix.ui import motion, paint
from audix.ui.branding import draw_mark
from audix.ui.theme import dial_font, mono_font, ui_font
from audix.ui.tokens import COLORS, DURATION, EASE_OUT_QUART, SPACE, TYPE
from audix.utils import humanize

DIAL_HEIGHT = 76
GLASS_HEIGHT = 58

#: A combined rate at this level or above fills the signal ladder. The scale is
#: logarithmic, so a trickle still registers and a fast line does not peg it.
_SIGNAL_FLOOR = 32 * 1024
_SIGNAL_CEILING = 24 * 1024 * 1024


@dataclass
class Station:
    key: str
    label: str
    tooltip: str


class _StationButton(QAbstractButton):
    """A transparent hit area with the station's legend and count."""

    def __init__(self, station: Station, number: int, parent: QWidget) -> None:
        super().__init__(parent)
        self.station = station
        self.number = number
        self.badge = ""
        self.lamp = ""
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setToolTip(f"{station.tooltip}   (Alt+{number})")
        self.setAccessibleName(station.label)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_badge(self, text: str, lamp: str = "") -> None:
        """Show a count, with a lamp when something here is waiting to be seen."""
        if (text, lamp) != (self.badge, self.lamp):
            self.badge = text
            self.lamp = lamp
            self.setAccessibleDescription(text)
            self.update()

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        current = self.isChecked()
        if self.underMouse() and not current:
            painter.fillRect(self.rect().adjusted(2, 2, -2, -2), _hover_wash())

        # Every legend is printed alike, as on a real scale: the needle says which one.
        painter.setFont(dial_font(11))
        painter.setPen(QColor(COLORS["glass_ink"]))
        label_rect = QRectF(0, self.height() - 26, self.width(), 18)
        painter.drawText(label_rect, Qt.AlignHCenter | Qt.AlignVCenter, self.station.label)

        if self.badge:
            self._paint_badge(painter, label_rect)

        if self.hasFocus():
            painter.setPen(QPen(QColor(COLORS["glass_ink"]), 1.5, Qt.DotLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(self.rect()).adjusted(3, 3, -3, -3))
        painter.end()

    def _paint_badge(self, painter: QPainter, label_rect: QRectF) -> None:
        metrics = painter.fontMetrics()
        label_width = metrics.horizontalAdvance(self.station.label)
        font = mono_font(11, 600)
        painter.setFont(font)
        text_width = painter.fontMetrics().horizontalAdvance(self.badge)
        lamp_room = 12 if self.lamp else 0
        pill = QRectF(label_rect.center().x() + label_width / 2 + 7,
                      label_rect.center().y() - 8, text_width + 10 + lamp_room, 16)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(COLORS["glass_ink"]))
        painter.drawRoundedRect(pill, 2, 2)
        if self.lamp:
            paint.draw_lamp(painter, QPointF(pill.left() + 9, pill.center().y()), self.lamp,
                            radius=3.5)
        painter.setPen(QColor(COLORS["glass"]))
        painter.drawText(pill.adjusted(lamp_room, 0, 0, 0), Qt.AlignCenter, self.badge)


def _hover_wash() -> QColor:
    wash = QColor(COLORS["glass_ink"])
    wash.setAlpha(26)
    return wash


class _Glass(QWidget):
    """The lit field. Paints the scale behind the stations and the needle above them."""

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(GLASS_HEIGHT)
        self.setProperty("role", "clear")
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self._centres: List[float] = []
        self._needle_x: Optional[float] = None

    def set_stations(self, centres: List[float]) -> None:
        self._centres = centres
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, 3, 3)

        # Backlight falls away toward the ends of the glass, as a lamp behind it would.
        light = QLinearGradient(rect.topLeft(), rect.topRight())
        edge, centre = QColor(COLORS["glass_edge"]), QColor(COLORS["glass"])
        light.setColorAt(0.0, edge)
        light.setColorAt(0.14, centre)
        light.setColorAt(0.86, centre)
        light.setColorAt(1.0, edge)
        painter.fillPath(path, light)

        self._paint_scale(painter, rect)
        painter.setPen(QPen(QColor(COLORS["well"]), 1))
        painter.drawPath(path)
        painter.end()

    def _paint_scale(self, painter: QPainter, rect: QRectF) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)
        ink = QColor(COLORS["glass_soft"])
        painter.setPen(QPen(ink, 1))
        top = rect.top() + 7
        x = rect.left() + 12
        step = 8
        index = 0
        while x < rect.right() - 12:
            height = 7 if index % 5 == 0 else 4
            painter.drawLine(QPointF(x, top), QPointF(x, top + height))
            x += step
            index += 1

        painter.setPen(QPen(QColor(COLORS["glass_ink"]), 1))
        painter.setFont(mono_font(10, 500))
        for number, centre in enumerate(self._centres, start=1):
            painter.drawLine(QPointF(centre, top), QPointF(centre, top + 10))
            # Beside the mark, not on it: the needle parks on that mark.
            painter.drawText(QRectF(centre + 6, top + 9, 16, 12),
                             Qt.AlignLeft | Qt.AlignVCenter, str(number))
        painter.restore()


class _Needle(QWidget):
    """The pointer. A separate layer, so it can pass over the station legends."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setProperty("role", "clear")
        self._x = -10.0

    def get_x(self) -> float:
        return self._x

    def set_x(self, value: float) -> None:
        self._x = value
        self.update()

    needle_x = Property(float, get_x, set_x)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        x = self._x
        # Stops above the legend: the station you are on is the one you must be able
        # to read, so the pointer points at its name instead of striking through it.
        tip = self.height() - 25
        painter.fillRect(QRectF(x - 0.25, 1, 3.0, tip - 4), QColor(0, 0, 0, 46))
        painter.fillRect(QRectF(x - 1.0, 1, 2.0, tip - 4), QColor(COLORS["needle"]))
        head = QPainterPath(QPointF(x - 4, tip - 5))
        head.lineTo(x + 4, tip - 5)
        head.lineTo(x, tip)
        head.closeSubpath()
        painter.fillPath(head, QColor(COLORS["needle"]))
        painter.end()


class SignalMeter(QAbstractButton):
    """Live throughput, shown as a receiver shows signal strength.

    Clicking it tunes to Downloads, so progress is one click away from any page.
    """

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setFixedSize(150, GLASS_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setToolTip("Combined download speed. Click to open Downloads.")
        self._speed = 0.0
        self._running = 0
        self._waiting = 0

    def set_activity(self, speed: float, running: int, waiting: int) -> None:
        self._speed = speed
        self._running = running
        self._waiting = waiting
        self.setAccessibleDescription(self._caption())
        self.update()

    def _level(self) -> float:
        if self._speed <= 0:
            return 0.0
        span = log(_SIGNAL_CEILING / _SIGNAL_FLOOR)
        return max(0.08, min(log(max(self._speed, _SIGNAL_FLOOR) / _SIGNAL_FLOOR) / span, 1.0))

    def _caption(self) -> str:
        if self._running:
            line = f"{self._running} running"
            return f"{line}, {self._waiting} waiting" if self._waiting else line
        if self._waiting:
            return f"{self._waiting} waiting"
        return "Nothing running"

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        width = self.width()

        ladder = QRectF(0, 7, width, 12)
        paint.draw_ladder(painter, ladder, self._level(), COLORS["primary"])

        painter.setFont(mono_font(TYPE["body"][0], 600))
        painter.setPen(QColor(COLORS["ink"] if self._running else COLORS["faint"]))
        speed = humanize.format_speed(self._speed) if self._speed else "—"
        painter.drawText(QRectF(0, 21, width, 18), Qt.AlignLeft | Qt.AlignVCenter, speed)

        painter.setFont(ui_font(TYPE["small"][0]))
        painter.setPen(QColor(COLORS["muted"]))
        painter.drawText(QRectF(0, 37, width, 18), Qt.AlignLeft | Qt.AlignVCenter,
                         self._caption())

        if self.hasFocus():
            painter.setPen(QPen(QColor(COLORS["primary"]), 1))
            painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.end()


class TuningDial(QWidget):
    """The top of the window: wordmark, dial, and signal meter."""

    changed = Signal(int)          # station index

    def __init__(self, stations: List[Station], parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(DIAL_HEIGHT)
        self.setProperty("role", "dial")
        self.setAttribute(Qt.WA_StyledBackground, True)

        self._stations = stations
        self._buttons: List[_StationButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._glide: Optional[QPropertyAnimation] = None

        row = QHBoxLayout(self)
        row.setContentsMargins(SPACE["base"], 0, SPACE["base"], 0)
        row.setSpacing(SPACE["lg"])
        row.addWidget(self._wordmark(), 0, Qt.AlignVCenter)

        self.glass = _Glass()
        strip = QHBoxLayout(self.glass)
        strip.setContentsMargins(0, 0, 0, 0)
        strip.setSpacing(0)
        for number, station in enumerate(stations, start=1):
            button = _StationButton(station, number, self.glass)
            self._buttons.append(button)
            self._group.addButton(button, number - 1)
            strip.addWidget(button, 1)
        row.addWidget(self.glass, 1, Qt.AlignVCenter)

        self.needle = _Needle(self.glass)
        self.needle.raise_()

        self.signal = SignalMeter()
        row.addWidget(self.signal, 0, Qt.AlignVCenter)

        self._group.idClicked.connect(self._on_clicked)
        if self._buttons:
            self._buttons[0].setChecked(True)

    def _wordmark(self) -> QWidget:
        box = QWidget()
        box.setProperty("role", "clear")
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["sm"])

        mark = QLabel()
        mark.setPixmap(draw_mark(28, with_border=False))
        layout.addWidget(mark)

        name = QLabel(__app_name__)
        name.setFont(dial_font(15))
        name.setStyleSheet(f"color: {COLORS['ink']};")
        layout.addWidget(name)
        return box

    # ------------------------------------------------------------------ public
    def set_current(self, index: int, animate: bool = True) -> None:
        if not 0 <= index < len(self._buttons):
            return
        self._buttons[index].setChecked(True)
        self._move_needle(animate)

    def current(self) -> int:
        return self._group.checkedId()

    def set_badge(self, index: int, text: str, lamp: str = "") -> None:
        if 0 <= index < len(self._buttons):
            self._buttons[index].set_badge(text, lamp)

    def install_shortcuts(self, target: QWidget) -> None:
        """Alt+1..N jump between stations; the numerals on the scale say which."""
        for index in range(len(self._buttons)):
            shortcut = QShortcut(QKeySequence(f"Alt+{index + 1}"), target)
            shortcut.activated.connect(lambda i=index: self._activate(i))

    # --------------------------------------------------------------- internals
    def _activate(self, index: int) -> None:
        self.set_current(index)
        self.changed.emit(index)

    def _on_clicked(self, index: int) -> None:
        self._move_needle(True)
        self.changed.emit(index)

    def _station_centres(self) -> List[float]:
        return [button.geometry().center().x() + 0.5 for button in self._buttons]

    def _move_needle(self, animate: bool) -> None:
        button = self._buttons[self.current()]
        target = button.geometry().center().x() + 0.5

        if self._glide is not None:
            self._glide.stop()
        if not animate or motion.reduced() or not self.isVisible():
            self.needle.set_x(target)
            return

        glide = QPropertyAnimation(self.needle, b"needle_x", self)
        glide.setDuration(DURATION["needle"])
        curve = QEasingCurve(QEasingCurve.BezierSpline)
        x1, y1, x2, y2 = EASE_OUT_QUART
        curve.addCubicBezierSegment(QPointF(x1, y1), QPointF(x2, y2), QPointF(1, 1))
        glide.setEasingCurve(curve)
        glide.setStartValue(self.needle.get_x())
        glide.setEndValue(target)
        glide.start()
        self._glide = glide

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        option = QStyleOption()
        option.initFrom(self)
        self.style().drawPrimitive(QStyle.PE_Widget, option, painter, self)

        # The lamp behind the glass spills a little onto the plate beneath it. This is
        # what makes the dial a lit object rather than a pale strip.
        glass = self.glass.geometry()
        top = glass.bottom() + 1
        painter.translate(glass.center().x(), top)
        painter.scale(glass.width() / 2, self.height() - top - 1)
        spill = QRadialGradient(0, 0, 1)
        lit = QColor(COLORS["primary"])
        lit.setAlpha(58)
        spill.setColorAt(0.0, lit)
        lit.setAlpha(30)
        spill.setColorAt(0.7, lit)
        lit.setAlpha(0)
        spill.setColorAt(1.0, lit)
        painter.fillRect(QRectF(-1, 0, 2, 1), spill)
        painter.end()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._sync_glass()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self._sync_glass()

    def _sync_glass(self) -> None:
        self.layout().activate()
        self.glass.layout().activate()
        self.needle.setGeometry(self.glass.rect())
        self.glass.set_stations(self._station_centres())
        self._move_needle(False)
