# Product

## Register

product

## Platform

web

> Platform note: audix is a **desktop** application (PySide6/Qt on Windows, macOS,
> Linux). The taxonomy above has no `desktop` value; `web` is recorded because no
> mobile rulebook (HIG, Material 3) applies. Desktop conventions govern instead:
> menu bars, keyboard-first operation, resizable windows, native file dialogs.

## Users

Four audiences share one tool, so audix ships **profiles** rather than a single set
of defaults. Each profile presets loudness target, output format, and how much of
the editor is exposed on first open.

The **music collector / archivist** is the center of gravity. They rip albums, live
sets, and DJ mixes to build a tagged local library, and they care most about
lossless output, correct metadata, and splitting a 90-minute upload into real
tracks. The **casual listener** grabs a few songs for a phone or a car USB and wants
near-zero decisions — for them the editor must stay invisible until asked for. The
**podcaster / creator** pulls clips and reference audio, needing precise trimming,
speech-appropriate loudness, and fast export of a selection. The **DJ / producer**
sources tracks and samples, and cares about accurate cue points, lossless fidelity,
and independent pitch and speed control.

The shared context is a desk, headphones, and often a dark room at night. The job to
be done is the same in every case: *get clean, correctly labelled audio out of a
video platform and into a library.*

## Product Purpose

audix extracts audio from YouTube and turns it into finished library files —
converted, trimmed, leveled, tagged, and split. It exists because the two halves of
this job currently require two different tools: a downloader that produces a raw
file, and an audio editor that knows nothing about where that file came from.

Success is a user going from a pasted URL to a correctly tagged, correctly leveled
set of tracks without opening a second application, and without ever waiting on a
frozen window.

## Positioning

The only audio editor that already knows what it is editing — because it did the
download, it has the chapters, the artist, the album, and the artwork before the
waveform is even drawn.

## Brand Personality

Precise, unblocking, quietly technical. The voice states what happened and what to
do next, never scolds and never hides a failure behind a generic message. It has the
confidence of a well-built instrument: it does not decorate, it does not celebrate
routine success, and it never makes the user feel that they used it wrong.

Three words: **precise, candid, unobtrusive.**

## Anti-references

**Audacity** is the primary anti-reference, specifically its habit of refusing
actions without explanation — dragging a clip past another, pasting where there is
no "room", selecting multiple clips — the class of arbitrary modal blocks that
earned it the "UX nightmare" nickname its own 4.0 redesign is now unwinding. audix
must never answer an intent with a bare refusal.

Also rejected: the **charcoal-gray DAW** look shared by nearly every audio tool,
which is the first-order category reflex; the **terminal amber/green CRT** aesthetic,
which is the second-order reflex and where audix's own first version landed; and the
**generic dark SaaS dashboard** with hero metrics and identical card grids. Near-black
with one neon accent, where audix's second version landed, is rejected for the same
reason as the rest: the category arrives there by default.

## Design Principles

**A link means what it says.** A link that names a video gets that video, however it
was copied. Whatever list YouTube happened to be playing it from stays a separate,
explicit choice. Nothing ever expands into more than the user pointed at.

**Nothing starts until you choose.** Every link lands in the Queue as ticked rows, so
a 300-track playlist is a decision rather than an event. Download is one deliberate
press, and it can be all of them, some of them, or one.

**Show every item's whole story.** While a track runs, its stage, size, speed, and time
left are all on its row. Afterwards the inspector still knows which stream was fetched
and how long each stage took. A download never becomes a spinner with a percentage.

**Never refuse silently.** Any action audix will not perform must say why and offer
the next move. A disabled control carries the reason in its tooltip. This is the
direct inversion of the primary anti-reference.

**The source is sacred.** Edits are a non-destructive stack applied on export. The
originally downloaded audio is never overwritten in place, so any edit is reversible
and the user can never destroy the thing they waited to download.

**Preview before commit.** Every effect is audible before it is applied, during
playback, with an A/B bypass. This is the single capability Audacity lacks and
Ocenaudio is praised for.

**Metadata is a first-class input.** audix holds chapters, artist, album, year, and
artwork from the extraction step. The editor treats that as data to act on — chapter
markers become split points — not as fields to fill in afterward.

**Never block the window.** Waveform analysis, conversion, and export run on
workers with visible progress and a working cancel. A published wavesurfer.js report
measured a 90-minute file locking the UI for three minutes; that failure mode is
designed out, not tuned down.

## Accessibility & Inclusion

Keyboard-first: every editor action reachable without a mouse, using the shortcut
vocabulary users already carry from other editors (Space to play/stop, Ctrl+1/2/3 to
zoom in/normal/out, Ctrl+E to fit selection). The Queue is fully keyboard-driven too,
and Alt+1 to Alt+5 tune the dial; the numerals printed on it say which is which. Visible
focus on every control, including painted rows.

Body text and placeholder text both meet WCAG AA (≥4.5:1); large text and graphical
controls meet ≥3:1. Contrast is verified numerically against the tokens, not
eyeballed.

Color is never the only carrier of meaning — clipping is shown by a marker and a
readable dBFS number, not by redness alone — which keeps the interface usable with
deuteranopia and protanopia. All motion respects a reduced-motion preference, and
waveform rendering degrades to a static draw rather than an animated one.
