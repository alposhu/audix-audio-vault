"""Application theme: palette, fonts, and the global stylesheet.

All values interpolate from :mod:`audix.ui.tokens`, so a token change propagates
everywhere. Nothing in this file hard-codes a color.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication

from audix.ui import icons
from audix.ui.tokens import (
    COLORS, DIAL_FONT_FAMILY, DIAL_FONT_FILE, FILL_TEXT, RADIUS, SPACE, STATE_COLORS, TYPE,
    mono_font_stack, rgba, ui_font_stack,
)
from audix.utils import paths, runtime

log = logging.getLogger("audix.ui.theme")

# Re-exported so existing call sites keep working after the rework.
__all__ = ["COLORS", "STATE_COLORS", "apply", "stylesheet", "ui_font", "mono_font",
           "dial_font"]


def _first_available(candidates: list, fallback: str) -> str:
    families = set(QFontDatabase.families())
    for name in candidates:
        if name in families:
            return name
    return fallback


_UI_FAMILY: str = ""
_MONO_FAMILY: str = ""
_DIAL_FAMILY: str = ""


def ui_font(size: int = None, weight: int = None) -> QFont:
    """A UI font at the given size/weight, using the resolved family."""
    font = QFont(_UI_FAMILY or "Sans Serif")
    font.setPixelSize(size or TYPE["body"][0])
    if weight is not None:
        font.setWeight(QFont.Weight(weight))
    return font


def mono_font(size: int = None, weight: int = None) -> QFont:
    """A monospace font with **tabular figures** for timecodes and dB readouts."""
    font = QFont(_MONO_FAMILY or "Monospace")
    font.setPixelSize(size or TYPE["body"][0])
    if weight is not None:
        font.setWeight(QFont.Weight(weight))
    font.setStyleHint(QFont.Monospace)
    # Digits must not change width between frames during playback.
    font.setFixedPitch(True)
    return font


def dial_font(size: int) -> QFont:
    """The silkscreened face used on the tuning dial, and nowhere else."""
    font = QFont(_DIAL_FAMILY or _UI_FAMILY or "Sans Serif")
    font.setPixelSize(size)
    return font


def apply(app: QApplication) -> None:
    """Apply palette, fonts, and stylesheet to the application."""
    global _UI_FAMILY, _MONO_FAMILY, _DIAL_FAMILY

    app.setStyle("Fusion")
    _UI_FAMILY = _first_available(ui_font_stack(), app.font().family())
    _MONO_FAMILY = _first_available(mono_font_stack(), "Courier New")
    _DIAL_FAMILY = _load_dial_face()

    # Asking for dark gives Windows a dark title bar to match, and makes embedded
    # pages see prefers-color-scheme: dark, so YouTube opens in its dark theme.
    hints = app.styleHints()
    if hasattr(hints, "setColorScheme"):
        hints.setColorScheme(Qt.ColorScheme.Dark)

    app.setPalette(_palette())
    app.setStyleSheet(stylesheet())
    app.setFont(ui_font(TYPE["body"][0]))


def _load_dial_face() -> str:
    """Register the bundled dial face. Falls back to the UI face if it is missing."""
    path = _bundled_font()
    if path is None:
        log.warning("Dial font %s is missing; using the UI font", DIAL_FONT_FILE)
        return ""
    if QFontDatabase.addApplicationFont(str(path)) < 0:
        log.warning("Dial font could not be loaded from %s", path)
        return ""
    return DIAL_FONT_FAMILY


def _bundled_font() -> "Path | None":
    relative = Path("audix") / "assets" / "fonts" / DIAL_FONT_FILE
    for root in (runtime.bundle_dir(), Path(__file__).resolve().parents[2]):
        candidate = root / relative
        if candidate.is_file():
            return candidate
    return None


def _palette() -> QPalette:
    """Native-drawn surfaces (menus, tooltips, scrollbars) must match the QSS."""
    p = QPalette()
    p.setColor(QPalette.Window, QColor(COLORS["bg"]))
    p.setColor(QPalette.WindowText, QColor(COLORS["ink"]))
    p.setColor(QPalette.Base, QColor(COLORS["well"]))
    p.setColor(QPalette.AlternateBase, QColor(COLORS["surface"]))
    p.setColor(QPalette.ToolTipBase, QColor(COLORS["surface_3"]))
    p.setColor(QPalette.ToolTipText, QColor(COLORS["ink"]))
    p.setColor(QPalette.Text, QColor(COLORS["ink"]))
    p.setColor(QPalette.Button, QColor(COLORS["surface_2"]))
    p.setColor(QPalette.ButtonText, QColor(COLORS["ink"]))
    p.setColor(QPalette.BrightText, QColor(COLORS["accent"]))
    p.setColor(QPalette.Highlight, QColor(COLORS["primary"]))
    p.setColor(QPalette.HighlightedText, QColor(FILL_TEXT["primary"]))
    p.setColor(QPalette.Link, QColor(COLORS["primary"]))
    p.setColor(QPalette.PlaceholderText, QColor(COLORS["faint"]))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(COLORS["faint"]))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(COLORS["faint"]))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor(COLORS["faint"]))
    return p


def _indicator_images() -> dict:
    """Write the small images QSS can only take from disk.

    QSS has no way to draw a tick or an arrow, and without a tick a checked box
    would be distinguishable from an empty one by color alone. Sizes are written at
    both densities; Qt picks the ``@2x`` file on high-DPI screens by itself.
    """
    folder = paths.cache_dir() / "ui"
    folder.mkdir(parents=True, exist_ok=True)

    def write(name: str, size: int, icon_name: str, color: str) -> str:
        for scale, suffix in ((1, ""), (2, "@2x")):
            pixmap = QPixmap(size * scale, size * scale)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            icons.paint(painter, icon_name, QRectF(0, 0, size * scale, size * scale), color)
            painter.end()
            pixmap.save(str(folder / f"{name}{suffix}.png"))
        return (folder / f"{name}.png").as_posix()

    return {
        "img_tick": write("tick", 14, "check", FILL_TEXT["primary"]),
        "img_dash": write("dash", 14, "minus", FILL_TEXT["primary"]),
        "img_arrow": write("arrow", 12, "chevron_down", COLORS["muted"]),
        "img_arrow_up": write("arrow-up", 10, "chevron_up", COLORS["muted"]),
        "img_arrow_down": write("arrow-down", 10, "chevron_down", COLORS["muted"]),
    }


def stylesheet() -> str:
    return _QSS.format(
        **COLORS,
        **_indicator_images(),
        on_primary=FILL_TEXT["primary"],
        on_accent=FILL_TEXT["accent"],
        primary_wash=rgba("primary", 0.14),
        primary_wash_hi=rgba("primary", 0.22),
        accent_wash=rgba("accent", 0.16),
        r_control=RADIUS["control"],
        r_panel=RADIUS["panel"],
        s_sm=SPACE["sm"],
        s_md=SPACE["md"],
        s_base=SPACE["base"],
        t_body=TYPE["body"][0],
        t_small=TYPE["small"][0],
        t_micro=TYPE["micro"][0],
        t_h1=TYPE["h1"][0],
        t_h2=TYPE["h2"][0],
        t_display=TYPE["display"][0],
    )


_QSS = """
QWidget {{
    background-color: {bg};
    color: {ink};
    font-size: {t_body}px;
}}
QMainWindow, QDialog {{ background-color: {bg}; }}

/* Labels and checkboxes must not paint the plate colour over whatever window
   they sit in; otherwise every caption renders as a rectangle punched through. */
QLabel, QCheckBox, QRadioButton, QGroupBox::title {{ background: transparent; }}

/* ------------------------------------------------------------- typography */
QLabel[role="display"] {{ font-size: {t_display}px; font-weight: 600; color: {ink}; }}
QLabel[role="h1"]      {{ font-size: {t_h1}px; font-weight: 600; color: {ink}; }}
QLabel[role="h2"]      {{ font-size: {t_h2}px; font-weight: 600; color: {ink}; }}
QLabel[role="body"]    {{ color: {ink}; }}
QLabel[role="muted"]   {{ color: {muted}; font-size: {t_small}px; }}
QLabel[role="hint"]    {{ color: {faint}; font-size: {t_small}px; }}
QLabel[role="micro"]   {{ color: {muted}; font-size: {t_micro}px; font-weight: 500; }}
QLabel[role="error"]   {{ color: {accent}; font-size: {t_small}px; }}
QLabel[role="success"] {{ color: {success}; font-size: {t_small}px; }}
QLabel[role="warning"] {{ color: {warning}; font-size: {t_small}px; }}

/* ----------------------------------------------------- plate and windows */
/* A window is recessed into the plate. Light comes from above, so the top edge is
   in shadow, the sides are barely there, and the lower lip catches the light. */
QFrame[role="window"] {{
    background-color: {well};
    border-top: 2px solid {shade};
    border-left: 1px solid {surface};
    border-right: 1px solid {surface};
    border-bottom: 1px solid {border_hi};
    border-radius: 1px;
}}
QFrame[role="sidePanel"] {{
    background-color: {surface};
    border: none;
    border-left: 1px solid {border_hi};
}}
QFrame[role="plateBar"] {{
    background-color: {bg};
    border: none;
    border-top: 1px solid {border};
}}
/* A strip is a lower section of the same plate. */
QFrame[role="strip"] {{
    background-color: {surface};
    border: none;
    border-top: 1px solid {border};
}}
QFrame[role="stripTop"] {{
    background-color: {surface};
    border: none;
    border-bottom: 1px solid {border};
}}
QFrame[role="panel"] {{
    background-color: {surface};
    border: 1px solid {border};
    border-radius: {r_panel}px;
}}
QFrame[role="inset"] {{
    background-color: {well};
    border: 1px solid {border};
    border-radius: {r_control}px;
}}
QFrame[role="divider"] {{
    background-color: {border};
    max-height: 1px;
    border: none;
}}
QFrame[role="vdivider"] {{
    background-color: {border};
    max-width: 1px;
    border: none;
}}
QWidget[role="clear"], QFrame[role="clear"] {{ background: transparent; }}
QWidget[role="wellPage"]  {{ background-color: {well}; }}
QWidget[role="panelBody"] {{ background-color: {surface}; }}
QWidget[role="dial"] {{
    background-color: {bg};
    border-bottom: 1px solid {well};
}}
QFrame[role="toast"] {{
    background-color: {surface_3};
    border: 1px solid {border_hi};
    border-radius: {r_panel}px;
}}
QFrame[role="notice"] {{
    background-color: {surface_2};
    border: 1px solid {border};
    border-radius: {r_control}px;
}}

/* ----------------------------------------------------------------- inputs */
/* Fields are recessed like windows, so they outline with border_hi. */
QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background-color: {well};
    border: 1px solid {border_hi};
    border-radius: {r_control}px;
    padding: 7px 10px;
    color: {ink};
    selection-background-color: {primary};
    selection-color: {on_primary};
}}
QLineEdit[size="large"] {{ padding: 10px 12px; font-size: {t_h2}px; }}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: {muted}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus {{
    border-color: {primary};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {faint};
    background-color: {surface};
    border-color: {border};
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 18px;
    background: transparent;
    border: none;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url("{img_arrow_up}"); width: 10px; height: 10px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url("{img_arrow_down}"); width: 10px; height: 10px;
}}

/* A selector is a key: raised, not recessed. */
QComboBox {{
    background-color: {surface_2};
    border: 1px solid {border};
    border-top-color: {border_hi};
    border-bottom-color: {surface};
    border-radius: {r_control}px;
    padding: 6px 10px;
    color: {ink};
    selection-background-color: {primary};
    selection-color: {on_primary};
}}
QComboBox:hover {{ background-color: {surface_3}; border-color: {muted}; }}
QComboBox:focus {{ border-color: {primary}; }}
QComboBox:disabled {{
    color: {faint};
    background-color: {surface};
    border-color: {border};
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url("{img_arrow}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background-color: {surface_2};
    border: 1px solid {border_hi};
    selection-background-color: {primary};
    selection-color: {on_primary};
    padding: 4px;
    outline: none;
}}

/* ---------------------------------------------------------------- buttons */
/* Keys catch light on the top edge and fall into shadow on the bottom. */
QPushButton, QToolButton[role="key"] {{
    background-color: {surface_2};
    border: 1px solid {border};
    border-top-color: {border_hi};
    border-bottom-color: {surface};
    border-radius: {r_control}px;
    padding: 7px 14px;
    color: {ink};
    font-weight: 500;
    min-height: 18px;
}}
QPushButton:hover, QToolButton[role="key"]:hover {{
    background-color: {surface_3};
    border-color: {muted};
}}
QPushButton:pressed, QToolButton[role="key"]:pressed {{
    background-color: {surface};
    border-top-color: {surface};
    border-bottom-color: {border_hi};
}}
QPushButton:focus, QToolButton[role="key"]:focus {{ border-color: {primary}; }}
QPushButton:disabled, QToolButton[role="key"]:disabled {{
    color: {faint};
    background-color: {bg};
    border-color: {surface_3};
}}
QToolButton[role="key"]::menu-indicator {{ image: none; }}

/* Primary is the lit key: tungsten with dark ink. Unlit, it is simply off. */
QPushButton[variant="primary"] {{
    background-color: {primary};
    border: 1px solid {primary};
    border-top-color: {primary_hi};
    color: {on_primary};
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{
    background-color: {primary_hi};
    border-color: {primary_hi};
}}
QPushButton[variant="primary"]:pressed {{
    background-color: {primary};
    border-color: {primary};
}}
QPushButton[variant="primary"]:focus {{ border-color: {ink}; }}
QPushButton[variant="primary"]:disabled {{
    background-color: {bg};
    border-color: {surface_3};
    color: {faint};
    font-weight: 500;
}}

/* Destructive stays an outline until it is deliberately approached. */
QPushButton[variant="danger"] {{
    background-color: transparent;
    border: 1px solid {border};
    color: {muted};
}}
QPushButton[variant="danger"]:hover {{
    background-color: {accent};
    border-color: {accent};
    color: {on_accent};
}}
QPushButton[variant="danger"]:focus {{ border-color: {accent}; }}
QPushButton[variant="danger"]:disabled {{
    color: {faint};
    border-color: {surface_3};
}}

QPushButton[variant="ghost"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {muted};
    padding: 6px 10px;
}}
QPushButton[variant="ghost"]:hover {{ color: {ink}; background: {surface_3}; }}
QPushButton[variant="ghost"]:focus {{ border-color: {primary}; }}
QPushButton[variant="ghost"]:disabled {{ color: {faint}; background: transparent; }}

QPushButton[variant="nav"], QToolButton[role="nav"] {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {r_control}px;
    padding: 6px;
    color: {muted};
}}
QPushButton[variant="nav"]:hover, QToolButton[role="nav"]:hover {{
    background: {surface_3};
    color: {ink};
}}
QPushButton[variant="nav"]:focus, QToolButton[role="nav"]:focus {{
    border-color: {primary};
}}

/* Selector keys: a filter that stays lit from beneath while it is chosen. */
QPushButton[variant="selector"] {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    padding: 6px 12px;
    color: {muted};
    font-weight: 500;
}}
QPushButton[variant="selector"]:hover {{ color: {ink}; }}
QPushButton[variant="selector"]:checked {{
    color: {ink};
    border-bottom-color: {primary};
}}
QPushButton[variant="selector"]:focus {{ color: {primary}; }}

/* Tool buttons in the editor toolbar */
QPushButton[variant="tool"] {{
    background: {surface_2};
    border: 1px solid {border};
    border-radius: {r_control}px;
    padding: 6px 11px;
    color: {ink};
    font-size: {t_small}px;
}}
QPushButton[variant="tool"]:hover {{ background: {surface_3}; border-color: {muted}; }}
QPushButton[variant="tool"]:checked {{
    background: {primary_wash};
    border-color: {primary};
    color: {primary};
}}
QPushButton[variant="tool"]:disabled {{ color: {faint}; border-color: {surface_3}; }}

/* -------------------------------------------------------------- progress */
QProgressBar {{
    background-color: {well};
    border: 1px solid {border};
    border-radius: 2px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background-color: {primary}; border-radius: 1px; }}
QProgressBar[tone="success"]::chunk {{ background-color: {success}; }}
QProgressBar[tone="error"]::chunk   {{ background-color: {accent}; }}
QProgressBar[tone="idle"]::chunk    {{ background-color: {border_hi}; }}

/* ----------------------------------------------------------------- lists */
QListView, QListWidget, QTreeWidget, QTableWidget {{
    background-color: {well};
    border: none;
    outline: none;
}}
QListWidget {{
    border: 1px solid {border};
    border-radius: {r_panel}px;
    padding: 4px;
}}
QListWidget::item {{ background: transparent; border-radius: {r_control}px; margin: 2px; }}
QListWidget::item:selected {{ background: {primary_wash}; }}
QListWidget::item:hover {{ background: {surface}; }}

/* ------------------------------------------------------------- checkboxes */
QCheckBox {{ spacing: 9px; padding: 3px 0; color: {ink}; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {border_hi};
    border-radius: 3px;
    background: {well};
}}
QCheckBox::indicator:hover {{ border-color: {primary}; }}
QCheckBox::indicator:checked {{
    background: {primary};
    border-color: {primary};
    image: url("{img_tick}");
}}
QCheckBox::indicator:indeterminate {{
    background: {primary};
    border-color: {primary};
    image: url("{img_dash}");
}}
QCheckBox::indicator:disabled {{ border-color: {border}; background: {surface}; }}
QCheckBox::indicator:checked:disabled {{
    background: {primary_dim};
    border-color: {primary_dim};
}}
QCheckBox:disabled {{ color: {faint}; }}

QRadioButton {{ spacing: 9px; color: {ink}; }}
QRadioButton::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {border_hi};
    border-radius: 8px;
    background: {well};
}}
QRadioButton::indicator:checked {{
    background: {primary};
    border: 4px solid {well};
}}

/* --------------------------------------------------------------- sliders */
/* A fader cap on a slot. The cap is the reading: these are bipolar controls, so a
   lit track would show half on at zero, where nothing is happening. */
QSlider::groove:horizontal {{
    height: 4px;
    background: {well};
    border-radius: 1px;
}}
QSlider::handle:horizontal {{
    background: {ink};
    width: 8px; height: 16px;
    margin: -6px 0;
    border-radius: 2px;
}}
QSlider::handle:horizontal:hover {{ background: {primary_hi}; }}

/* ------------------------------------------------------------- group box */
/* A section of the plate under a printed rule, never a box inside a box. */
QGroupBox {{
    border: none;
    border-top: 1px solid {border};
    margin-top: 6px;
    padding: 30px 0 8px 0;
    background: transparent;
    font-weight: 600;
    color: {ink};
}}
QGroupBox::title {{
    subcontrol-origin: padding;
    subcontrol-position: top left;
    left: 0;
    top: 10px;
    color: {ink};
    font-size: {t_body}px;
    font-weight: 600;
}}

/* ------------------------------------------------------------- scrollbar */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {border}; border-radius: 2px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {border_hi}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: {border}; border-radius: 2px; min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{ background: {border_hi}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QToolTip {{
    background-color: {surface_3};
    color: {ink};
    border: 1px solid {border_hi};
    padding: 6px 8px;
}}

QMenu {{
    background-color: {surface_2};
    border: 1px solid {border_hi};
    padding: 4px;
}}
QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 2px; }}
QMenu::item:selected {{ background: {primary}; color: {on_primary}; }}
QMenu::item:disabled {{ color: {faint}; background: transparent; }}
QMenu::icon {{ padding-left: 8px; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}

QSplitter::handle {{ background: {border}; }}
QSplitter::handle:hover {{ background: {primary_dim}; }}
"""
