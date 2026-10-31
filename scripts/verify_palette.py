#!/usr/bin/env python3
"""Verify the audix palette against DESIGN.md's stated requirements.

Recomputes every contrast number from the OKLCH source values and exits non-zero
on any regression. Run it after touching `audix/ui/tokens.py`.

Checks performed:
  * sRGB gamut validity (a chroma the display cannot reproduce renders clipped,
    so the token would silently differ from its spec)
  * WCAG contrast for text, placeholders, and graphical elements
  * Adjacent surface levels are actually distinguishable from each other
  * Printed ink and the needle on the lit dial
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
    # Bronze ramp, darkest to lightest. The faceplate is deliberately not the
    # darkest thing on screen: controls sit on the plate and content sits behind
    # it in darker recessed windows, which is what makes the layout read as one
    # physical object rather than a stack of cards.
    "shade":       (0.100, 0.004, 70),    # the edge of a well that falls into shadow
    "well":        (0.150, 0.008, 70),    # recessed window glass
    "surface":     (0.215, 0.014, 68),    # lower plate, transport strip
    "bg":          (0.265, 0.018, 66),    # faceplate
    "surface_2":   (0.315, 0.020, 66),    # keys, raised controls
    "surface_3":   (0.360, 0.022, 66),    # key hover
    "border":      (0.420, 0.022, 66),
    "border_hi":   (0.530, 0.024, 66),

    # Text, warmed to sit on bronze
    "ink":         (0.950, 0.012, 90),
    "muted":       (0.800, 0.018, 85),
    # Checked on the lightest surface it can land on, not just on the plate.
    "faint":       (0.735, 0.020, 82),

    # The dial: the one lit field in the interface
    "glass":       (0.875, 0.068, 88),
    "glass_edge":  (0.760, 0.075, 82),
    "glass_ink":   (0.270, 0.030, 65),
    "glass_soft":  (0.430, 0.040, 68),
    "needle":      (0.590, 0.215, 30),

    # Tungsten: lit means it will act now
    "primary":     (0.855, 0.105, 86),
    "primary_hi":  (0.915, 0.075, 90),
    "primary_dim": (0.480, 0.060, 80),

    # Semantic. Red means failure, destruction, or clipping, and the needle.
    "accent":      (0.640, 0.200, 30),
    "success":     (0.800, 0.150, 150),
    "warning":     (0.760, 0.140, 60),

    # Waveform
    "wave_peak":   (0.570, 0.085, 82),
    "wave_rms":    (0.860, 0.100, 87),
}

WHITE = (1.0, 0.0, 0)

#: Bronze ramp in order; each step must be visible against the one before it.
SURFACE_ORDER = ["well", "surface", "bg", "surface_2", "surface_3", "border", "border_hi"]

#: Minimum contrast for two stacked surfaces to read as separate planes.
#:
#: Deliberately low. WCAG contrast compresses hard this dark, so planes are told
#: apart by their edges as much as by their fill, which is why BORDER_VISIBILITY
#: below is the check that actually guarantees legibility.
SURFACE_SEPARATION = 1.10

#: A panel edge must be clearly visible against both surfaces it divides.
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
    for surface in ("well", "surface", "bg", "surface_2", "surface_3"):
        report.check(f"ink on {surface}",
                     contrast(resolved["ink"], resolved[surface]), 7.0)
        report.check(f"muted on {surface}",
                     contrast(resolved["muted"], resolved[surface]), 4.5)
        report.check(f"faint on {surface}",
                     contrast(resolved["faint"], resolved[surface]), 4.5)

    # -- surface separation --------------------------------------------------
    print("\nSURFACE SEPARATION (stacked planes must be distinguishable)")
    for lower, upper in zip(SURFACE_ORDER, SURFACE_ORDER[1:]):
        report.check(
            f"{lower} vs {upper}",
            contrast(resolved[lower], resolved[upper]),
            SURFACE_SEPARATION,
        )

    # Inputs are recessed into the plate, so they outline with border_hi; keys are
    # raised from it and use border. That split is a design rule, enforced here
    # rather than left to memory.
    print("\nEDGES (what actually separates planes this dark)")
    report.check("border on well (window frame)",
                 contrast(resolved["border"], resolved["well"]), BORDER_VISIBILITY)
    report.check("border on surface (strip edge)",
                 contrast(resolved["border"], resolved["surface"]), BORDER_VISIBILITY)
    report.check("border_hi on well (input outline)",
                 contrast(resolved["border_hi"], resolved["well"]), BORDER_VISIBILITY)
    report.check("border_hi on bg (key on plate)",
                 contrast(resolved["border_hi"], resolved["bg"]), BORDER_VISIBILITY)
    report.check("primary on well (focus ring)",
                 contrast(resolved["primary"], resolved["well"]), 3.0)
    report.check("primary on bg (focus ring)",
                 contrast(resolved["primary"], resolved["bg"]), 3.0)

    # -- the dial ------------------------------------------------------------
    print("\nTHE DIAL (printed ink on lit glass)")
    report.check("glass_ink on glass (current station)",
                 contrast(resolved["glass_ink"], resolved["glass"]), 7.0)
    report.check("glass_soft on glass (scale ticks)",
                 contrast(resolved["glass_soft"], resolved["glass"]), 4.5)
    report.check("glass_soft on glass_edge (dial ends)",
                 contrast(resolved["glass_soft"], resolved["glass_edge"]), 3.0)
    report.check("needle on glass", contrast(resolved["needle"], resolved["glass"]), 3.0)
    report.check("needle on glass_edge",
                 contrast(resolved["needle"], resolved["glass_edge"]), 2.0)

    # -- graphical -----------------------------------------------------------
    print("\nGRAPHICAL ELEMENTS (>= 3:1)")
    for name in ("primary", "accent", "success", "warning", "wave_peak", "wave_rms"):
        report.check(f"{name} on well", contrast(resolved[name], resolved["well"]), 3.0)
    for name in ("primary", "accent", "success", "warning"):
        report.check(f"{name} on bg", contrast(resolved[name], resolved["bg"]), 3.0)
    report.check("wave_rms vs wave_peak (two-tone)",
                 contrast(resolved["wave_rms"], resolved["wave_peak"]), 1.3)

    # -- text on fills -------------------------------------------------------
    print("\nTEXT ON COLOR FILLS (which text color each control must use)")
    for fill in ("primary", "accent", "success", "warning"):
        dark = contrast(resolved["well"], resolved[fill])
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
    report.check("primary vs warning distinct",
                 contrast(resolved["primary"], resolved["warning"]), 1.3)
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
        "faceplate is warm, restrained bronze",
        all(0.0 < resolved[n][1] <= 0.03 and 60 <= resolved[n][2] <= 75
            for n in SURFACE_ORDER),
        "chroma 0-0.03, hue 60-75",
    )
    report.assert_(
        "faceplate is not near-black",
        resolved["bg"][0] >= 0.20,
        f"L={resolved['bg'][0]:.3f}; rejects near-black plus one neon accent",
    )
    report.assert_(
        "the dial is the brightest field",
        resolved["glass"][0] > resolved["primary"][0],
        f"glass L={resolved['glass'][0]:.3f} > primary L={pL:.3f}",
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
