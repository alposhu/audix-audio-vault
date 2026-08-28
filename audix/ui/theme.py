"""Application theme: palette, fonts, and the global stylesheet.

All values interpolate from :mod:`audix.ui.tokens`, so a token change propagates
everywhere. Nothing in this file hard-codes a color.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from audix.ui.tokens import (
    COLORS, FILL_TEXT, RADIUS, SPACE, STATE_COLORS, TYPE,
    mono_font_stack, rgba, ui_font_stack,
)

# Re-exported so existing call sites keep working after the rework.
__all__ = ["COLORS", "STATE_COLORS", "apply", "stylesheet", "ui_font", "mono_font"]


def _first_available(candidates: list, fallback: str) -> str:
    families = set(QFontDatabase.families())
    for name in candidates:
        if name in families:
            return name
    return fallback


_UI_FAMILY: str = ""
_MONO_FAMILY: str = ""


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


def apply(app: QApplication) -> None:
    """Apply palette, fonts, and stylesheet to the application."""
    global _UI_FAMILY, _MONO_FAMILY

    app.setStyle("Fusion")
    _UI_FAMILY = _first_available(ui_font_stack(), app.font().family())
    _MONO_FAMILY = _first_available(mono_font_stack(), "Courier New")

    app.setPalette(_palette())
    app.setStyleSheet(stylesheet())
    app.setFont(ui_font(TYPE["body"][0]))


def _palette() -> QPalette:
    """Native-drawn surfaces (menus, tooltips, scrollbars) must match the QSS."""
    p = QPalette()
    p.setColor(QPalette.Window, QColor(COLORS["bg"]))
    p.setColor(QPalette.WindowText, QColor(COLORS["ink"]))
    p.setColor(QPalette.Base, QColor(COLORS["surface_2"]))
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


def stylesheet() -> str:
    return _QSS.format(
        **COLORS,
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

/* Labels and checkboxes must not paint the window colour over whatever panel
   they sit on; otherwise every caption inside a surface-coloured group box
   renders as a dark rectangle punched through the panel. */
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

/* ----------------------------------------------------------------- panels */
QFrame[role="panel"] {{
    background-color: {surface};
    border: 1px solid {border};
    border-radius: {r_panel}px;
}}
QFrame[role="inset"] {{
    background-color: {surface_2};
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

/* ----------------------------------------------------------------- inputs */
/* Inputs outline with border_hi: border is only 1.33:1 on surface_2, which
   would leave the edge invisible. Verified in scripts/verify_palette.py. */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background-color: {surface_2};
    border: 1px solid {border_hi};
    border-radius: {r_control}px;
    padding: 7px 10px;
    color: {ink};
    selection-background-color: {primary};
    selection-color: {on_primary};
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: {muted};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QPlainTextEdit:focus {{
    border-color: {primary};
    background-color: {surface_2};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {faint};
    background-color: {surface};
    border-color: {border};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {muted};
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background-color: {surface_2};
    border: 1px solid {border_hi};
    border-radius: {r_control}px;
    selection-background-color: {primary};
    selection-color: {on_primary};
    padding: 4px;
    outline: none;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 16px; }}

/* ---------------------------------------------------------------- buttons */
QPushButton {{
    background-color: {surface_2};
    border: 1px solid {border_hi};
    border-radius: {r_control}px;
    padding: 7px 14px;
    color: {ink};
    font-weight: 500;
    min-height: 18px;
}}
QPushButton:hover  {{ background-color: {surface_3}; border-color: {muted}; }}
QPushButton:pressed {{ background-color: {surface}; }}
QPushButton:focus  {{ border-color: {primary}; }}
QPushButton:disabled {{
    color: {faint};
    background-color: {surface};
    border-color: {border};
}}

/* Primary takes DARK text: white on this cobalt measures 1.95:1. */
QPushButton[variant="primary"] {{
    background-color: {primary};
    border: 1px solid {primary};
    color: {on_primary};
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{
    background-color: {primary_hi};
    border-color: {primary_hi};
}}
QPushButton[variant="primary"]:disabled {{
    background-color: {primary_dim};
    border-color: {primary_dim};
    color: {muted};
}}

/* Destructive takes WHITE text: dark ink on vermillion is only 3.83:1. */
QPushButton[variant="danger"] {{
    background-color: transparent;
    border: 1px solid {border_hi};
    color: {ink};
}}
QPushButton[variant="danger"]:hover {{
    background-color: {accent};
    border-color: {accent};
    color: {on_accent};
}}

QPushButton[variant="ghost"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {muted};
    padding: 6px 10px;
}}
QPushButton[variant="ghost"]:hover {{ color: {ink}; background: {surface_3}; }}
QPushButton[variant="ghost"]:focus {{ border-color: {primary}; }}

QPushButton[variant="nav"] {{
    background: transparent;
    border: 1px solid transparent;
    padding: 6px 10px;
    font-size: 15px;
    color: {muted};
}}
QPushButton[variant="nav"]:hover {{ background: {surface_3}; color: {ink}; }}
QPushButton[variant="nav"]:focus {{ border-color: {primary}; }}

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
QPushButton[variant="tool"]:disabled {{ color: {faint}; border-color: {border}; }}

/* ------------------------------------------------------------ rail (nav) */
QWidget[role="rail"] {{
    background-color: {surface};
    border-right: 1px solid {border};
}}
QToolButton[role="railitem"] {{
    background: transparent;
    border: none;
    border-radius: {r_control}px;
    color: {muted};
    padding: 6px;
    font-size: {t_micro}px;
}}
QToolButton[role="railitem"]:hover {{ background: {surface_3}; color: {ink}; }}
QToolButton[role="railitem"]:checked {{
    background: {primary_wash};
    color: {primary};
}}
QToolButton[role="railitem"]:focus {{ border: 1px solid {primary}; }}

/* -------------------------------------------------------------- progress */
QProgressBar {{
    background-color: {surface_2};
    border: 1px solid {border};
    border-radius: 5px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background-color: {primary}; border-radius: 4px; }}
QProgressBar[tone="success"]::chunk {{ background-color: {success}; }}
QProgressBar[tone="error"]::chunk   {{ background-color: {accent}; }}
QProgressBar[tone="idle"]::chunk    {{ background-color: {border_hi}; }}

/* ----------------------------------------------------------------- lists */
QListWidget, QTreeWidget, QTableWidget {{
    background-color: {surface};
    border: 1px solid {border};
    border-radius: {r_panel}px;
    outline: none;
    padding: 4px;
}}
QListWidget::item {{ background: transparent; border-radius: {r_control}px; margin: 2px; }}
QListWidget::item:selected {{ background: {primary_wash}; }}
QListWidget::item:hover {{ background: {surface_3}; }}

/* ------------------------------------------------------------- checkboxes */
QCheckBox {{ spacing: 9px; padding: 3px 0; color: {ink}; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {border_hi};
    border-radius: 4px;
    background: {surface_2};
}}
QCheckBox::indicator:hover {{ border-color: {primary}; }}
QCheckBox::indicator:checked {{ background: {primary}; border-color: {primary}; }}
QCheckBox::indicator:disabled {{ border-color: {border}; background: {surface}; }}
QCheckBox:disabled {{ color: {faint}; }}

QRadioButton {{ spacing: 9px; color: {ink}; }}
QRadioButton::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {border_hi};
    border-radius: 8px;
    background: {surface_2};
}}
QRadioButton::indicator:checked {{
    background: {primary};
    border: 4px solid {surface_2};
}}

/* --------------------------------------------------------------- sliders */
QSlider::groove:horizontal {{
    height: 4px;
    background: {surface_3};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{ background: {primary}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {ink};
    width: 12px; height: 12px;
    margin: -5px 0;
    border-radius: 6px;
}}
QSlider::handle:horizontal:hover {{ background: {primary_hi}; }}

/* ------------------------------------------------------------- group box */
QGroupBox {{
    border: 1px solid {border};
    border-radius: {r_panel}px;
    margin-top: 14px;
    padding: 16px 14px 12px 14px;
    background-color: {surface};
    font-weight: 600;
    color: {ink};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: {muted};
    font-size: {t_small}px;
    font-weight: 600;
}}

/* ------------------------------------------------------------- scrollbar */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {border_hi}; border-radius: 5px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {muted}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: {border_hi}; border-radius: 5px; min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{ background: {muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ------------------------------------------------------------- statusbar */
QStatusBar {{
    background-color: {surface};
    border-top: 1px solid {border};
    color: {muted};
}}
QStatusBar::item {{ border: none; }}

QToolTip {{
    background-color: {surface_3};
    color: {ink};
    border: 1px solid {border_hi};
    border-radius: {r_control}px;
    padding: 6px 8px;
}}

QMenu {{
    background-color: {surface_2};
    border: 1px solid {border_hi};
    border-radius: {r_control}px;
    padding: 4px;
}}
QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {primary_wash}; color: {primary}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}

QSplitter::handle {{ background: {border}; }}
QSplitter::handle:hover {{ background: {primary_dim}; }}

/* Legacy tab styling retained for any remaining QTabWidget usage. */
QTabWidget::pane {{
    border: 1px solid {border};
    border-radius: {r_panel}px;
    background-color: {surface};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {muted};
    padding: 8px 16px;
    margin-right: 4px;
    border: 1px solid transparent;
    border-top-left-radius: {r_control}px;
    border-top-right-radius: {r_control}px;
}}
QTabBar::tab:selected {{
    background: {surface};
    color: {primary};
    border: 1px solid {border};
}}
"""
