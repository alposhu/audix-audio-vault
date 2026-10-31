"""The icon set, drawn once in code.

Every icon is authored on a 24-unit grid with one stroke weight, so toolbars,
painted rows, and menus share a single hand. Drawing them keeps the set free of
asset files and sharp at any device pixel ratio, and it is what lets a painted row
tint the same glyph for any state.
"""
from __future__ import annotations

from math import cos, pi, sin
from typing import Callable, Dict, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QBrush, QColor, QGuiApplication, QIcon, QPainter, QPainterPath, QPen, QPixmap,
)

from audix.ui.tokens import COLORS

STROKE = 1.75

_Draw = Callable[[QPainter], None]
_cache: Dict[Tuple[str, int, str, float], QPixmap] = {}


def _line(painter: QPainter, *points: Tuple[float, float]) -> None:
    path = QPainterPath(QPointF(*points[0]))
    for point in points[1:]:
        path.lineTo(*point)
    painter.drawPath(path)


def _filled(painter: QPainter, *points: Tuple[float, float]) -> None:
    path = QPainterPath(QPointF(*points[0]))
    for point in points[1:]:
        path.lineTo(*point)
    path.closeSubpath()
    painter.save()
    painter.setBrush(painter.pen().color())
    painter.drawPath(path)
    painter.restore()


def _arc_arrow(painter: QPainter) -> None:
    """A circular arrow: reload, and retrying a failed download."""
    radius = 8.0
    rect = QRectF(12 - radius, 12 - radius, radius * 2, radius * 2)
    path = QPainterPath()
    path.arcMoveTo(rect, 60)
    path.arcTo(rect, 60, 285)
    painter.drawPath(path)
    angle = 60 * pi / 180
    tip = (12 + radius * cos(angle), 12 - radius * sin(angle))
    _line(painter, (tip[0] - 4.5, tip[1] - 2.2), tip, (tip[0] + 0.3, tip[1] + 4.6))


def _back(p): _line(p, (19.5, 12), (4.5, 12)); _line(p, (11, 5.5), (4.5, 12), (11, 18.5))
def _forward(p): _line(p, (4.5, 12), (19.5, 12)); _line(p, (13, 5.5), (19.5, 12), (13, 18.5))
def _close(p): _line(p, (6, 6), (18, 18)); _line(p, (18, 6), (6, 18))
def _plus(p): _line(p, (12, 5), (12, 19)); _line(p, (5, 12), (19, 12))
def _minus(p): _line(p, (5.5, 12), (18.5, 12))
def _check(p): _line(p, (4.5, 12.5), (9.5, 17.5), (19.5, 6.5))
def _chevron_down(p): _line(p, (6, 9), (12, 15), (18, 9))
def _chevron_right(p): _line(p, (9, 6), (15, 12), (9, 18))
def _chevron_up(p): _line(p, (6, 15), (12, 9), (18, 15))


def _home(p):
    _line(p, (4, 11.5), (12, 4.5), (20, 11.5))
    _line(p, (6.5, 10), (6.5, 19.5), (17.5, 19.5), (17.5, 10))


def _download(p):
    _line(p, (12, 4), (12, 15))
    _line(p, (7, 10.5), (12, 15.5), (17, 10.5))
    _line(p, (4.5, 15.5), (4.5, 19.5), (19.5, 19.5), (19.5, 15.5))


def _pause(p):
    p.save()
    p.setBrush(p.pen().color())
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(6.5, 5, 4, 14), 1, 1)
    p.drawRoundedRect(QRectF(13.5, 5, 4, 14), 1, 1)
    p.restore()


def _play(p):
    _filled(p, (7.5, 4.8), (18.5, 12), (7.5, 19.2))


def _stop(p):
    p.save()
    p.setBrush(p.pen().color())
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(6, 6, 12, 12), 1.5, 1.5)
    p.restore()


def _top(p):
    _line(p, (5, 4.5), (19, 4.5))
    _line(p, (12, 20), (12, 9.5))
    _line(p, (7, 14), (12, 9), (17, 14))


def _trash(p):
    _line(p, (4, 6.5), (20, 6.5))
    _line(p, (9.5, 6.5), (9.5, 4), (14.5, 4), (14.5, 6.5))
    _line(p, (6, 6.5), (7, 20), (17, 20), (18, 6.5))
    _line(p, (10, 10.5), (10, 16))
    _line(p, (14, 10.5), (14, 16))


def _folder(p):
    _line(p, (3.5, 18.5), (3.5, 5.5), (9.5, 5.5), (11.5, 8), (20.5, 8), (20.5, 18.5))
    _line(p, (3.5, 18.5), (20.5, 18.5))


def _wave(p):
    for x, half in ((4, 3), (8, 7), (12, 4.5), (16, 8), (20, 3)):
        _line(p, (x, 12 - half), (x, 12 + half))


def _link(p):
    p.save()
    p.translate(12, 12)
    p.rotate(-45)
    p.drawRoundedRect(QRectF(-9.5, -3.2, 10.5, 6.4), 3.2, 3.2)
    p.drawRoundedRect(QRectF(-1, -3.2, 10.5, 6.4), 3.2, 3.2)
    p.restore()


def _paste(p):
    p.drawRoundedRect(QRectF(5.5, 5.5, 13, 15), 1.5, 1.5)
    p.drawRoundedRect(QRectF(9, 3, 6, 4), 1, 1)


def _copy(p):
    p.drawRoundedRect(QRectF(8.5, 8.5, 11, 12), 1.5, 1.5)
    _line(p, (15.5, 8.5), (15.5, 5), (4.5, 5), (4.5, 16.5), (8.5, 16.5))


def _search(p):
    p.drawEllipse(QRectF(4, 4, 12.5, 12.5))
    _line(p, (14.8, 14.8), (20, 20))


def _globe(p):
    p.drawEllipse(QRectF(3.5, 3.5, 17, 17))
    p.drawEllipse(QRectF(8, 3.5, 8, 17))
    _line(p, (3.5, 12), (20.5, 12))


def _external(p):
    _line(p, (10, 5), (5, 5), (5, 19), (19, 19), (19, 14))
    _line(p, (12.5, 11.5), (19.5, 4.5))
    _line(p, (14, 4.5), (19.5, 4.5), (19.5, 10))


def _more(p):
    p.save()
    p.setBrush(p.pen().color())
    p.setPen(Qt.NoPen)
    for x in (5.5, 12, 18.5):
        p.drawEllipse(QPointF(x, 12), 1.7, 1.7)
    p.restore()


def _person(p):
    p.drawEllipse(QRectF(8, 3.8, 8, 8))
    path = QPainterPath(QPointF(4.5, 20.5))
    path.cubicTo(5, 16, 8.5, 14.5, 12, 14.5)
    path.cubicTo(15.5, 14.5, 19, 16, 19.5, 20.5)
    p.drawPath(path)


def _gear(p):
    p.drawEllipse(QRectF(9, 9, 6, 6))
    for step in range(8):
        angle = step * pi / 4
        _line(p,
              (12 + 7.5 * cos(angle), 12 + 7.5 * sin(angle)),
              (12 + 9.5 * cos(angle), 12 + 9.5 * sin(angle)))
    p.drawEllipse(QRectF(5.5, 5.5, 13, 13))


def _note(p):
    _line(p, (9, 17.5), (9, 5.5), (19, 3.8), (19, 15.5))
    p.drawEllipse(QRectF(4.2, 15, 4.8, 4.8))
    p.drawEllipse(QRectF(14.2, 13, 4.8, 4.8))


_ICONS: Dict[str, _Draw] = {
    "back": _back, "forward": _forward, "reload": _arc_arrow, "retry": _arc_arrow,
    "home": _home, "close": _close, "plus": _plus, "minus": _minus, "check": _check,
    "chevron_down": _chevron_down, "chevron_right": _chevron_right,
    "chevron_up": _chevron_up, "download": _download, "pause": _pause, "play": _play,
    "stop": _stop, "top": _top, "trash": _trash, "folder": _folder, "wave": _wave,
    "link": _link, "paste": _paste, "copy": _copy, "search": _search, "globe": _globe,
    "external": _external, "more": _more, "person": _person, "gear": _gear, "note": _note,
}


def paint(painter: QPainter, name: str, rect: QRectF, color: str) -> None:
    """Draw an icon into ``rect`` on an existing painter."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.translate(rect.topLeft())
    painter.scale(rect.width() / 24.0, rect.height() / 24.0)
    pen = QPen(QColor(color), STROKE)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    _ICONS[name](painter)
    painter.restore()


def pixmap(name: str, size: int = 18, color: Optional[str] = None) -> QPixmap:
    """A cached, DPI-correct pixmap of an icon."""
    color = color or COLORS["ink"]
    app = QGuiApplication.instance()
    ratio = app.devicePixelRatio() if app else 1.0
    key = (name, size, color, ratio)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    pix = QPixmap(QSize(round(size * ratio), round(size * ratio)))
    pix.setDevicePixelRatio(ratio)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    paint(painter, name, QRectF(0, 0, size, size), color)
    painter.end()
    _cache[key] = pix
    return pix


def icon(name: str, size: int = 18, color: Optional[str] = None) -> QIcon:
    """A ``QIcon`` with a dimmed disabled state, for buttons and menus."""
    result = QIcon()
    result.addPixmap(pixmap(name, size, color or COLORS["ink"]), QIcon.Normal)
    result.addPixmap(pixmap(name, size, COLORS["faint"]), QIcon.Disabled)
    return result


def brush_for(color: str) -> QBrush:
    return QBrush(QColor(color))
