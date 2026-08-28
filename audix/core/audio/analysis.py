"""Measurement: loudness, silence, and clipping.

Loudness uses FFmpeg's `loudnorm` measurement pass, which implements ITU-R
BS.1770 K-weighting with gating and EBU R128 normalisation. Measuring with the
same filter that later performs the correction is deliberate: a second-pass
`loudnorm` fed with first-pass measurements hits its target far more accurately
than a single pass, and using a different meter here would introduce drift
between what audix reports and what it writes.

Silence and clipping are derived from the already-computed peak pyramid rather
than re-reading samples, so both are effectively instant even on a long file.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from audix.utils.proc import no_window_kwargs

log = logging.getLogger("audix.audio.analysis")


# --------------------------------------------------------------- loudness

#: Delivery targets in LUFS. Streaming platforms normalise to roughly -14;
#: speech-led content sits at -16; EBU R128 broadcast is -23.
LOUDNESS_TARGETS = {
    "streaming": (-14.0, "Streaming (-14 LUFS)"),
    "apple": (-16.0, "Apple Music / podcast (-16 LUFS)"),
    "broadcast": (-23.0, "EBU R128 broadcast (-23 LUFS)"),
}

#: True-peak ceiling. -1.5 dBTP leaves headroom so a later lossy encode, which
#: can overshoot on reconstruction, does not clip.
DEFAULT_TRUE_PEAK = -1.5


@dataclass
class LoudnessMeasurement:
    """Result of a `loudnorm` measurement pass."""

    integrated_lufs: float
    true_peak_db: float
    lra: float
    threshold: float
    offset: float = 0.0

    @property
    def is_valid(self) -> bool:
        # loudnorm reports -inf (serialised as -70 or lower) for silence.
        return self.integrated_lufs > -70.0

    def gain_to(self, target_lufs: float) -> float:
        """dB of gain needed to reach ``target_lufs``."""
        return target_lufs - self.integrated_lufs

    def describe(self) -> str:
        if not self.is_valid:
            return "Silent or unmeasurable"
        return (f"{self.integrated_lufs:.1f} LUFS  ·  "
                f"true peak {self.true_peak_db:.1f} dBTP  ·  "
                f"range {self.lra:.1f} LU")


def measure_loudness(ffmpeg: str, source: Path,
                     timeout: float = 600.0) -> Optional[LoudnessMeasurement]:
    """Run the `loudnorm` measurement pass over ``source``.

    Returns ``None`` if measurement fails; callers fall back to peak
    normalisation rather than failing the whole operation.
    """
    cmd = [
        ffmpeg, "-hide_banner", "-nostdin",
        "-i", str(source),
        "-map", "0:a:0",
        "-af", "loudnorm=print_format=json",
        "-f", "null", "-",
    ]
    try:
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, text=True, errors="replace",
            timeout=timeout, check=False, **no_window_kwargs(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("Loudness measurement failed to run: %s", exc)
        return None

    # loudnorm prints its JSON block to stderr, after the log output.
    payload = _last_json_object(result.stderr or "")
    if payload is None:
        log.warning("Could not parse loudnorm output for %s", source.name)
        return None

    try:
        return LoudnessMeasurement(
            integrated_lufs=float(payload["input_i"]),
            true_peak_db=float(payload["input_tp"]),
            lra=float(payload["input_lra"]),
            threshold=float(payload["input_thresh"]),
            offset=float(payload.get("target_offset", 0.0)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        log.warning("Unexpected loudnorm payload: %s", exc)
        return None


def _last_json_object(text: str) -> Optional[dict]:
    """Extract the final ``{...}`` block from FFmpeg's stderr."""
    start = text.rfind("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def loudnorm_filter(measurement: Optional[LoudnessMeasurement], target_lufs: float,
                    true_peak: float = DEFAULT_TRUE_PEAK) -> str:
    """Build the second-pass `loudnorm` filter string.

    With a measurement, this is the accurate two-pass form. Without one it
    degrades to single-pass, which is less precise but still correct.
    """
    base = f"loudnorm=I={target_lufs}:TP={true_peak}:LRA=11"
    if measurement is None or not measurement.is_valid:
        return base
    return (
        f"{base}"
        f":measured_I={measurement.integrated_lufs}"
        f":measured_TP={measurement.true_peak_db}"
        f":measured_LRA={measurement.lra}"
        f":measured_thresh={measurement.threshold}"
        f":offset={measurement.offset}"
        f":linear=true:print_format=summary"
    )


# ----------------------------------------------------------------- silence

@dataclass
class Region:
    """A span of the timeline, in seconds."""

    start: float
    end: float
    label: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def overlaps(self, other: "Region") -> bool:
        return self.start < other.end and other.start < self.end


def detect_silence(pyramid, threshold_db: float = -50.0,
                   min_duration: float = 0.5) -> List[Region]:
    """Find silent spans using the coarse peak data.

    Reads the pyramid rather than the samples, so a three-hour file is analysed
    in milliseconds.
    """
    if pyramid is None or not pyramid.levels:
        return []
    level = pyramid.levels[0]
    if level.buckets == 0:
        return []

    threshold = 10.0 ** (threshold_db / 20.0)
    amplitude = np.maximum(np.abs(level.minimum), np.abs(level.maximum)).max(axis=1)
    quiet = amplitude < threshold

    seconds_per_bucket = level.frames_per_bucket / pyramid.sample_rate
    regions: List[Region] = []
    start_index: Optional[int] = None

    for index, is_quiet in enumerate(quiet):
        if is_quiet and start_index is None:
            start_index = index
        elif not is_quiet and start_index is not None:
            _append_region(regions, start_index, index, seconds_per_bucket, min_duration)
            start_index = None
    if start_index is not None:
        _append_region(regions, start_index, len(quiet), seconds_per_bucket, min_duration)
    return regions


def _append_region(regions: List[Region], start: int, end: int,
                   seconds_per_bucket: float, min_duration: float) -> None:
    span = (end - start) * seconds_per_bucket
    if span >= min_duration:
        regions.append(Region(start * seconds_per_bucket, end * seconds_per_bucket,
                              "silence"))


def trim_bounds(pyramid, threshold_db: float = -50.0) -> Tuple[float, float]:
    """First and last non-silent moment, for one-click leading/trailing trim."""
    if pyramid is None or not pyramid.levels:
        return 0.0, 0.0
    level = pyramid.levels[0]
    if level.buckets == 0:
        return 0.0, 0.0

    threshold = 10.0 ** (threshold_db / 20.0)
    amplitude = np.maximum(np.abs(level.minimum), np.abs(level.maximum)).max(axis=1)
    loud = np.flatnonzero(amplitude >= threshold)
    seconds_per_bucket = level.frames_per_bucket / pyramid.sample_rate
    if loud.size == 0:
        return 0.0, pyramid.frames / pyramid.sample_rate
    return (
        float(loud[0] * seconds_per_bucket),
        float(min((loud[-1] + 1) * seconds_per_bucket,
                  pyramid.frames / pyramid.sample_rate)),
    )


# ---------------------------------------------------------------- clipping

@dataclass
class ClipReport:
    """Where and how badly the signal exceeds full scale."""

    positions: List[float]
    peak_amplitude: float

    @property
    def count(self) -> int:
        return len(self.positions)

    @property
    def peak_db(self) -> float:
        from audix.core.audio.dsp import linear_to_db
        return linear_to_db(self.peak_amplitude)

    @property
    def is_clipping(self) -> bool:
        return self.count > 0


def detect_clipping(pyramid, ceiling: float = 0.997,
                    max_markers: int = 400) -> ClipReport:
    """Locate buckets that reach or exceed full scale.

    Clipping is reported with a count and a dBFS figure as well as markers, so
    the information does not depend on seeing the colour red.
    """
    if pyramid is None or not pyramid.levels:
        return ClipReport([], 0.0)
    level = pyramid.levels[0]
    if level.buckets == 0:
        return ClipReport([], 0.0)

    amplitude = np.maximum(np.abs(level.minimum), np.abs(level.maximum)).max(axis=1)
    hits = np.flatnonzero(amplitude >= ceiling)
    seconds_per_bucket = level.frames_per_bucket / pyramid.sample_rate

    positions = [float(i * seconds_per_bucket) for i in hits[:max_markers]]
    return ClipReport(positions, float(amplitude.max()) if amplitude.size else 0.0)


def parse_silencedetect(stderr: str) -> List[Region]:
    """Parse FFmpeg's `silencedetect` output, for verification against the pyramid."""
    starts = [float(m) for m in re.findall(r"silence_start:\s*(-?[\d.]+)", stderr)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*(-?[\d.]+)", stderr)]
    return [Region(s, e, "silence") for s, e in zip(starts, ends)]
