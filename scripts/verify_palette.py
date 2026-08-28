#!/usr/bin/env python3
"""Verify the audix palette against DESIGN.md's stated requirements.

Recomputes every contrast number from the OKLCH source values and exits non-zero
on any regression. Run it after touching `audix/ui/tokens.py`.

Checks performed:
  * sRGB gamut validity (a chroma the display cannot reproduce renders clipped,
    so the token would silently differ from its spec)
  * WCAG contrast for text, placeholders, and graphical elements
  * Adjacent surface levels are actually distinguishable from each other
  * The impeccable hard rules (chroma ceilings, primary/accent separation)
  * Which text color each filled control must use

Usage:  python scripts/verify_palette.py [-v]
"""
from __future__ import annotations

import math
import sys

# --------------------------------------------------------------- color science

def _oklch_to_oklab(L: float, C: float, h_deg: float):
    h = math.radians(h_deg)
    return L, C * math.cos(h), C * math.sin(h)


def _oklab_to_linear_srgb(L: float, a: float, b: float):
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    return (
        +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    )


def _linear_to_srgb(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def oklch_to_rgb(L: float, C: float, h: float):
    """Non-clamped sRGB floats. Values outside [0,1] mean out of gamut."""
    return tuple(_linear_to_srgb(c) for c in _oklab_to_linear_srgb(*_oklch_to_oklab(L, C, h)))


def in_gamut(L: float, C: float, h: float, tol: float = 0.002) -> bool:
    return all(-tol <= c <= 1 + tol for c in oklch_to_rgb(L, C, h))


def fit_chroma(L: float, C: float, h: float) -> float:
    """Largest chroma <= C that stays inside sRGB, floored to 3 decimals."""
    if in_gamut(L, C, h):
        return C
    lo, hi = 0.0, C
    for _ in range(40):
        mid = (lo + hi) / 2
        if in_gamut(L, mid, h):
            lo = mid
        else:
            hi = mid
    return math.floor(lo * 1000) / 1000


def to_hex(L: float, C: float, h: float) -> str:
    r, g, b = (max(0.0, min(1.0, c)) for c in oklch_to_rgb(L, C, h))
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def relative_luminance(L: float, C: float, h: float) -> float:
    lin = _oklab_to_linear_srgb(*_oklch_to_oklab(L, C, h))
    r, g, b = (max(0.0, min(1.0, c)) for c in lin)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(c1, c2) -> float:
    l1, l2 = relative_luminance(*c1), relative_luminance(*c2)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


# ------------------------------------------------------------------- the palette
# Source of truth. `audix/ui/tokens.py` is generated to match these values.
PALETTE = {
    # Neutral ramp. Steps are spaced so adjacent surfaces are actually visible
    # against each other; OKLCH lightness compresses hard at the dark end, so
    # evenly-spaced L values would collapse into an indistinguishable smear.
    "bg":          (0.100, 0.000, 0),
    "surface":     (0.190, 0.000, 0),
    "surface_2":   (0.245, 0.000, 0),
    "surface_3":   (0.300, 0.000, 0),
    "border":      (0.330, 0.000, 0),
    "border_hi":   (0.420, 0.000, 0),

    # Text
    "ink":         (0.960, 0.005, 233),
    "muted":       (0.720, 0.008, 233),
    # 0.600 measured 4.12:1 as placeholder text on surface_2 (an input) - an AA
    # fail at the exact place placeholders live. Raised until it clears on the
    # lightest surface it can sit on.
    "faint":       (0.640, 0.008, 233),

    # Brand
    "primary":     (0.780, 0.135, 233),
    "primary_hi":  (0.870, 0.077, 233),
    "primary_dim": (0.430, 0.089, 233),

    # Semantic
    "accent":      (0.550, 0.200, 25),
    "success":     (0.780, 0.160, 150),
    "warning":     (0.820, 0.150, 85),

    # Waveform
    "wave_peak":   (0.560, 0.110, 233),
    "wave_rms":    (0.800, 0.122, 233),
}

WHITE = (1.0, 0.0, 0)

#: Neutral ramp in order; each step must be visible against the one before it.
SURFACE_ORDER = ["bg", "surface", "surface_2", "surface_3", "border", "border_hi"]

#: Minimum contrast for two stacked surfaces to read as separate planes.
#
#: Deliberately 1.10, not something higher. WCAG contrast compresses hard at
#: near-black luminance: forcing 1.18:1 between consecutive dark surfaces would
#: push the input background to roughly #464646, which is charcoal - precisely
#: the DAW look DESIGN.md rejects. Real dark interfaces (Vercel, Linear) run
#: 1.05-1.15 between planes and rely on a *border* to draw the edge, which is
#: why BORDER_VISIBILITY below is the check that actually guarantees legibility.
SURFACE_SEPARATION = 1.10

#: A panel edge must be clearly visible against both the ground and the panel.
#: This is what carries plane separation in a near-black UI.
BORDER_VISIBILITY = 1.5


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.notes: list[str] = []

    def check(self, label: str, value: float, minimum: float) -> bool:
        ok = value >= minimum
        print(f"  [{'PASS' if ok else 'FAIL'}] {label:<46} {value:>6.2f}:1  (>= {minimum})")
        if not ok:
            self.failures.append(f"{label} ({value:.2f}:1, needs {minimum}:1)")
        return ok

    def assert_(self, label: str, ok: bool, detail: str = "") -> bool:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label:<46} {detail}")
        if not ok:
            self.failures.append(label)
        return ok


def main(argv: list[str]) -> int:
    verbose = "-v" in argv or "--verbose" in argv
    report = Report()
    resolved: dict = {}

    print("=" * 74)
    print(" audix palette verification")
    print("=" * 74)

    # -- gamut ---------------------------------------------------------------
    print("\nTOKENS")
    print(f"  {'token':<13} {'oklch':<24} {'hex':<9} {'vs bg':>8}")
    print("  " + "-" * 60)
    adjusted = []
    for name, (L, C, h) in PALETTE.items():
        fitted = fit_chroma(L, C, h)
        if abs(fitted - C) > 1e-9:
            adjusted.append((name, C, fitted))
        resolved[name] = (L, fitted, h)

    for name, spec in resolved.items():
        L, C, h = spec
        ratio = contrast(spec, resolved["bg"])
        print(f"  {name:<13} oklch({L:.3f} {C:.3f} {h:>3.0f}) {to_hex(*spec):<9} {ratio:>7.2f}:1")

    if adjusted:
        print("\n  Chroma fitted to sRGB gamut:")
        for name, was, now in adjusted:
            print(f"    {name:<13} {was:.3f} -> {now:.3f}")

    # -- text ----------------------------------------------------------------
    print("\nTEXT LEGIBILITY")
    report.check("ink on bg (body)", contrast(resolved["ink"], resolved["bg"]), 7.0)
    report.check("muted on bg (secondary)", contrast(resolved["muted"], resolved["bg"]), 4.5)
    report.check("faint on bg (placeholder)", contrast(resolved["faint"], resolved["bg"]), 4.5)
    report.check("ink on surface", contrast(resolved["ink"], resolved["surface"]), 7.0)
    report.check("muted on surface", contrast(resolved["muted"], resolved["surface"]), 4.5)
    report.check("faint on surface_2", contrast(resolved["faint"], resolved["surface_2"]), 4.5)
    report.check("ink on surface_3 (hover row)", contrast(resolved["ink"], resolved["surface_3"]), 7.0)

    # -- surface separation --------------------------------------------------
    print("\nSURFACE SEPARATION (stacked planes must be distinguishable)")
    for lower, upper in zip(SURFACE_ORDER, SURFACE_ORDER[1:]):
        report.check(
            f"{lower} vs {upper}",
            contrast(resolved[lower], resolved[upper]),
            SURFACE_SEPARATION,
        )

    # `border` is not visible enough against surface_2 (1.33:1), so inputs -
    # which are filled with surface_2 - must outline with border_hi instead.
    # That split is a design rule, enforced here rather than left to memory.
    print("\nPANEL EDGES (what actually separates planes at near-black)")
    report.check("border on bg (panel on ground)",
                 contrast(resolved["border"], resolved["bg"]), BORDER_VISIBILITY)
    report.check("border on surface (nested panel)",
                 contrast(resolved["border"], resolved["surface"]), BORDER_VISIBILITY)
    report.check("border_hi on surface_2 (input outline)",
                 contrast(resolved["border_hi"], resolved["surface_2"]), BORDER_VISIBILITY)
    report.check("primary on surface_2 (focus ring)",
                 contrast(resolved["primary"], resolved["surface_2"]), 3.0)

    # -- graphical -----------------------------------------------------------
    print("\nGRAPHICAL ELEMENTS (>= 3:1)")
    for name in ("primary", "accent", "success", "warning", "wave_peak", "wave_rms"):
        report.check(f"{name} on bg", contrast(resolved[name], resolved["bg"]), 3.0)
    report.check("wave_rms vs wave_peak (two-tone)",
                 contrast(resolved["wave_rms"], resolved["wave_peak"]), 1.3)

    # -- text on fills -------------------------------------------------------
    print("\nTEXT ON COLOR FILLS (which text color each control must use)")
    for fill in ("primary", "accent", "success", "warning"):
        dark = contrast(resolved["bg"], resolved[fill])
        light = contrast(WHITE, resolved[fill])
        winner = "dark ink" if dark >= light else "white"
        best = max(dark, light)
        print(f"    {fill:<10} dark {dark:>5.2f}:1 | white {light:>5.2f}:1  -> use {winner}")
        report.check(f"{fill} fill readable with {winner}", best, 4.5)

    # -- hard rules ----------------------------------------------------------
    print("\nIMPECCABLE HARD RULES")
    pL, pC, _ = resolved["primary"]
    report.check("primary vs accent distinct",
                 contrast(resolved["primary"], resolved["accent"]), 1.7)
    report.assert_("primary chroma <= 0.23", pC <= 0.23, f"C={pC:.3f}")
    if pL > 0.78:
        report.assert_("primary L>0.78 implies chroma <= 0.18", pC <= 0.18, f"C={pC:.3f}")
    else:
        print(f"  [PASS] {'primary L <= 0.78 (fluorescent rule n/a)':<46} L={pL:.3f}")
    aL, aC, _ = resolved["accent"]
    report.assert_(
        "accent can hold text (C>=.10 | L>=.85 | L<=.30)",
        aC >= 0.10 or aL >= 0.85 or aL <= 0.30,
        f"C={aC:.3f} L={aL:.3f}",
    )
    report.assert_(
        "neutral ramp is untinted (chroma exactly 0)",
        all(resolved[n][1] == 0.0 for n in SURFACE_ORDER),
        "rejects the tinted-charcoal DAW look",
    )

    if verbose:
        print("\nPYTHON TOKENS")
        for name, spec in resolved.items():
            print(f'    "{name}": "{to_hex(*spec)}",')

    print("\n" + "=" * 74)
    if report.failures:
        print(f"FAILED ({len(report.failures)}):")
        for failure in report.failures:
            print(f"  - {failure}")
        print("=" * 74)
        return 1
    print("ALL PALETTE REQUIREMENTS PASS")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
