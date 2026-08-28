"""Playback engine with live effect preview.

Audio is pulled from the memory-mapped :class:`AudioBuffer` inside a
``sounddevice`` callback, passed through the preview chain, and written to the
output device. Because the chain runs per block, changing a gain or an EQ band
is audible immediately — including mid-playback — and the A/B bypass switches
between processed and raw signal without a gap.

``sounddevice`` is an optional dependency. If it is missing the engine reports
``available == False`` and the UI explains what is unavailable and why, rather
than presenting a transport that silently does nothing.

Threading: the callback runs on a realtime audio thread and must never block.
It therefore only reads plain attributes and writes counters; the UI polls
:meth:`snapshot` on a timer instead of receiving signals from the audio thread.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from audix.core.audio.dsp import (
    ThreeBandEQ, db_to_linear, fade_envelope, soft_clip,
)

log = logging.getLogger("audix.audio.engine")

#: Frames per callback. Large enough that the Python-side EQ comfortably fits
#: inside the callback deadline, small enough that transport feels immediate.
BLOCK_SIZE = 2048

_IMPORT_ERROR: Optional[str] = None
try:                                        # pragma: no cover - environment dependent
    import sounddevice as _sd
except Exception as exc:                    # noqa: BLE001 - PortAudio can fail many ways
    _sd = None
    _IMPORT_ERROR = str(exc)


def backend_available() -> bool:
    return _sd is not None


def backend_error() -> str:
    """Why playback is unavailable, phrased for a user."""
    if _sd is not None:
        return ""
    return (
        "Real-time preview needs the 'sounddevice' package, which is not "
        f"installed or could not load its audio backend. ({_IMPORT_ERROR}) "
        "Install it with:  pip install sounddevice"
    )


@dataclass
class FadeSpec:
    start: float
    duration: float
    fade_in: bool
    curve: str = "equal_power"


@dataclass
class PreviewChain:
    """The effect chain applied during playback.

    Mutated from the UI thread and read from the audio thread. Every field is a
    single primitive or an immutable list swap, so no lock is needed on the
    audio side; a torn read costs at most one block of stale gain.
    """

    gain_db: float = 0.0
    eq_low_db: float = 0.0
    eq_mid_db: float = 0.0
    eq_high_db: float = 0.0
    fades: List[FadeSpec] = field(default_factory=list)
    bypass: bool = False

    @property
    def is_identity(self) -> bool:
        return (
            self.gain_db == 0.0
            and self.eq_low_db == 0.0
            and self.eq_mid_db == 0.0
            and self.eq_high_db == 0.0
            and not self.fades
        )

    def describe(self) -> str:
        if self.bypass:
            return "Bypassed (hearing the original)"
        if self.is_identity:
            return "No effects"
        parts = []
        if self.gain_db:
            parts.append(f"{self.gain_db:+.1f} dB")
        if self.eq_low_db or self.eq_mid_db or self.eq_high_db:
            parts.append(f"EQ {self.eq_low_db:+.0f}/{self.eq_mid_db:+.0f}"
                         f"/{self.eq_high_db:+.0f}")
        if self.fades:
            parts.append(f"{len(self.fades)} fade{'s' if len(self.fades) != 1 else ''}")
        return " · ".join(parts)


@dataclass
class EngineSnapshot:
    """Immutable view for the UI, polled on a timer."""

    playing: bool
    frame: int
    seconds: float
    peak_left: float
    peak_right: float
    clipped: bool


class PlaybackEngine:
    """Streams an :class:`AudioBuffer` to the audio device through a chain."""

    def __init__(self) -> None:
        self.chain = PreviewChain()
        self._buffer = None
        self._stream = None
        self._eq: Optional[ThreeBandEQ] = None

        self._lock = threading.RLock()
        self._position = 0
        self._playing = False
        self._loop: Optional[Tuple[int, int]] = None
        self._bounds: Optional[Tuple[int, int]] = None

        # Written by the audio thread, read by the UI. Plain floats: a stale
        # read is harmless and locking here would risk an underrun.
        self._peak_l = 0.0
        self._peak_r = 0.0
        self._clipped = False

    # ------------------------------------------------------------------ setup
    @property
    def available(self) -> bool:
        return backend_available()

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def has_audio(self) -> bool:
        return self._buffer is not None and self._buffer.frames > 0

    def load(self, buffer) -> None:
        """Attach a decoded buffer. Stops any current playback."""
        self.stop()
        with self._lock:
            self._buffer = buffer
            self._position = 0
            self._bounds = None
            self._loop = None
            self._eq = ThreeBandEQ(buffer.sample_rate) if buffer is not None else None

    def unload(self) -> None:
        self.stop()
        with self._lock:
            self._buffer = None
            self._eq = None

    # -------------------------------------------------------------- transport
    def play(self, start_frame: Optional[int] = None) -> bool:
        """Begin playback. Returns False when no backend or no audio."""
        if not self.available or not self.has_audio:
            return False
        with self._lock:
            if start_frame is not None:
                self._position = self._clamp(start_frame)
            if self._eq is not None:
                self._eq.set_gains(self.chain.eq_low_db, self.chain.eq_mid_db,
                                   self.chain.eq_high_db)
                self._eq.reset(self._buffer.channels)

        if self._stream is None and not self._open_stream():
            return False
        self._playing = True
        return True

    def pause(self) -> None:
        self._playing = False
        self._reset_meters()

    def stop(self) -> None:
        self._playing = False
        self._close_stream()
        self._reset_meters()

    def toggle(self) -> bool:
        if self._playing:
            self.pause()
        else:
            self.play()
        return self._playing

    def seek(self, frame: int) -> None:
        with self._lock:
            self._position = self._clamp(frame)

    def seek_seconds(self, seconds: float) -> None:
        if self._buffer is not None:
            self.seek(self._buffer.seconds_to_frame(seconds))

    def set_bounds(self, start_frame: Optional[int], end_frame: Optional[int]) -> None:
        """Restrict playback to a range - used to audition a selection."""
        with self._lock:
            if start_frame is None or end_frame is None or end_frame <= start_frame:
                self._bounds = None
            else:
                self._bounds = (self._clamp(start_frame), self._clamp(end_frame))
                self._position = self._bounds[0]

    def set_loop(self, start_frame: Optional[int], end_frame: Optional[int]) -> None:
        with self._lock:
            if start_frame is None or end_frame is None or end_frame <= start_frame:
                self._loop = None
            else:
                self._loop = (self._clamp(start_frame), self._clamp(end_frame))

    # --------------------------------------------------------------- readback
    def snapshot(self) -> EngineSnapshot:
        buffer = self._buffer
        position = self._position
        seconds = buffer.frame_to_seconds(position) if buffer is not None else 0.0
        return EngineSnapshot(
            playing=self._playing,
            frame=position,
            seconds=seconds,
            peak_left=self._peak_l,
            peak_right=self._peak_r,
            clipped=self._clipped,
        )

    def acknowledge_clip(self) -> None:
        self._clipped = False

    # --------------------------------------------------------------- internals
    def _clamp(self, frame: int) -> int:
        if self._buffer is None:
            return 0
        return max(0, min(int(frame), self._buffer.frames))

    def _reset_meters(self) -> None:
        self._peak_l = 0.0
        self._peak_r = 0.0

    def _open_stream(self) -> bool:
        if not self.available or self._buffer is None:
            return False
        try:
            self._stream = _sd.OutputStream(
                samplerate=self._buffer.sample_rate,
                channels=self._buffer.channels,
                dtype="float32",
                blocksize=BLOCK_SIZE,
                callback=self._callback,
                finished_callback=self._on_finished,
            )
            self._stream.start()
            log.debug("Audio stream open: %d Hz x%d",
                      self._buffer.sample_rate, self._buffer.channels)
            return True
        except Exception as exc:  # noqa: BLE001 - PortAudio surfaces many errors
            log.error("Could not open audio output: %s", exc)
            self._stream = None
            return False

    def _close_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
        except Exception as exc:  # noqa: BLE001
            log.debug("Error closing audio stream: %s", exc)

    def _on_finished(self) -> None:
        self._playing = False

    # ------------------------------------------------------------- audio thread
    def _callback(self, outdata, frames, time_info, status) -> None:
        """Realtime callback. Must not block, allocate large, or raise."""
        if status:
            log.debug("Audio callback status: %s", status)

        buffer = self._buffer
        if buffer is None or not self._playing:
            outdata.fill(0)
            return

        start = self._position
        end_limit = self._bounds[1] if self._bounds else buffer.frames

        block = buffer.read(start, frames)
        available = block.shape[0]
        if start + available > end_limit:
            available = max(0, end_limit - start)
            block = block[:available]

        if available == 0:
            outdata.fill(0)
            if self._loop:
                self._position = self._loop[0]
            else:
                self._playing = False
            return

        processed = self._process(block, start, buffer.sample_rate)

        outdata[:available] = processed
        if available < frames:
            outdata[available:] = 0

        # Meters, for the UI's polling timer.
        if processed.shape[1] >= 2:
            self._peak_l = float(np.max(np.abs(processed[:, 0])))
            self._peak_r = float(np.max(np.abs(processed[:, 1])))
        else:
            level = float(np.max(np.abs(processed)))
            self._peak_l = self._peak_r = level
        if max(self._peak_l, self._peak_r) >= 0.999:
            self._clipped = True

        next_position = start + available
        if self._loop and next_position >= self._loop[1]:
            next_position = self._loop[0]
        elif next_position >= end_limit:
            if self._loop:
                next_position = self._loop[0]
            else:
                self._playing = False
        self._position = next_position

    def _process(self, block: np.ndarray, start_frame: int,
                 sample_rate: int) -> np.ndarray:
        """Apply the preview chain to one block."""
        chain = self.chain
        if chain.bypass or chain.is_identity:
            return block

        out = block

        if chain.fades:
            positions = (
                np.arange(start_frame, start_frame + out.shape[0], dtype=np.float64)
                / sample_rate
            )
            envelope = np.ones(out.shape[0], dtype=np.float32)
            for fade in chain.fades:
                envelope *= fade_envelope(
                    positions, fade.start, fade.duration, fade.fade_in, fade.curve
                )
            out = out * envelope[:, np.newaxis]

        eq = self._eq
        if eq is not None:
            eq.set_gains(chain.eq_low_db, chain.eq_mid_db, chain.eq_high_db)
            if not eq.is_flat:
                out = eq.process(out)

        if chain.gain_db:
            out = out * db_to_linear(chain.gain_db)

        return soft_clip(out)
