"""Export: turn an :class:`EditState` into an FFmpeg filtergraph and render it.

Export always re-reads the **original source file**, never the decoded preview
buffer, so nothing is lost to the intermediate representation used for drawing
and monitoring.

Ordering inside the graph is deliberate and mirrors a mastering chain:

    segments -> concat -> reverse -> speed/pitch -> EQ -> fades -> gain -> loudness

Loudness normalisation is last because it must measure and correct what the
listener will actually hear; running it before a gain change would make its
target meaningless.
"""
from __future__ import annotations

import logging
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from audix.core import formats
from audix.core.audio.analysis import (
    DEFAULT_TRUE_PEAK, LoudnessMeasurement, loudnorm_filter, measure_loudness,
)
from audix.core.converter import ConversionCancelled, ConversionError, _parse_progress_line
from audix.core.edits import EditState, NormalizeMode
from audix.utils.proc import no_window_kwargs

log = logging.getLogger("audix.render")

ProgressCallback = Callable[[float], None]

#: FFmpeg's atempo accepts 0.5-2.0 per instance; wider ranges chain instances.
_ATEMPO_MIN, _ATEMPO_MAX = 0.5, 2.0


@dataclass
class RenderRequest:
    """Everything needed to produce one output file."""

    source: Path
    destination: Path
    state: EditState
    audio_format: str
    bitrate: str = "320"
    source_duration: float = 0.0
    #: Optional sub-range of the *edited* result, used for chapter splitting.
    segment: Optional[Tuple[float, float]] = None


def map_to_output(state: EditState, position: float, source_duration: float) -> float:
    """Translate a source-timeline position into the edited output timeline.

    Fades and markers are stored against the original timeline so that adding a
    cut never silently moves them; this converts at render time.
    """
    output = 0.0
    for start, end in state.kept_segments(source_duration):
        if position >= end:
            output += end - start
        elif position > start:
            return (output + (position - start)) / (state.speed or 1.0)
        else:
            break
    return output / (state.speed or 1.0)


def _atempo_chain(rate: float) -> List[str]:
    """Decompose an arbitrary tempo ratio into legal atempo stages."""
    if abs(rate - 1.0) < 1e-6:
        return []
    stages: List[str] = []
    remaining = rate
    # Split into factors inside FFmpeg's accepted range.
    while remaining > _ATEMPO_MAX:
        stages.append(f"atempo={_ATEMPO_MAX}")
        remaining /= _ATEMPO_MAX
    while remaining < _ATEMPO_MIN:
        stages.append(f"atempo={_ATEMPO_MIN}")
        remaining /= _ATEMPO_MIN
    if abs(remaining - 1.0) > 1e-6:
        stages.append(f"atempo={remaining:.6f}")
    return stages


def build_filtergraph(
    state: EditState,
    source_duration: float,
    sample_rate: int = 44100,
    measurement: Optional[LoudnessMeasurement] = None,
    segment: Optional[Tuple[float, float]] = None,
) -> Tuple[str, bool]:
    """Return ``(filter_complex, uses_complex)`` for this edit.

    A single kept span needs only a simple ``-af`` chain; multiple spans need
    ``-filter_complex`` with a concat, so the caller is told which to use.
    """
    segments = state.kept_segments(source_duration)
    if not segments:
        raise ConversionError(
            "This edit removes all of the audio. Adjust the trim or cuts first."
        )

    stages: List[str] = []
    uses_complex = len(segments) > 1

    if uses_complex:
        parts = []
        for index, (start, end) in enumerate(segments):
            parts.append(
                f"[0:a]atrim=start={start:.6f}:end={end:.6f},"
                f"asetpts=PTS-STARTPTS[seg{index}]"
            )
        chain = "".join(f"[seg{i}]" for i in range(len(segments)))
        parts.append(f"{chain}concat=n={len(segments)}:v=0:a=1[joined]")
        prefix = ";".join(parts) + ";[joined]"
    else:
        start, end = segments[0]
        stages.append(f"atrim=start={start:.6f}:end={end:.6f}")
        stages.append("asetpts=PTS-STARTPTS")
        prefix = ""

    # --- reverse ---------------------------------------------------------
    if state.reverse:
        stages.append("areverse")

    # --- pitch and speed --------------------------------------------------
    if state.pitch_semitones:
        ratio = 2.0 ** (state.pitch_semitones / 12.0)
        # Resample to shift pitch, then correct the tempo it dragged with it.
        stages.append(f"asetrate={int(sample_rate * ratio)}")
        stages.append(f"aresample={sample_rate}")
        stages.extend(_atempo_chain(1.0 / ratio))

    if state.speed != 1.0:
        if state.preserve_pitch:
            stages.extend(_atempo_chain(state.speed))
        else:
            stages.append(f"asetrate={int(sample_rate * state.speed)}")
            stages.append(f"aresample={sample_rate}")

    # --- EQ ---------------------------------------------------------------
    # Band centres match audix.core.audio.dsp so preview and export agree.
    if state.eq_low_db:
        stages.append(f"bass=g={state.eq_low_db:.2f}:f=100")
    if state.eq_mid_db:
        stages.append(f"equalizer=f=1000:t=q:w=0.9:g={state.eq_mid_db:.2f}")
    if state.eq_high_db:
        stages.append(f"treble=g={state.eq_high_db:.2f}:f=8000")

    # --- fades ------------------------------------------------------------
    for fade in state.fades:
        start = map_to_output(state, fade.start, source_duration)
        duration = max(0.01, fade.duration / (state.speed or 1.0))
        kind = "in" if fade.fade_in else "out"
        stages.append(
            f"afade=t={kind}:st={start:.6f}:d={duration:.6f}"
            f":curve={fade.curve.ffmpeg_name}"
        )

    # --- gain -------------------------------------------------------------
    if state.gain_db:
        stages.append(f"volume={state.gain_db:.2f}dB")

    # --- chapter segment --------------------------------------------------
    # Applied after edits so split points refer to the edited timeline.
    if segment is not None:
        seg_start, seg_end = segment
        stages.append(f"atrim=start={seg_start:.6f}:end={seg_end:.6f}")
        stages.append("asetpts=PTS-STARTPTS")

    # --- loudness (last: it must measure the final signal) ----------------
    if state.normalize is NormalizeMode.LOUDNESS:
        stages.append(loudnorm_filter(measurement, state.normalize_target,
                                      DEFAULT_TRUE_PEAK))
    elif state.normalize is NormalizeMode.PEAK:
        # `volume` with replaygain-style peak detection is not available in one
        # pass, so peak mode uses the measured true peak when we have it.
        if measurement is not None and measurement.is_valid:
            delta = state.normalize_target - measurement.true_peak_db
            stages.append(f"volume={delta:.2f}dB")
        else:
            stages.append("dynaudnorm=p=0.9:m=10")

    if not stages:
        stages.append("anull")

    return prefix + ",".join(stages), uses_complex


class Renderer:
    """Executes a :class:`RenderRequest` through FFmpeg."""

    def __init__(self, ffmpeg_path: str, ffprobe_path: str) -> None:
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path

    def measure_if_needed(self, request: RenderRequest) -> Optional[LoudnessMeasurement]:
        """Run the loudness measurement pass when the edit calls for one."""
        if request.state.normalize is NormalizeMode.NONE:
            return None
        return measure_loudness(self.ffmpeg_path, request.source)

    def render(
        self,
        request: RenderRequest,
        progress: Optional[ProgressCallback] = None,
        cancel_event: Optional[threading.Event] = None,
        measurement: Optional[LoudnessMeasurement] = None,
    ) -> Path:
        """Render one file. Returns the written path."""
        fmt = formats.get(request.audio_format)
        destination = Path(request.destination)
        destination.parent.mkdir(parents=True, exist_ok=True)

        from audix.core.audio.decoder import probe_stream_format

        stream_format = probe_stream_format(self.ffprobe_path, request.source)
        graph, uses_complex = build_filtergraph(
            request.state,
            request.source_duration,
            sample_rate=stream_format.sample_rate,
            measurement=measurement,
            segment=request.segment,
        )

        args = [
            self.ffmpeg_path, "-hide_banner", "-nostdin",
            "-loglevel", "error", "-y",
            "-i", str(request.source),
        ]
        if uses_complex:
            args += ["-filter_complex", graph]
        else:
            args += ["-map", "0:a:0", "-af", graph]
        args += [
            "-map_metadata", "-1",          # audix writes tags itself
            *fmt.output_args(request.bitrate),
            "-progress", "pipe:1", "-nostats",
            str(destination),
        ]

        expected = request.state.output_duration(request.source_duration)
        if request.segment is not None:
            expected = max(0.0, request.segment[1] - request.segment[0])

        log.debug("Rendering %s (%.1fs expected)", destination.name, expected)
        self._run(args, expected, progress, cancel_event)

        if not destination.is_file() or destination.stat().st_size == 0:
            raise ConversionError(
                f"FFmpeg reported success but wrote no audio for {destination.name}."
            )
        return destination

    def _run(self, args: List[str], duration: float,
             progress: Optional[ProgressCallback],
             cancel_event: Optional[threading.Event]) -> None:
        try:
            process = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL, text=True, errors="replace",
                bufsize=1, **no_window_kwargs(),
            )
        except OSError as exc:
            raise ConversionError(f"Could not start FFmpeg: {exc}") from exc

        cancelled = False
        try:
            assert process.stdout is not None
            for line in process.stdout:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    _terminate(process)
                    break
                if progress and duration > 0:
                    fraction = _parse_progress_line(line, duration)
                    if fraction is not None:
                        progress(fraction)
        finally:
            if cancelled:
                process.wait(timeout=10)
                raise ConversionCancelled("Export cancelled.")
            stderr = process.stderr.read() if process.stderr else ""
            code = process.wait()

        if code != 0:
            detail = (stderr or "").strip().splitlines()
            raise ConversionError(
                f"Export failed: {detail[-1] if detail else f'exit code {code}'}"
            )
        if progress:
            progress(1.0)


def _terminate(process: subprocess.Popen) -> None:
    try:
        process.terminate()
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
    except OSError:
        pass
