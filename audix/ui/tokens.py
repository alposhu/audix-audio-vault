"""Design tokens: the single source of truth for color, spacing, and type.

Every hex value here is derived from an OKLCH source and verified by
``scripts/verify_palette.py``, which fails on any contrast or gamut regression.
Do not hand-edit a hex value; change the OKLCH in the verifier and regenerate.

The world is a hi-fi receiver with the room lights off (see DESIGN.md): a warm
bronze faceplate, content recessed behind dark glass, and one lit tuning dial as the
brightest object on screen. Tungsten means lit, and lit means it will act now.
"""
from __future__ import annotations

from typing import Dict, Final

# ---------------------------------------------------------------------- color

#: Verified palette. Contrast ratios in comments are against ``bg``.
COLORS: Final[Dict[str, str]] = {
    # Bronze ramp, darkest to lightest. The plate is not the darkest surface:
    # controls sit on it, and content sits behind it in darker recessed windows.
    "shade":       "#040303",   # the edge of a well that falls into shadow
    "well":        "#0d0b08",   # recessed window glass
    "surface":     "#1e1813",   # lower plate, transport strip
    "bg":          "#2b241c",   # faceplate
    "surface_2":   "#393027",   # keys, raised controls
    "surface_3":   "#453b31",   # key hover
    "border":      "#564b41",   # edges
    "border_hi":   "#76695d",   # input outlines

    # Text
    "ink":         "#f1eee6",   # body                13.26:1
    "muted":       "#c3bdb1",   # secondary            8.21:1
    "faint":       "#b0a89b",   # placeholder          6.53:1

    # The dial: the one lit field in the interface
    "glass":       "#e9d4a3",
    "glass_edge":  "#c9ad7a",   # falloff toward the ends of the dial
    "glass_ink":   "#312317",   # printed scale       10.38:1 on glass
    "glass_soft":  "#5f4c38",   # scale ticks          5.60:1 on glass
    "needle":      "#e02e1e",   #                      3.13:1 on glass

    # Tungsten - lit means it will act now
    "primary":     "#eecb7d",   #                      9.83:1
    "primary_hi":  "#f6e2aa",   # hover
    "primary_dim": "#6f5a35",   # unlit

    # Semantic - red means failure, destruction, or clipping, and the needle
    "accent":      "#ed4c3a",
    "success":     "#6ed889",
    "warning":     "#f19a4b",

    # Waveform two-tone
    "wave_peak":   "#907238",   # min/max envelope
    "wave_rms":    "#edcd83",   # RMS body
}

#: Which text color each filled control must use. Measured, not guessed: every
#: fill in this palette reads better with dark ink than with white.
FILL_TEXT: Final[Dict[str, str]] = {
    "primary": COLORS["well"],
    "success": COLORS["well"],
    "warning": COLORS["well"],
    "accent":  COLORS["well"],
}

#: Task state -> lamp color, shared by the Downloads page and the editor.
STATE_COLORS: Final[Dict[str, str]] = {
    "Waiting":     COLORS["faint"],
    "Paused":      COLORS["warning"],
    "Preparing":   COLORS["primary"],
    "Downloading": COLORS["primary"],
    "Converting":  COLORS["primary"],
    "Tagging":     COLORS["primary"],
    "Editing":     COLORS["primary"],
    "Finished":    COLORS["success"],
    "Failed":      COLORS["accent"],
    "Cancelled":   COLORS["faint"],
}


def rgba(token: str, alpha: float) -> str:
    """``rgba()`` string for a token, for washes and overlays."""
    value = COLORS[token].lstrip("#")
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alpha:.3f})"


def rgb_tuple(token: str) -> tuple:
    value = COLORS[token].lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


# -------------------------------------------------------------------- spacing

#: 4px base unit. Rhythm comes from varying these, not from one uniform gap.
SPACE: Final[Dict[str, int]] = {
    "xs": 4, "sm": 8, "md": 12, "base": 16,
    "lg": 20, "xl": 24, "2xl": 32, "3xl": 48, "4xl": 64,
}

#: Hardware is rectilinear: keys and windows take a slight ease, nothing rounder.
RADIUS: Final[Dict[str, int]] = {
    "control": 3,
    "panel": 4,
    "selection": 3,
    "pill": 999,
}

#: Semantic stacking order. Never write a bare 999.
Z: Final[Dict[str, int]] = {
    "base": 0, "raised": 10, "sticky": 20,
    "overlay": 30, "modal": 40, "toast": 50, "tooltip": 60,
}


# ----------------------------------------------------------------- typography

#: Fixed scale at ratio ~1.16. Not fluid: a clamp-sized heading that shrinks
#: inside a panel looks worse, not better (product register).
TYPE: Final[Dict[str, tuple]] = {
    # name:      (px, weight, letter-spacing em)
    "display":   (22, 600, -0.02),
    "h1":        (18, 600, -0.01),
    "h2":        (15, 600, 0.0),
    "body":      (13, 400, 0.0),
    "small":     (12, 400, 0.0),
    "micro":     (11, 500, 0.02),
}

#: The one printed face. Used only on the dial, the way a faceplate's legends are
#: silkscreened; everything the user reads to work stays in the UI face.
DIAL_FONT_FILE: Final[str] = "Michroma-Regular.ttf"
DIAL_FONT_FAMILY: Final[str] = "Michroma"


def ui_font_stack() -> list:
    """Platform-appropriate UI faces, best first."""
    import sys

    if sys.platform == "win32":
        return ["Segoe UI Variable Text", "Segoe UI", "Inter"]
    if sys.platform == "darwin":
        return ["SF Pro Text", "Helvetica Neue", "Inter"]
    return ["Inter", "Cantarell", "DejaVu Sans"]


def mono_font_stack() -> list:
    """Monospace faces for timecodes and numeric readouts.

    Tabular figures are not optional here: a proportional timecode shifts
    horizontally on every frame during playback, which reads as a rendering bug.
    """
    import sys

    if sys.platform == "win32":
        return ["Cascadia Mono", "Consolas", "JetBrains Mono"]
    if sys.platform == "darwin":
        return ["SF Mono", "Menlo", "JetBrains Mono"]
    return ["JetBrains Mono", "DejaVu Sans Mono", "monospace"]


# --------------------------------------------------------------------- motion

#: Product register: 150-250ms. Users are in a task, not watching a show.
DURATION: Final[Dict[str, int]] = {
    "instant": 90,
    "fast": 150,
    "base": 200,
    "slow": 250,
    "needle": 220,
}

#: ease-out-quart, as Qt easing curve names are limited.
EASE_OUT_QUART = (0.25, 1.0, 0.5, 1.0)
