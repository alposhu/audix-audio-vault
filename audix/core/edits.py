"""The non-destructive edit model.

Every edit is a **parameter**, not a buffer mutation. The originally downloaded
audio is never written to; edits describe a transformation that is applied once,
on export, by an FFmpeg filtergraph.

Two things fall out of that choice:

* **Undo is free.** A history entry is a copy of a small dataclass, not a copy
  of the audio, so a hundred undo levels cost a few kilobytes. Undo depth is
  therefore generous rather than rationed.
* **Nothing is destructive.** The user can never lose the file they waited to
  download, which is the product's "the source is sacred" principle made real.
"""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import List, Optional, Tuple

from audix.core.audio.analysis import Region

log = logging.getLogger("audix.edits")

#: Undo depth. Generous because entries are parameter snapshots, not audio.
HISTORY_LIMIT = 200


class NormalizeMode(str, Enum):
    NONE = "none"
    PEAK = "peak"
    LOUDNESS = "loudness"


class FadeCurve(str, Enum):
    EQUAL_POWER = "equal_power"
    LINEAR = "linear"
    LOGARITHMIC = "logarithmic"

    @property
    def ffmpeg_name(self) -> str:
        # FFmpeg's afade curve vocabulary.
        return {
            FadeCurve.EQUAL_POWER: "qsin",
            FadeCurve.LINEAR: "tri",
            FadeCurve.LOGARITHMIC: "esin",
        }[self]


@dataclass
class Marker:
    """A named point on the timeline. Chapter markers become split points."""

    position: float
    label: str = ""
    from_chapter: bool = False


@dataclass
class Fade:
    start: float
    duration: float
    fade_in: bool
    curve: FadeCurve = FadeCurve.EQUAL_POWER

    @property
    def end(self) -> float:
        return self.start + self.duration


@dataclass
class EditState:
    """The complete, serialisable description of an edit.

    Times are in seconds against the **original** timeline, so a cut never
    invalidates a marker placed after it.
    """

    # Outer bounds. `trim_end` of None means "to the end of the source".
    trim_start: float = 0.0
    trim_end: Optional[float] = None

    #: Spans removed from the middle. Kept sorted and non-overlapping.
    cuts: List[Region] = field(default_factory=list)

    gain_db: float = 0.0
    eq_low_db: float = 0.0
    eq_mid_db: float = 0.0
    eq_high_db: float = 0.0

    fades: List[Fade] = field(default_factory=list)

    normalize: NormalizeMode = NormalizeMode.NONE
    normalize_target: float = -14.0        # LUFS, or dBFS in peak mode

    speed: float = 1.0                     # 0.5 - 2.0
    preserve_pitch: bool = True
    pitch_semitones: float = 0.0
    reverse: bool = False

    markers: List[Marker] = field(default_factory=list)

    def copy(self) -> "EditState":
        return copy.deepcopy(self)

    # ------------------------------------------------------------- inspection
    @property
    def is_pristine(self) -> bool:
        """True when the edit would produce audio identical to the source."""
        return (
            self.trim_start == 0.0
            and self.trim_end is None
            and not self.cuts
            and self.gain_db == 0.0
            and self.eq_low_db == 0.0
            and self.eq_mid_db == 0.0
            and self.eq_high_db == 0.0
            and not self.fades
            and self.normalize is NormalizeMode.NONE
            and self.speed == 1.0
            and self.pitch_semitones == 0.0
            and not self.reverse
        )

    def summary(self) -> List[str]:
        """Human-readable list of what this edit does, for the UI."""
        items: List[str] = []
        if self.trim_start > 0 or self.trim_end is not None:
            items.append("Trimmed")
        if self.cuts:
            items.append(f"{len(self.cuts)} cut{'s' if len(self.cuts) != 1 else ''}")
        if self.gain_db:
            items.append(f"Gain {self.gain_db:+.1f} dB")
        if self.eq_low_db or self.eq_mid_db or self.eq_high_db:
            items.append("EQ")
        if self.fades:
            items.append(f"{len(self.fades)} fade{'s' if len(self.fades) != 1 else ''}")
        if self.normalize is NormalizeMode.LOUDNESS:
            items.append(f"Normalized to {self.normalize_target:.0f} LUFS")
        elif self.normalize is NormalizeMode.PEAK:
            items.append(f"Peak normalized to {self.normalize_target:.1f} dBFS")
        if self.speed != 1.0:
            items.append(f"Speed {self.speed:.2f}x")
        if self.pitch_semitones:
            items.append(f"Pitch {self.pitch_semitones:+.1f} st")
        if self.reverse:
            items.append("Reversed")
        return items

    def output_duration(self, source_duration: float) -> float:
        """Predicted length of the exported file."""
        end = self.trim_end if self.trim_end is not None else source_duration
        span = max(0.0, min(end, source_duration) - self.trim_start)
        removed = sum(
            max(0.0, min(cut.end, end) - max(cut.start, self.trim_start))
            for cut in self.cuts
        )
        span = max(0.0, span - removed)
        return span / self.speed if self.speed else span

    def kept_segments(self, source_duration: float) -> List[Tuple[float, float]]:
        """The spans that survive, in order: bounds minus cuts."""
        start = max(0.0, self.trim_start)
        end = self.trim_end if self.trim_end is not None else source_duration
        end = min(end, source_duration)
        if end <= start:
            return []

        segments: List[Tuple[float, float]] = []
        cursor = start
        for cut in sorted(self.cuts, key=lambda c: c.start):
            cut_start = max(cut.start, start)
            cut_end = min(cut.end, end)
            if cut_end <= cursor:
                continue
            if cut_start > cursor:
                segments.append((cursor, min(cut_start, end)))
            cursor = max(cursor, cut_end)
            if cursor >= end:
                break
        if cursor < end:
            segments.append((cursor, end))
        return [(a, b) for a, b in segments if b - a > 1e-4]

    # ------------------------------------------------------------- mutation
    def add_cut(self, start: float, end: float) -> None:
        """Add a removed span, merging any it touches."""
        if end <= start:
            return
        merged = Region(start, end, "cut")
        remaining: List[Region] = []
        for cut in self.cuts:
            if cut.start <= merged.end and merged.start <= cut.end:
                merged = Region(min(merged.start, cut.start),
                                max(merged.end, cut.end), "cut")
            else:
                remaining.append(cut)
        remaining.append(merged)
        self.cuts = sorted(remaining, key=lambda c: c.start)

    def add_fade(self, start: float, duration: float, fade_in: bool,
                 curve: FadeCurve = FadeCurve.EQUAL_POWER) -> None:
        if duration <= 0:
            return
        self.fades = [
            f for f in self.fades if not (f.fade_in == fade_in
                                          and abs(f.start - start) < 1e-6)
        ]
        self.fades.append(Fade(start, duration, fade_in, curve))
        self.fades.sort(key=lambda f: f.start)

    def add_marker(self, position: float, label: str = "",
                   from_chapter: bool = False) -> None:
        if any(abs(m.position - position) < 1e-4 for m in self.markers):
            return
        self.markers.append(Marker(position, label, from_chapter))
        self.markers.sort(key=lambda m: m.position)

    def clear_markers(self, chapters_only: bool = False) -> None:
        if chapters_only:
            self.markers = [m for m in self.markers if not m.from_chapter]
        else:
            self.markers = []


class EditDocument:
    """An :class:`EditState` plus undo/redo history.

    Callers mutate through :meth:`mutate`, which snapshots first. Direct
    mutation of ``state`` is allowed for live scrubbing (a slider drag), with
    :meth:`checkpoint` called once when the interaction ends — otherwise a drag
    would push a hundred history entries.
    """

    def __init__(self, state: Optional[EditState] = None) -> None:
        self.state = state or EditState()
        self._undo: List[EditState] = []
        self._redo: List[EditState] = []
        self._pending: Optional[EditState] = None

    # --------------------------------------------------------------- history
    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_depth(self) -> int:
        return len(self._undo)

    def snapshot(self) -> None:
        """Record the current state as an undo point."""
        self._undo.append(self.state.copy())
        if len(self._undo) > HISTORY_LIMIT:
            self._undo.pop(0)
        self._redo.clear()

    def mutate(self, **changes) -> EditState:
        """Snapshot, then apply field changes. The common path for one action."""
        self.snapshot()
        self.state = replace(self.state, **changes)
        return self.state

    def begin(self) -> None:
        """Start a continuous interaction (a drag). Pairs with :meth:`checkpoint`."""
        if self._pending is None:
            self._pending = self.state.copy()

    def checkpoint(self) -> bool:
        """End a continuous interaction, recording one history entry if it changed."""
        if self._pending is None:
            return False
        changed = self._pending != self.state
        if changed:
            self._undo.append(self._pending)
            if len(self._undo) > HISTORY_LIMIT:
                self._undo.pop(0)
            self._redo.clear()
        self._pending = None
        return changed

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self.state.copy())
        self.state = self._undo.pop()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self.state.copy())
        self.state = self._redo.pop()
        return True

    def reset(self) -> None:
        """Return to a pristine edit, keeping the history so it can be undone."""
        self.snapshot()
        self.state = EditState()

    def clear_history(self) -> None:
        self._undo.clear()
        self._redo.clear()
        self._pending = None
