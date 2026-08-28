# Design

The visual system for audix. Every value here is verified, not asserted — the
contrast and gamut numbers come from `scripts/verify_palette.py`, which fails the
build if a token drifts out of spec.

## Theme

Dark, and dark for a stated reason: *1am, lights off, headphones on, scrubbing a
90-minute DJ set to find where track 3 starts.* The room is dark, so the interface
is dark and the waveform is the brightest object on screen.

Two rejected reflexes, recorded so they stay rejected:

- **Charcoal-gray DAW** (L 0.25–0.35 neutral gray, blue-green accents). This is what
  Ableton, Reaper, Audition, and Audacity all look like. It is the first thing anyone
  would guess from the category.
- **Terminal amber / green CRT.** The second-order reflex — the thing you reach for
  when avoiding the first — and where audix's own v1 landed.

audix instead uses a **pure neutral near-black** ground at `L 0.09, chroma exactly
0`. Measurably not DAW-charcoal, and it makes a saturated cobalt waveform read as
genuinely luminous rather than merely colored.

## Color

Strategy: **Restrained** (the product-register floor) with one exception — the
waveform canvas is **Committed**, where cobalt carries the surface. Everywhere else
the accent stays under 10% of the surface.

Anchor hue 233° derives from the impeccable brand seed (230°, within the ±10°
requirement).

```
--bg           oklch(0.100 0.000   0)   #030303   ground
--surface      oklch(0.190 0.000   0)   #141414   panels, rail
--surface-2    oklch(0.245 0.000   0)   #202020   inputs, raised
--surface-3    oklch(0.300 0.000   0)   #2e2e2e   hover
--border       oklch(0.330 0.000   0)   #353535   panel edges
--border-hi    oklch(0.420 0.000   0)   #4d4d4d   input outlines

--ink          oklch(0.960 0.005 233)   #eff2f5   body            18.35:1
--muted        oklch(0.720 0.008 233)   #a0a5a9   secondary        8.31:1
--faint        oklch(0.640 0.008 233)   #888d90   placeholder      6.13:1

--primary      oklch(0.780 0.135 233)   #4ac5ff   cobalt          10.53:1
--primary-hi   oklch(0.870 0.077 233)   #a1deff   hover
--primary-dim  oklch(0.430 0.089 233)   #005778   disabled fill

--accent       oklch(0.550 0.200  25)   #cc272e   clip/destructive 3.83:1
--success      oklch(0.780 0.160 150)   #5fd37f                  10.93:1
--warning      oklch(0.820 0.150  85)   #f0bb3b                  11.68:1

--wave-peak    oklch(0.560 0.110 233)   #157eaa   peak envelope    4.53:1
--wave-rms     oklch(0.800 0.122 233)   #62cbff   RMS body        11.26:1
```

**Role discipline.** Cobalt means *audio and action*: the waveform, the playhead,
primary buttons, focus rings, current selection. Vermillion means *destructive or
clipping* and nothing else — never a decorative red, never a generic "danger" tint on
an idle control. Warmth was demoted from identity to semantics deliberately; audix v1
used amber everywhere, which made "hot" unsayable.

**Four constraints that came out of measurement, not taste:**

1. **Primary buttons take dark text, not white.** White on `--primary` measures
   1.95:1 — unreadable. Dark ink on it measures 10.53:1. Same for `--success` and
   `--warning`. The reverse holds for `--accent`: white on it is 5.38:1, dark ink
   only 3.83:1, so destructive buttons take white.
2. **Inputs outline with `--border-hi`, panels with `--border`.** `--border` against
   `--surface-2` is only 1.33:1, so an input filled with `surface-2` would have an
   invisible edge. Panels on the ground are fine at 1.69:1.
3. **Panel separation is carried by the border, not by luminance.** Consecutive dark
   surfaces sit at 1.11–1.19:1, because forcing more would push inputs to ~`#464646`
   — charcoal, the exact look this theme rejects. This matches how Vercel and Linear
   build dark surfaces.
4. **`--faint` must clear 4.5:1 on `--surface-2`, not just on `--bg`.** At L 0.600 it
   passed on the ground (5.23:1) and failed inside an input (4.12:1) — which is the
   only place placeholder text actually appears. Raised to L 0.640.

Three tokens (`primary-hi`, `primary-dim`, `wave-rms`) had their requested chroma
reduced to fit sRGB; the fitted values are the ones above.

**Color is never the sole carrier.** Clipping shows a marker plus a readable dBFS
number, not redness alone.

## Typography

One family, per the product register. No display/body pairing — a tool does not need
a voice, it needs legibility at 13px.

- **UI:** `Segoe UI Variable` / `Segoe UI` (Windows), `SF Pro Text` (macOS), `Inter`
  (Linux), falling back to `system-ui`.
- **Numeric:** `Cascadia Mono` / `SF Mono` / `JetBrains Mono`, **tabular figures**,
  used for every timecode, dB value, LUFS reading, and duration. Non-negotiable: a
  proportional timecode jitters horizontally during playback, which reads as a bug.

Fixed rem-equivalent scale at ratio ~1.16 — not fluid. A clamp-sized heading that
shrinks inside a panel looks worse, not better.

```
display  22px / 600 / -0.02em    workspace title
h1       18px / 600 / -0.01em    panel heading
h2       15px / 600              group heading
body     13px / 400              default UI
small    12px / 400              secondary
micro    11px / 500 / 0.02em     axis labels, meter ticks
```

Section labels are sentence case. **No tracked-uppercase eyebrows** above every
group — that is the saturated AI scaffold, and v1 used it on all four settings
panels.

## Spacing & Layout

4px base unit; steps 4, 8, 12, 16, 20, 24, 32, 48, 64. Rhythm varies deliberately —
16px inside a control group, 24px between groups, 32px between regions.

**App shell:** a 56px icon rail (Browse · Get · Queue · Edit · Settings), then the
workspace. The rail replaces the v1 tab bar, which was already at four tabs and had
no room for a fifth destination or a transport bar.

**Editor workspace:** vertical stack — header (title, format, duration) / waveform
canvas (flex, minimum 220px) / time ruler / transport bar / tool panel (docked
right, 320px, collapsible). The waveform gets every pixel not claimed by a control.

Radii: 6px controls, 10px panels, 3px waveform selection. Never fully rounded except
on the playhead handle.

## Components

Every interactive control ships all seven states: default, hover, focus-visible,
active, disabled, loading, error. A disabled control **carries its reason in a
tooltip** — this is the Never-refuse-silently principle made concrete.

- **Buttons:** primary (cobalt fill, dark text), secondary (surface-2 fill, border),
  ghost (transparent), destructive (vermillion fill, white text). One shape, 6px
  radius, 32px standard height.
- **Waveform:** two-tone — a dark `--wave-peak` min/max envelope with a bright
  `--wave-rms` body drawn over it. This is what makes quiet passages legible; a
  single-tone peak-only waveform hides dynamics.
- **Selection:** cobalt wash at 18% alpha with full-opacity edge handles. Handles are
  8px wide with a 16px hit area.
- **Playhead:** 1px cobalt line, full canvas height, with a 12px grab handle in the
  ruler.
- **Meters:** segmented, green below −18 dBFS, amber −18 to −3, vermillion above −3,
  with a sticky peak-hold marker.
- **Empty states teach.** The editor with nothing loaded explains what it edits and
  offers the two ways in, rather than saying "no file".

## Motion

150–250ms, `ease-out-quart`. Motion conveys state only: panel collapse, selection
snap, meter falloff, progress. No orchestrated load sequences — the app loads into a
task.

The waveform playhead is the one continuous animation, driven by the audio clock at
60fps and decoupled from layout. Under `prefers-reduced-motion` (Qt: honoring the
platform setting) transitions become instant and the playhead updates at 10fps
without interpolation.

## Verification

`python scripts/verify_palette.py` recomputes every number in the Color section from
the OKLCH source values and exits non-zero on any regression: contrast below
threshold, chroma outside sRGB, or a primary/accent pair that has drifted together.
