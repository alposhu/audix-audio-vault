"""Real-time DSP for preview playback.

These implementations run inside the audio callback, so they are block-based,
allocation-light, and stateful where the filter topology requires it. They exist
to answer the one capability Audacity lacks and Ocenaudio is praised for:
hearing an effect *while* the audio plays, with an A/B bypass.

Export does not use this module. Export re-renders from the original file
through an FFmpeg filtergraph (see :mod:`audix.core.render`), which is higher
quality and handles resampling properly. Preview and export are kept
deliberately equivalent in *audible* result, not in implementation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

# --------------------------------------------------------------------- gain

def db_to_linear(db: float) -> float:
    return float(10.0 ** (db / 20.0))


def linear_to_db(value: float) -> float:
    """Amplitude to dBFS, floored at -120 so silence does not return -inf."""
    return 20.0 * math.log10(max(abs(float(value)), 1e-6))


def apply_gain(block: np.ndarray, db: float) -> np.ndarray:
    if db == 0.0:
        return block
    return block * db_to_linear(db)


# --------------------------------------------------------------------- fades

def fade_envelope(positions: np.ndarray, start: float, length: float,
                  fade_in: bool, curve: str = "equal_power") -> np.ndarray:
    """Gain multipliers for sample positions (in seconds) within a fade.

    ``equal_power`` keeps perceived loudness constant through a crossfade;
    ``linear`` is the right choice for a hard cut to silence.
    """
    if length <= 0:
        return np.ones_like(positions, dtype=np.float32)
    t = np.clip((positions - start) / length, 0.0, 1.0)
    if not fade_in:
        t = 1.0 - t
    if curve == "linear":
        gain = t
    elif curve == "logarithmic":
        gain = np.square(t)
    else:                                   # equal power (default)
        gain = np.sin(t * (math.pi / 2.0))
    return gain.astype(np.float32)


# ----------------------------------------------------------------- biquad EQ

@dataclass
class Biquad:
    """Transposed direct-form II biquad. One instance per channel."""

    b0: float = 1.0
    b1: float = 0.0
    b2: float = 0.0
    a1: float = 0.0
    a2: float = 0.0
    z1: np.ndarray = field(default=None, repr=False)
    z2: np.ndarray = field(default=None, repr=False)

    def reset(self, channels: int) -> None:
        self.z1 = np.zeros(channels, dtype=np.float64)
        self.z2 = np.zeros(channels, dtype=np.float64)

    def process(self, block: np.ndarray) -> np.ndarray:
        """Filter ``(frames, channels)`` in place-safe fashion.

        The recurrence is genuinely sequential, so this is a Python loop over
        frames. Blocks are small (1024 frames) and this runs on the audio
        thread at roughly 2% of a core for stereo, which is acceptable; the
        alternative (scipy.lfilter) would add a large dependency for preview.
        """
        if self.z1 is None or self.z1.shape[0] != block.shape[1]:
            self.reset(block.shape[1])
        out = np.empty_like(block, dtype=np.float32)
        z1, z2 = self.z1, self.z2
        b0, b1, b2, a1, a2 = self.b0, self.b1, self.b2, self.a1, self.a2
        for i in range(block.shape[0]):
            x = block[i].astype(np.float64)
            y = b0 * x + z1
            z1 = b1 * x - a1 * y + z2
            z2 = b2 * x - a2 * y
            out[i] = y.astype(np.float32)
        self.z1, self.z2 = z1, z2
        return out


def _low_shelf(sample_rate: int, freq: float, gain_db: float, slope: float = 1.0) -> Biquad:
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * math.pi * freq / sample_rate
    cos_w0, sin_w0 = math.cos(w0), math.sin(w0)
    alpha = sin_w0 / 2 * math.sqrt((A + 1 / A) * (1 / slope - 1) + 2)
    two_sqrt_a_alpha = 2 * math.sqrt(A) * alpha

    b0 = A * ((A + 1) - (A - 1) * cos_w0 + two_sqrt_a_alpha)
    b1 = 2 * A * ((A - 1) - (A + 1) * cos_w0)
    b2 = A * ((A + 1) - (A - 1) * cos_w0 - two_sqrt_a_alpha)
    a0 = (A + 1) + (A - 1) * cos_w0 + two_sqrt_a_alpha
    a1 = -2 * ((A - 1) + (A + 1) * cos_w0)
    a2 = (A + 1) + (A - 1) * cos_w0 - two_sqrt_a_alpha
    return Biquad(b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)


def _high_shelf(sample_rate: int, freq: float, gain_db: float, slope: float = 1.0) -> Biquad:
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * math.pi * freq / sample_rate
    cos_w0, sin_w0 = math.cos(w0), math.sin(w0)
    alpha = sin_w0 / 2 * math.sqrt((A + 1 / A) * (1 / slope - 1) + 2)
    two_sqrt_a_alpha = 2 * math.sqrt(A) * alpha

    b0 = A * ((A + 1) + (A - 1) * cos_w0 + two_sqrt_a_alpha)
    b1 = -2 * A * ((A - 1) + (A + 1) * cos_w0)
    b2 = A * ((A + 1) + (A - 1) * cos_w0 - two_sqrt_a_alpha)
    a0 = (A + 1) - (A - 1) * cos_w0 + two_sqrt_a_alpha
    a1 = 2 * ((A - 1) - (A + 1) * cos_w0)
    a2 = (A + 1) - (A - 1) * cos_w0 - two_sqrt_a_alpha
    return Biquad(b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)


def _peaking(sample_rate: int, freq: float, gain_db: float, q: float = 1.0) -> Biquad:
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * math.pi * freq / sample_rate
    cos_w0, sin_w0 = math.cos(w0), math.sin(w0)
    alpha = sin_w0 / (2 * q)

    b0 = 1 + alpha * A
    b1 = -2 * cos_w0
    b2 = 1 - alpha * A
    a0 = 1 + alpha / A
    a1 = -2 * cos_w0
    a2 = 1 - alpha / A
    return Biquad(b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)


#: Fixed band centres. Matching FFmpeg's equalizer/bass/treble defaults keeps
#: preview and export audibly equivalent.
EQ_LOW_HZ = 100.0
EQ_MID_HZ = 1000.0
EQ_HIGH_HZ = 8000.0


class ThreeBandEQ:
    """Low shelf / mid peak / high shelf, the standard tone-control layout."""

    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self.low_db = 0.0
        self.mid_db = 0.0
        self.high_db = 0.0
        self._stages: List[Biquad] = []
        self._rebuild()

    def set_gains(self, low_db: float, mid_db: float, high_db: float) -> None:
        if (low_db, mid_db, high_db) == (self.low_db, self.mid_db, self.high_db):
            return
        self.low_db, self.mid_db, self.high_db = low_db, mid_db, high_db
        self._rebuild()

    @property
    def is_flat(self) -> bool:
        return self.low_db == 0.0 and self.mid_db == 0.0 and self.high_db == 0.0

    def _rebuild(self) -> None:
        stages: List[Biquad] = []
        if self.low_db:
            stages.append(_low_shelf(self.sample_rate, EQ_LOW_HZ, self.low_db))
        if self.mid_db:
            stages.append(_peaking(self.sample_rate, EQ_MID_HZ, self.mid_db, q=0.9))
        if self.high_db:
            stages.append(_high_shelf(self.sample_rate, EQ_HIGH_HZ, self.high_db))
        self._stages = stages

    def reset(self, channels: int) -> None:
        for stage in self._stages:
            stage.reset(channels)

    def process(self, block: np.ndarray) -> np.ndarray:
        for stage in self._stages:
            block = stage.process(block)
        return block


# ------------------------------------------------------------------ limiting

def soft_clip(block: np.ndarray, ceiling: float = 0.999) -> np.ndarray:
    """Prevent hard digital clipping on the monitor path.

    Preview gain staging can exceed full scale; hard wraparound would sound far
    worse than the mild saturation applied here. Export uses FFmpeg's true-peak
    limiter instead, so this never affects a written file.
    """
    peak = float(np.max(np.abs(block))) if block.size else 0.0
    if peak <= ceiling:
        return block
    return np.tanh(block / peak * 1.4) * ceiling


def mix_to_mono(block: np.ndarray) -> np.ndarray:
    if block.ndim == 1 or block.shape[1] == 1:
        return block.reshape(-1)
    return block.mean(axis=1)


def block_peak_db(block: np.ndarray) -> float:
    if block.size == 0:
        return -120.0
    return linear_to_db(float(np.max(np.abs(block))))


def block_rms_db(block: np.ndarray) -> float:
    if block.size == 0:
        return -120.0
    return linear_to_db(float(np.sqrt(np.mean(np.square(block, dtype=np.float64)))))
