---
version: 1
slug: "audix-ui-main-window-py"
primary_target: "audix/ui/main_window.py"
related_targets: ["audix/ui/tabs/queue_tab.py","audix/ui/tabs/browser_tab.py"]
---

# audix application shell — surface brief

Scope: the whole desktop app (shell, Queue, Downloads, Browse, Settings; the Editor inherits). Mode: Operate.

Job: get exactly the audio you meant out of YouTube, choosing what to take from a list, and see every item land.
Constraints: PySide6 / QSS, painted delegates for long lists, lite build has no browser, editor behaviour untouched.
Build path: code-led (no image generation in this harness).

## Direction contract

THESIS: audix is a receiver you tune, not a dashboard you read. One lit dial is the brightest object on a dark bronze faceplate; content sits behind recessed windows. It refuses the sidebar-plus-near-black-cards download manager, including audix's own previous look.

OWN-WORLD: Anodised bronze plate, smoked-glass wells, one tungsten-lit dial strip with a printed scale and a red needle. Tungsten means lit: it will act now. Green lamp means finished, red means failure. Rectilinear keys with a top highlight, every state a lamp plus a word, progress a tick ladder, tabular figures, wide printed dial legends. No wood photos, screws, or faux brushed metal.

STORY: You paste a link or browse. Every link lands in the Queue as ticked rows. You untick what you do not want and press Download. Downloads shows each item's stage, size, speed, and time left, and holds what changed until you have seen it.

FIRST VIEWPORT: Full-width 76px dial at the top: wordmark left, stations Browse / Queue / Downloads / Edit / Settings on the glass, needle on the current one, signal ladder and live speed right. Beneath it the Queue: link field across the plate, the ticked list in a recessed window, and a bottom transport plate with Format, Quality, Save to, Run-at-a-time, then Download selected and Download all at the far right.

FORM: Hi-fi receiver at night, position 4 on the ordered list; seed key cf314d4c. Signature interaction: the needle glides to the chosen station (ease-out-quart, 220ms; instant under reduced motion). Motion grammar: lamps and ladders change state; nothing else moves.
Raises: Split-flap board: columns never move, only their contents. Gate board: a changed row stays lit until you have seen it. Developer console: destructive actions stand apart, outline until hovered. Star atlas: one red marker means here. Vertical feed: the actions for the current item stay in one fixed place.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Unresolved decisions

None. The user chose this direction in the structured question round.
