"""Design tokens: the single source of truth for color, spacing, and type.

Every hex value here is derived from an OKLCH source and verified by
``scripts/verify_palette.py``, which fails on any contrast or gamut regression.
Do not hand-edit a hex value; change the OKLCH in the verifier and regenerate.

The theme rejects two category reflexes on purpose (see DESIGN.md): the
charcoal-gray DAW look every audio tool shares, and the terminal-amber CRT look
audix itself used to have. The ground is a pure neutral near-black at chroma
exactly 0, and the brand color is a luminous cobalt reserved for audio.
"""
from __future__ import annotations

from typing import Dict, Final

# ---------------------------------------------------------------------- color

#: Verified palette. Contrast ratios in comments are against ``bg``.
COLORS: Final[Dict[str, str]] = {
    # Neutral ramp - chroma exactly 0, deliberately untinted.
    "bg":          "#030303",   # ground
    "surface":     "#141414",   # panels, rail
    "surface_2":   "#202020",   # inputs, raised controls
    "surface_3":   "#2e2e2e",   # hover
    "border":      "#353535",   # panel edges          1.69:1 on bg
    "border_hi":   "#4d4d4d",   # input outlines       1.91:1 on surface_2

    # Text
    "ink":         "#eff2f5",   # body                18.35:1
    "muted":       "#a0a5a9",   # secondary            8.31:1
    "faint":       "#888d90",   # placeholder          6.13:1 / 4.83:1 on input

    # Brand - cobalt means audio and action
    "primary":     "#4ac5ff",   #                     10.53:1
    "primary_hi":  "#a1deff",   # hover
    "primary_dim": "#005778",   # disabled fill

    # Semantic - vermillion means destructive or clipping, nothing else
    "accent":      "#cc272e",   #                      3.83:1
    "success":     "#5fd37f",   #                     10.93:1
    "warning":     "#f0bb3b",   #                     11.68:1

    # Waveform two-tone
    "wave_peak":   "#157eaa",   # min/max envelope     4.53:1
    "wave_rms":    "#62cbff",   # RMS body            11.26:1
}

#: Which text color each filled control must use. Measured, not guessed:
#: white on the cobalt primary is 1.95:1, which is unreadable.
FILL_TEXT: Final[Dict[str, str]] = {
    "primary": COLORS["bg"],
    "success": COLORS["bg"],
    "warning": COLORS["bg"],
    "accent":  "#ffffff",
}

#: Task state -> color, shared by the queue and the editor.
STATE_COLORS: Final[Dict[str, str]] = {
    "Pending":     COLORS["faint"],
    "Resolving":   COLORS["primary"],
    "Downloading": COLORS["primary"],
    "Converting":  COLORS["primary"],
    "Tagging":     COLORS["primary"],
    "Editing":     COLORS["primary"],
    "Completed":   COLORS["success"],
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

RADIUS: Final[Dict[str, int]] = {
    "control": 6,
    "panel": 10,
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
}

#: ease-out-quart, as Qt easing curve names are limited.
EASE_OUT_QUART = (0.25, 1.0, 0.5, 1.0)
