---
name: audix
description: A hi-fi receiver at night. One lit tuning dial on a dark bronze faceplate, with content behind recessed glass.
colors:
  shade: "#040303"
  well: "#0d0b08"
  surface: "#1e1813"
  bg: "#2b241c"
  surface_2: "#393027"
  surface_3: "#453b31"
  border: "#564b41"
  border_hi: "#76695d"
  ink: "#f1eee6"
  muted: "#c3bdb1"
  faint: "#b0a89b"
  glass: "#e9d4a3"
  glass_edge: "#c9ad7a"
  glass_ink: "#312317"
  glass_soft: "#5f4c38"
  needle: "#e02e1e"
  primary: "#eecb7d"
  primary_hi: "#f6e2aa"
  primary_dim: "#6f5a35"
  accent: "#ed4c3a"
  success: "#6ed889"
  warning: "#f19a4b"
  wave_peak: "#907238"
  wave_rms: "#edcd83"
typography:
  display:
    fontFamily: "Segoe UI Variable Text, Segoe UI, Inter"
    fontSize: "22px"
    fontWeight: 600
  h1:
    fontFamily: "Segoe UI Variable Text, Segoe UI, Inter"
    fontSize: "18px"
    fontWeight: 600
  h2:
    fontFamily: "Segoe UI Variable Text, Segoe UI, Inter"
    fontSize: "15px"
    fontWeight: 600
  body:
    fontFamily: "Segoe UI Variable Text, Segoe UI, Inter"
    fontSize: "13px"
    fontWeight: 400
  row-title:
    fontFamily: "Segoe UI Variable Text, Segoe UI, Inter"
    fontSize: "13px"
    fontWeight: 600
  small:
    fontFamily: "Segoe UI Variable Text, Segoe UI, Inter"
    fontSize: "12px"
    fontWeight: 400
  micro:
    fontFamily: "Segoe UI Variable Text, Segoe UI, Inter"
    fontSize: "11px"
    fontWeight: 500
  figures:
    fontFamily: "Cascadia Mono, Consolas, JetBrains Mono"
    fontSize: "12px"
    fontWeight: 400
  dial-legend:
    fontFamily: "Michroma"
    fontSize: "11px"
    fontWeight: 400
  wordmark:
    fontFamily: "Michroma"
    fontSize: "15px"
    fontWeight: 400
rounded:
  well: "1px"
  tick: "2px"
  control: "3px"
  panel: "4px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  base: "16px"
  lg: "20px"
  xl: "24px"
  2xl: "32px"
components:
  key:
    backgroundColor: "{colors.surface_2}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "7px 14px"
  key-hover:
    backgroundColor: "{colors.surface_3}"
    textColor: "{colors.ink}"
  key-pressed:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
  key-disabled:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.faint}"
  key-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.well}"
    rounded: "{rounded.control}"
    padding: "7px 14px"
  key-primary-hover:
    backgroundColor: "{colors.primary_hi}"
    textColor: "{colors.well}"
  key-danger:
    textColor: "{colors.muted}"
    rounded: "{rounded.control}"
    padding: "7px 14px"
  key-danger-hover:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.well}"
  key-ghost:
    textColor: "{colors.muted}"
    rounded: "{rounded.control}"
    padding: "6px 10px"
  key-ghost-hover:
    backgroundColor: "{colors.surface_3}"
    textColor: "{colors.ink}"
  key-tool:
    backgroundColor: "{colors.surface_2}"
    textColor: "{colors.ink}"
    typography: "{typography.small}"
    rounded: "{rounded.control}"
    padding: "6px 11px"
  key-tool-checked:
    textColor: "{colors.primary}"
  key-selector:
    textColor: "{colors.muted}"
    padding: "6px 12px"
  key-selector-checked:
    textColor: "{colors.ink}"
  field:
    backgroundColor: "{colors.well}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "7px 10px"
  field-large:
    backgroundColor: "{colors.well}"
    textColor: "{colors.ink}"
    typography: "{typography.h2}"
    rounded: "{rounded.control}"
    padding: "10px 12px"
  well:
    backgroundColor: "{colors.well}"
    rounded: "{rounded.well}"
  strip:
    backgroundColor: "{colors.surface}"
  dial-glass:
    backgroundColor: "{colors.glass}"
    textColor: "{colors.glass_ink}"
    typography: "{typography.dial-legend}"
    rounded: "{rounded.control}"
    height: "58px"
  dial-badge:
    backgroundColor: "{colors.glass_ink}"
    textColor: "{colors.glass}"
    rounded: "{rounded.tick}"
    height: "16px"
  toast:
    backgroundColor: "{colors.surface_3}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
    width: "380px"
  inspector:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    width: "320px"
  tick-box:
    backgroundColor: "{colors.well}"
    rounded: "{rounded.control}"
    size: "16px"
  tick-box-checked:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.well}"
    rounded: "{rounded.control}"
    size: "16px"
---

# Design System: audix

## Overview

**Creative North Star: "The Receiver at Night"**

audix is a receiver you tune, not a dashboard you read. A 76px dial runs across the top of the window, and its lit glass is the brightest field on screen. Everything else is a dark anodised bronze faceplate, with content behind it in smoked-glass wells. Controls live on the plate. Work lives behind it.

The interface is dense and quiet, because the people using it are in a task, often in a dark room with headphones on. Rows carry their whole story in fixed columns: a lamp and a word for state, a tick ladder for progress, tabular figures for size, speed, and time left. Nothing celebrates. A changed row stays lit until it has been seen, and a failure is never buried under a busy count.

The system refuses the sidebar-plus-near-black-cards download manager, including audix's own previous look. It also refuses the literal costume of its own metaphor: no wood photos, no screws, no faux brushed metal. The bronze is flat tone, and the dial is built only from light, printed ink, and one red needle.

Motion has one grammar: lamps and ladders change state, and the needle glides to the chosen station (ease-out-quart, 220ms; instant under the reduced-motion setting). Live readouts move because the signal does. Nothing moves for decoration.

**Key Characteristics:**
- One lit field: the dial glass, brighter than every other surface.
- An inverted tonal stack: the plate is lighter than the wells set into it.
- Rectilinear keys that catch light on the top edge.
- Every state is a lamp plus a word; progress is a tick ladder.
- Columns never move; only their contents change.
- Tabular figures for every number that updates.

## Colors

A warm, restrained bronze ramp at hue 66 to 70 with one tungsten voice, plus a red that is either a location (the needle) or bad news (failure, destruction, clipping). The bronze stays below chroma 0.03, so tungsten, green, and red carry all the meaning.

### Primary
- **Tungsten** (#eecb7d / oklch(0.855 0.105 86)): lit keys, ticked boxes, focus edges, running lamps, ladders, chosen filters, text selection. 9.83:1 on the plate, 12.61:1 on a well.
- **Tungsten Hot** (#f6e2aa / oklch(0.915 0.075 90)): hover on a lit key, top highlight of a lit key, hover on a fader cap.
- **Tungsten Dim** (#6f5a35 / oklch(0.480 0.060 80)): a ticked box that is disabled, and splitter hover. Tungsten that is off.

### Secondary
- **Dial Glass** (#e9d4a3 / oklch(0.875 0.068 88)): the lit field. Its lightness (L 0.875) is held above Tungsten (L 0.855) on purpose, so the dial stays the brightest field.
- **Dial Falloff** (#c9ad7a / oklch(0.760 0.075 82)): the backlight fading at each end of the glass, over the outer 14%.
- **Printed Ink** (#312317 / oklch(0.270 0.030 65)): every station legend, scale numeral, and station mark on the glass; also the badge plate. 10.38:1 on glass.
- **Printed Scale** (#5f4c38 / oklch(0.430 0.040 68)): the fine ticks of the scale. 5.60:1 on glass, 3.79:1 on the falloff.

### Tertiary
- **Needle Red** (#e02e1e / oklch(0.590 0.215 30)): the needle and nothing else. 3.13:1 on glass, 2.12:1 on the falloff.
- **Failure Red** (#ed4c3a / oklch(0.640 0.200 30)): failed lamps and messages, destructive hover, clipping, and the hot top of the level meter. 4.16:1 on the plate, 5.33:1 on a well.
- **Finished Green** (#6ed889 / oklch(0.800 0.150 150)): finished lamps and ladders, "Already downloaded". 8.69:1 on the plate, 11.14:1 on a well.
- **Paused Amber** (#f19a4b / oklch(0.760 0.140 60)): paused lamps and the near-clipping peak readout. 6.90:1 on the plate, 8.86:1 on a well. It sits only 1.42:1 from Tungsten, so it is never asked to carry state by hue alone.
- **Waveform Envelope** (#907238 / oklch(0.570 0.085 82)): min/max envelope, the quiet zone of the level meter. 4.38:1 on a well.
- **Waveform Body** (#edcd83 / oklch(0.860 0.100 87)): RMS body drawn over the envelope. 12.83:1 on a well, 2.93:1 against the envelope.

### Neutral

Darkest to lightest. Figures are contrast against the plate.

- **Shadow Edge** (#040303 / oklch(0.100 0.004 70)), 1.34:1: the top edge of a well, where it falls into shadow.
- **Well Glass** (#0d0b08 / oklch(0.150 0.008 70)), 1.28:1: recessed windows, fields, lists, the waveform canvas, and the dark ink on every fill.
- **Lower Plate** (#1e1813 / oklch(0.215 0.014 68)), 1.14:1: strips along the top and bottom of a page, the inspector, the editor's tool column, row hover.
- **Faceplate** (#2b241c / oklch(0.265 0.018 66)), 1.00:1: the plate itself, where controls sit.
- **Key** (#393027 / oklch(0.315 0.020 66)), 1.18:1: keys and selectors at rest, the selected row.
- **Key Hover** (#453b31 / oklch(0.360 0.022 66)), 1.41:1: hover on a key, toasts, tooltips.
- **Edge** (#564b41 / oklch(0.420 0.022 66)), 1.81:1: dividers, strip edges, unlit ladder ticks.
- **Edge Light** (#76695d / oklch(0.530 0.024 66)), 2.89:1: field outlines, key top highlight, the lower lip of a well, resting row actions.
- **Ink** (#f1eee6 / oklch(0.950 0.012 90)), 13.26:1: body text and titles. 17.01:1 on a well, 9.43:1 on Key Hover.
- **Muted** (#c3bdb1 / oklch(0.800 0.018 85)), 8.21:1: secondary text and figures. 10.53:1 on a well, 5.84:1 on Key Hover.
- **Faint** (#b0a89b / oklch(0.735 0.020 82)), 6.53:1: captions, placeholders, disabled labels. 8.37:1 on a well, and 4.64:1 on Key Hover, its hardest case.

### Named Rules

**The Tungsten Rule.** Tungsten means lit, and lit means it will act now. A disabled lit key goes dark, because it will not act. Never use tungsten as decoration.

**The Inverted Plate Rule.** The plate is deliberately not the darkest surface. Controls sit on it at L 0.265, and content sits behind it in wells at L 0.150. This inverts the usual lighter-cards-on-dark layout and it must not be flipped back.

**The Three Lamps Rule.** Green lamp means finished, red means failure, tungsten means working. A lit lamp is filled; an unlit lamp (Waiting, Paused, Cancelled) is an outline, and every lamp stands beside a word.

**The One Red Marker Rule.** The needle says where you are, and only the needle uses Needle Red. Failure Red is a separate token with a separate meaning.

**The Dark Ink Rule.** Every fill in this palette takes dark ink, including destructive red. Measured dark against white: Tungsten 12.61:1 to 1.56:1, Finished Green 11.14:1 to 1.77:1, Paused Amber 8.86:1 to 2.22:1, Failure Red 5.33:1 to 3.69:1. The older rule that destructive takes white no longer applies.

### Measured Constraints

- Stacked planes are separated by their edges more than by luminance. Neighbouring surfaces measure 1.12:1 to 1.19:1 (Well Glass to Lower Plate 1.12:1, Lower Plate to Faceplate 1.14:1, Faceplate to Key 1.18:1, Key to Key Hover 1.19:1). Edges do the work: Edge on a well 2.32:1, Edge on Lower Plate 2.06:1, Edge Light on a well 3.71:1, Edge Light on the plate 2.89:1.
- A field outlines with Edge Light rather than Edge, which holds 3.71:1 against its dark fill instead of 2.32:1.
- A focus edge is Tungsten: 12.61:1 on a well, 9.83:1 on the plate.

### Verification

`.venv/Scripts/python.exe scripts/verify_palette.py -v` recomputes every number in this file from the OKLCH source values and exits non-zero on a regression: contrast, sRGB gamut, surface separation, edges, the dial's ink and needle, fill ink, and the rule that the dial is the brightest field. The OKLCH values in the verifier are the source; the hex values in `audix/ui/tokens.py` are generated from them. Change a color there, regenerate, then update this file, so the numbers here cannot drift.

## Typography

**UI Font:** Segoe UI Variable Text, then Segoe UI, then Inter on Windows; SF Pro Text on macOS; Inter on Linux.
**Label/Mono Font:** Cascadia Mono, then Consolas, then JetBrains Mono on Windows; SF Mono on macOS; JetBrains Mono on Linux.
**Printed Face:** Michroma, bundled at `audix/assets/fonts/Michroma-Regular.ttf`, falling back to the UI face if it is missing.

**Character:** A plain working face for everything a person reads to get work done, a fixed-pitch face for every figure, and one wide squared face that behaves like silkscreen on the hardware.

### Hierarchy

The scale is fixed at a ratio of about 1.16 and is not fluid. A heading that shrinks inside a panel looks worse, not better.

- **Display** (600, 22px): the editor's workspace title.
- **H1** (600, 18px): empty-state and dialog headings.
- **H2** (600, 15px): page summaries, the inspector's title, the Browse dock title.
- **Body** (400, 13px): default UI. Keys use weight 500, lit keys 600.
- **Row Title** (600, 13px): the title line of every list row. Unticked rows fall back to Muted.
- **Small** (400, 12px): subtitles, hints, captions, inspector values. State words use weight 500.
- **Micro** (500, 11px): column headers, signal-path stages, editor field captions.
- **Figures** (400, 12px mono): sizes, speeds, durations, percentages. The dial's live speed is 13px at 600; the timecodes follow the same face. Dial badges are 11px at 600, and scale numerals are 10px at 500.
- **Dial Legend** (400, 11px Michroma): station names.
- **Wordmark** (400, 15px Michroma): the name beside the mark.

### Named Rules

**The Silkscreen Rule.** Michroma appears only on the dial and the wordmark. Everything a person reads to work stays in the system UI face.

**The Still Figures Rule.** Any number that updates is set in the mono face, so a changing digit never shifts what is beside it.

**The Sentence Case Rule.** Section titles and captions are sentence case. There are no tracked-uppercase labels above groups.

## Layout

The window opens at 1320x860 and goes no smaller than 1040x680. The dial spans the full width at 76px: the wordmark on the left, the 58px glass taking all remaining width, and a 150px signal meter on the right, 20px apart, inside 16px side margins.

Every page below it is a plate with the same order: controls on the plate, content in a well, and the page's main action fixed in a strip. Page margins are 16px at the sides and 12px above and below. The spacing scale has a 4px base (4, 8, 12, 16, 20, 24, 32), and rhythm comes from varying it: 8px between keys, 12px between bands, 24px and 32px inside a well page.

- **Queue:** link field and keys on the plate, then selection controls, the ticked list in a well, and a bottom strip with Format, Quality, Save to, and Run on the left and the two download keys at the far right.
- **Downloads:** summary and an overall ladder, filters and bulk controls, then the column list in a well. The list ranks running, paused, waiting, failed, finished.
- **Browse:** a top strip with navigation and address, the page edge to edge, and a dock strip naming what the page shows, with its actions at the right in one fixed place.
- **Edit:** the waveform takes every pixel not claimed by a control, beside a 330px tool column on Lower Plate.
- **Settings:** one well with 32px sides and 24px ends. Each section has a 210px title column and controls capped at 620px, with every field label 96px wide so all fields start at one edge.

Rows are fixed at 60px in Downloads, and 58px for tracks, 46px for playlist groups, and 54px for pending links in the Queue. Thumbnails are 16:9 at 64x36 and 72x40.

Downloads adapts by subtraction. Below 900px of row width it gives up speed and time left, below 760px it gives up size, and below 1180px of page width the control row drops its parallelism selector.

### Named Rules

**The Split-Flap Rule.** Columns never move, only their contents. A number changing, or a panel opening, leaves every visible column where it was.

**The Floating Inspector Rule.** The inspector floats over the right of the list rather than squeezing it. A column it would cut through is omitted, never shown as half a figure.

**The Fixed Actions Rule.** The actions for the current item stay in one fixed place: pinned at the foot of the inspector, and in the strip along the bottom of a page.

## Elevation & Depth

Depth comes from recess first. The world is lit from above, so a surface reads through which edge catches light and which falls into shadow. Inside the window, two surfaces float and take a soft ambient shadow; nothing else does. Raised controls use edges alone.

A well reads as recessed through three things working together: a 2px Shadow Edge along the top, a soft shade cast 10px down onto the glass from the top, and a lighter 1px lower lip in Edge Light. Its sides are Lower Plate, barely there, and its corner radius is 1px.

### Shadow Vocabulary
- **Well shade** (linear gradient, `rgba(0, 0, 0, 0.59)` to transparent over 10px): the shadow the plate casts into every well. It passes all clicks through.
- **Inspector** (`box-shadow: -6px 0 26px rgba(0, 0, 0, 0.59)`): the panel floating over the right of a list.
- **Toast** (`box-shadow: 0 6px 24px rgba(0, 0, 0, 0.47)`): notes in the corner of the window.
- **Page keys** (`box-shadow: 0 4px 14px rgba(0, 0, 0, 0.45)`): the keys audix floats over thumbnails on a web page.
- **Dial spill** (radial gradient of Tungsten at alpha 58, then 30, then 0): the lamp behind the glass leaking onto the plate beneath it. This is what makes the dial a lit object rather than a pale strip.

### Named Rules

**The Recess Rule.** A well must never read as a dark card. It keeps all three cues and almost no corner radius; drop any one of them and it floats forward.

**The Light From Above Rule.** A raised key has a light top edge and a dark bottom edge. Pressed, the two swap and the key drops to Lower Plate.

## Shapes

Hardware is rectilinear. Wells take a 1px ease, keys and fields 3px, floating panels 4px, and small parts such as dial badges, fader caps, and scrollbar thumbs 2px. Lamps and radio buttons are the only circles. Filter selectors and thumbnails are square-cornered, and a thumbnail takes a 1px dark hairline so it sits in its frame. Everything else is a straight edge or a tick.

Icons are one drawn set on a 24-unit grid with a single 1.75 stroke, tinted per state. They are never a font or a platform glyph, and in-page keys carry the same shapes as inline SVG.

## Components

### Buttons
Rectilinear keys, tactile rather than flat, with every state told through their edges.

- **Shape:** gently eased corners (3px), 1px edge.
- **Key:** Key fill with Ink text, weight 500, padding 7px 14px. Top edge Edge Light, sides Edge, bottom edge Lower Plate.
- **Lit key:** Tungsten fill, dark ink, weight 600, top edge Tungsten Hot. It is the one key that will act now, and it sits at the far right of its strip. Hover goes to Tungsten Hot; focus is an Ink edge, since a Tungsten edge would vanish.
- **Destructive:** a transparent outline in Edge with Muted text until hovered, then a Failure Red fill with dark ink. It stands apart from constructive keys. In painted rows the same grammar is a dim icon that fills red on hover.
- **Ghost:** transparent, Muted text, padding 6px 10px, for quieter actions such as Invert and Undo.
- **Tool:** a compact 12px key for the editor and for a toast's one action. Checked, it takes a 14% Tungsten wash, a Tungsten edge, and Tungsten text.
- **Selector:** a filter with no box. It shows a 2px Tungsten bar beneath while chosen.
- **Hover / Focus:** hover lifts to Key Hover with a Muted edge. Focus is a Tungsten edge.
- **Disabled:** drops to the plate with Faint text, and carries its reason in a tooltip.

### Inputs / Fields
- **Style:** recessed like a well: Well Glass fill, 1px Edge Light outline, 3px corners, padding 7px 10px. The Queue's link field is the large size at 15px, padding 10px 12px.
- **Focus:** a Tungsten edge. Hover is a Muted edge.
- **Disabled:** Lower Plate fill, Edge outline, Faint text.
- **Combo selectors:** a selector is a key, not a field: raised, with the key's edges and padding 6px 10px.

### Tick Boxes
A 16px box in Well Glass with an Edge Light outline, which fills Tungsten with a drawn dark tick when checked and a dash when partial. Because the mark is drawn, a checked box differs from an empty one by more than color.

### Cards / Containers

There are no cards. Content sits in one of these.

- **Well:** the recessed window from Elevation & Depth. Lists sit directly in it, rows divided by a 1px Lower Plate rule.
- **Strip:** a lower section of the same plate in Lower Plate, with a 1px Edge along the side facing the page. It holds a page's main actions.
- **Section:** a printed 1px Edge rule above a title, never a box inside a box. Used in Settings and in the editor's tool column.
- **Notice:** a Key panel with an Edge outline and 3px corners, for an inline offer such as a link found on the clipboard.

### Navigation
The dial is the only navigation; see below. Stations are real buttons, so focus, tooltips, and screen readers all work. Alt+1 to Alt+5 tune them, and the numerals printed on the scale say which is which. Focus on the glass is a 1.5px dotted line in Printed Ink. Hover on a station is a Printed Ink wash at alpha 26. Tungsten is never used on the glass, where it would disappear.

### Tuning Dial
The signature component and the one lit object. The glass is a 58px strip with a horizontal backlight falloff toward each end and a Well Glass outline. The scale is printed 8px apart, with every fifth tick taller; each station has a 10px mark in Printed Ink with its numeral beside the mark, not on it, because the needle parks there.

- **Legends:** all legends print alike, in Printed Ink. The current station gets no highlight.
- **Needle:** a 2px Needle Red line with a small head and a faint shadow, gliding on a separate layer with ease-out-quart at 220ms, or instantly under the reduced-motion setting. It stops above the legend, so the current station stays readable.
- **Badges:** a Printed Ink plate at 16px high with a Dial Glass figure. On Downloads the count says how much is running or waiting, and a separate lamp says something changed: green, or red if any of those changes was a failure. A busy count cannot hide a failure.
- **Signal meter:** a tick ladder for combined speed on a logarithmic scale, the live speed, and a caption. Clicking it tunes to Downloads.

### Lamps
An 8px circle at the standard size, 7px inside dense places such as badges. Lit is filled; unlit is a 1.5px outline, so state survives without color. A lamp always stands beside a word.

### Tick Ladders
Progress is a row of 2px ticks with a 2px gap, filling left to right. The grain stays fixed at any width instead of stretching. Unlit ticks are Edge; lit ticks take the state color. Work of unknown length, such as reading a link, runs a short chasing group of ticks instead.

### List Rows
Queue rows: tick box, thumbnail, title with subtitle, duration, then Download and Remove icon actions.

Downloads rows use fixed columns: lamp and word, thumbnail, title with subtitle, ladder, percent, size, speed, time left, then up to three 30px icon actions.

In both lists, actions rest in Edge Light and rise to Muted when the row is approached, so rows stay calm. A hovered row is Lower Plate, and focus is a 1px Tungsten outline. A selected Downloads row is Key.

A row that changed while you were elsewhere keeps a wash of its state color at alpha 26 until you have come to Downloads and seen it.

### Inspector
A 320px Lower Plate panel floating over the right of the list: lamp and word, a 136px cover, title, a signal path of lamps through Prepare, Download, Convert, and Tag with a time under each finished stage, and a two-column table of figures. Actions are pinned in a strip at its foot.

### Toasts
A 380px note, with a lamp, a line of text, at most one action, and a dismiss key. It stacks bottom right above the page strip, four at most, and never vanishes while the pointer is on it.

### Editor Instruments
- **Waveform:** two-tone on Well Glass: a Waveform Envelope with a Waveform Body over it, which keeps quiet passages legible. Selection is a Tungsten wash at alpha 38 with 1px Tungsten edges and 4x10px tabs. The playhead is a 1px Ink line with a grab handle in the ruler.
- **Sliders:** deliberately unlit. They are bipolar, so a lit track would read half on at zero. An Ink fader cap (8x16px) on a 4px Well Glass slot is the reading, and it warms to Tungsten Hot on hover.
- **Level meter:** stays in the tungsten grammar with 22 segments: Waveform Envelope below -18 dBFS, Tungsten up to -3, and red only when hot, with an Ink peak-hold marker. The numeric readout beside it carries the same information.

### Page Keys
A small bar audix floats over a web thumbnail: Lower Plate, an Edge Light outline, 4px corners, 26px keys with 3px corners, a lit Download and a Key Hover Queue. They reuse the palette, so they read as part of the receiver on a page audix does not own.

## Do's and Don'ts

### Do:
- **Do** keep the dial glass the brightest field; Dial Glass stays above Tungsten in lightness.
- **Do** put controls on the plate and content in a well.
- **Do** build each well from the 2px top Shadow Edge, the 10px cast shade, and the Edge Light lower lip, at a 1px radius.
- **Do** pair every state with a lamp and a word.
- **Do** use the 2px-tick ladder for item progress, in the state's color.
- **Do** set every changing number in the mono face.
- **Do** keep a changed row lit until it has been seen, and keep the count and the change lamp apart on the badge.
- **Do** take dark ink on every fill, including destructive red.
- **Do** keep the current item's actions in one fixed place.
- **Do** leave out a column an overlay would cut through.
- **Do** run `scripts/verify_palette.py -v` after any color change and copy its numbers here.

### Don't:
- **Don't** use wood photos, screws, or faux brushed metal.
- **Don't** return to the sidebar with near-black cards, or to audix's earlier near-black-and-cobalt look.
- **Don't** make the plate the darkest surface, or let a well read as a raised dark card.
- **Don't** light a second field to compete with the dial.
- **Don't** use tungsten as decoration; it is reserved for what is lit.
- **Don't** highlight the current legend, or run the needle through it; the needle alone says where you are.
- **Don't** use Needle Red anywhere but the needle.
- **Don't** show white text on a fill.
- **Don't** fill a destructive key before it is hovered.
- **Don't** light a slider track.
- **Don't** set Michroma outside the dial and the wordmark.
- **Don't** let any panel squeeze or shift a column.
- **Don't** let a busy count stand in for a failure.
- **Don't** add motion beyond the needle, lamps, ladders, and live readouts.
