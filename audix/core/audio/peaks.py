"""Multi-resolution peak pyramid for waveform drawing.

This module exists because of a specific, documented failure mode. Naive
waveform renderers read every sample for every repaint; a public wavesurfer.js
report measured a 10-minute file taking 34 seconds and a 90-minute file taking
three minutes, with the UI frozen throughout.

The fix is to never let repaint cost scale with duration. Peaks are summarised
once, at several resolutions, into a pyramid:

    level 0 :   256 frames per bucket
    level 1 :  1024   (4x)
    level 2 :  4096
    ...

Drawing picks the coarsest level that still gives at least one bucket per
pixel, so a repaint always touches roughly `width` buckets — a few thousand
reads — no matter whether the file is three minutes or three hours.

Each bucket stores **min, max, and RMS**. The min/max pair draws the peak
envelope; RMS draws the brighter inner body that makes dynamics legible. A
peak-only waveform is a solid block that hides everything.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable, List, Optional

import numpy as np

log = logging.getLogger("audix.audio.peaks")

ProgressCallback = Callable[[float], None]

#: Frames summarised into one bucket at the finest level.
BASE_BUCKET = 256

#: Each level is this much coarser than the one below it.
LEVEL_FACTOR = 4

#: Frames read per pass while summarising. Bounded so RAM stays flat.
_CHUNK_FRAMES = 1 << 18


class PeaksCancelled(RuntimeError):
    """Analysis was cancelled before completion."""


@dataclass
class PeakLevel:
    """One resolution of the pyramid."""

    frames_per_bucket: int
    #: shape (buckets, channels)
    minimum: np.ndarray
    maximum: np.ndarray
    rms: np.ndarray

    @property
    def buckets(self) -> int:
        return self.minimum.shape[0]


class PeakPyramid:
    """Summarised amplitude data at several resolutions."""

    def __init__(self, levels: List[PeakLevel], frames: int, channels: int,
                 sample_rate: int) -> None:
        self.levels = levels
        self.frames = frames
        self.channels = channels
        self.sample_rate = sample_rate

    # ------------------------------------------------------------------ query
    def level_for(self, frames_visible: int, pixels: int) -> PeakLevel:
        """Coarsest level giving at least one bucket per pixel.

        Choosing by this rule is what keeps repaint cost proportional to widget
        width rather than to file duration.
        """
        if pixels <= 0 or not self.levels:
            return self.levels[0]
        wanted = max(1, frames_visible // max(1, pixels))
        chosen = self.levels[0]
        for level in self.levels:
            if level.frames_per_bucket <= wanted:
                chosen = level
            else:
                break
        return chosen

    def envelope(self, start_frame: int, end_frame: int, pixels: int,
                 channel: Optional[int] = None) -> tuple:
        """Return ``(min, max, rms)`` arrays of length ``pixels``.

        Values are mixed down across channels unless ``channel`` is given.
        Ready to draw: one entry per horizontal pixel, no further reduction.
        """
        pixels = max(1, int(pixels))
        start_frame = max(0, int(start_frame))
        end_frame = min(self.frames, max(start_frame + 1, int(end_frame)))
        level = self.level_for(end_frame - start_frame, pixels)

        lo = start_frame // level.frames_per_bucket
        hi = max(lo + 1, -(-end_frame // level.frames_per_bucket))  # ceil
        hi = min(hi, level.buckets)
        if hi <= lo:
            zeros = np.zeros(pixels, dtype=np.float32)
            return zeros, zeros.copy(), zeros.copy()

        def collapse(source: np.ndarray, reducer) -> np.ndarray:
            band = source[lo:hi]
            band = band[:, channel] if channel is not None else reducer(band, axis=1)
            # Map buckets onto pixels. When zoomed in there may be fewer
            # buckets than pixels, so this both downsamples and upsamples.
            index = np.linspace(0, len(band), pixels + 1).astype(np.int64)
            out = np.empty(pixels, dtype=np.float32)
            for i in range(pixels):
                a, b = index[i], max(index[i] + 1, index[i + 1])
                segment = band[a:min(b, len(band))]
                out[i] = reducer(segment) if segment.size else 0.0
            return out

        return (
            collapse(level.minimum, np.min),
            collapse(level.maximum, np.max),
            collapse(level.rms, np.max),
        )

    def peak_amplitude(self) -> float:
        """Largest absolute sample in the file, from the coarsest level."""
        if not self.levels:
            return 0.0
        top = self.levels[-1]
        if top.buckets == 0:
            return 0.0
        return float(max(np.max(np.abs(top.minimum)), np.max(np.abs(top.maximum))))

    def memory_bytes(self) -> int:
        return sum(
            lvl.minimum.nbytes + lvl.maximum.nbytes + lvl.rms.nbytes
            for lvl in self.levels
        )


def build(
    buffer,
    progress: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
    base_bucket: int = BASE_BUCKET,
    levels: int = 6,
) -> PeakPyramid:
    """Summarise an :class:`~audix.core.audio.decoder.AudioBuffer` into a pyramid.

    The finest level is computed by streaming the buffer in bounded chunks;
    every coarser level is then folded down from the one below it, which is
    far cheaper than re-reading the samples.
    """
    frames = buffer.frames
    channels = buffer.channels
    if frames <= 0:
        return PeakPyramid([], 0, channels, buffer.sample_rate)

    bucket_count = -(-frames // base_bucket)        # ceil
    mins = np.zeros((bucket_count, channels), dtype=np.float32)
    maxs = np.zeros((bucket_count, channels), dtype=np.float32)
    rmss = np.zeros((bucket_count, channels), dtype=np.float32)

    # --- finest level, streamed -------------------------------------------
    chunk_frames = (_CHUNK_FRAMES // base_bucket) * base_bucket
    position = 0
    while position < frames:
        if cancel_event is not None and cancel_event.is_set():
            raise PeaksCancelled("Waveform analysis cancelled.")
        take = min(chunk_frames, frames - position)
        block = buffer.view(position, take)
        if block.shape[0] == 0:
            break

        # Pad the tail so the block reshapes into whole buckets.
        n_buckets = -(-block.shape[0] // base_bucket)
        padded_len = n_buckets * base_bucket
        if padded_len != block.shape[0]:
            pad = np.zeros((padded_len - block.shape[0], channels), dtype=np.float32)
            block = np.vstack([block, pad])

        shaped = block.reshape(n_buckets, base_bucket, channels)
        offset = position // base_bucket
        mins[offset:offset + n_buckets] = shaped.min(axis=1)
        maxs[offset:offset + n_buckets] = shaped.max(axis=1)
        rmss[offset:offset + n_buckets] = np.sqrt(
            np.mean(np.square(shaped, dtype=np.float32), axis=1)
        )

        position += take
        if progress:
            progress(min(position / frames, 1.0) * 0.8)

    pyramid = [PeakLevel(base_bucket, mins, maxs, rmss)]

    # --- coarser levels, folded -------------------------------------------
    for index in range(1, levels):
        if cancel_event is not None and cancel_event.is_set():
            raise PeaksCancelled("Waveform analysis cancelled.")
        previous = pyramid[-1]
        if previous.buckets <= 2:
            break
        folded = _fold(previous, LEVEL_FACTOR)
        pyramid.append(folded)
        if progress:
            progress(0.8 + 0.2 * (index / max(1, levels - 1)))

    if progress:
        progress(1.0)

    result = PeakPyramid(pyramid, frames, channels, buffer.sample_rate)
    log.info(
        "Peak pyramid: %d levels, %.1f MB, coarsest %d frames/bucket",
        len(pyramid), result.memory_bytes() / 1e6, pyramid[-1].frames_per_bucket,
    )
    return result


def _fold(level: PeakLevel, factor: int) -> PeakLevel:
    """Combine ``factor`` adjacent buckets into one, without touching samples."""
    count = level.buckets
    groups = -(-count // factor)
    padded = groups * factor
    channels = level.minimum.shape[1]

    def reshape(source: np.ndarray, fill: float) -> np.ndarray:
        if padded != count:
            pad = np.full((padded - count, channels), fill, dtype=np.float32)
            source = np.vstack([source, pad])
        return source.reshape(groups, factor, channels)

    return PeakLevel(
        frames_per_bucket=level.frames_per_bucket * factor,
        minimum=reshape(level.minimum, 0.0).min(axis=1),
        maximum=reshape(level.maximum, 0.0).max(axis=1),
        # RMS of RMS values: max is the honest summary at coarser zoom, since
        # averaging would understate loud passages the user is looking for.
        rms=reshape(level.rms, 0.0).max(axis=1),
    )
