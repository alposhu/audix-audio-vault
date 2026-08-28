"""FFmpeg-backed audio conversion.

The converter is a thin, cancellable wrapper around an ``ffmpeg`` subprocess. It
reads ``-progress`` output on stdout so the UI gets a real percentage rather than a
spinner, and it can stream-copy instead of re-encoding when the source already
matches the requested target at native quality.
"""
from __future__ import annotations

import logging
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from audix.core import formats
from audix.core.ffmpeg_manager import probe_audio_stream, probe_duration
from audix.utils.proc import no_window_kwargs

log = logging.getLogger("audix.converter")

ProgressCallback = Callable[[float], None]   # 0.0 - 1.0

# Source codecs that can be remuxed straight into a target format without loss.
_COPY_COMPATIBLE = {
    "opus": {"opus"},
    "m4a": {"aac"},
    "aac": {"aac"},
    "ogg": {"vorbis"},
    "flac": {"flac"},
}


class ConversionError(RuntimeError):
    """FFmpeg exited non-zero or produced no output."""


class ConversionCancelled(RuntimeError):
    """The job was cancelled while FFmpeg was running."""


@dataclass
class ConversionResult:
    output_path: Path
    stream_copied: bool
    effective_bitrate: str


class AudioConverter:
    """Converts a downloaded source file into one of the supported audio formats."""

    def __init__(self, ffmpeg_path: str, ffprobe_path: str) -> None:
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path

    # ----------------------------------------------------------------- public
    def convert(
        self,
        source: Path,
        destination: Path,
        audio_format: str,
        bitrate: str = "320",
        duration: Optional[float] = None,
        progress: Optional[ProgressCallback] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> ConversionResult:
        """Encode ``source`` into ``destination`` using ``audio_format``.

        ``bitrate`` is a member of :data:`audix.core.formats.BITRATE_PRESETS`. With
        ``native``, the source bitrate is probed and reused, and a stream copy is
        preferred when the codecs already match.
        """
        fmt = formats.get(audio_format)
        source = Path(source)
        destination = Path(destination)

        if not source.is_file():
            raise ConversionError(f"Source file is missing: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)

        if duration is None:
            duration = probe_duration(self.ffprobe_path, source)

        args, stream_copied, effective = self._build_args(source, destination, fmt, bitrate)
        log.debug("ffmpeg %s", " ".join(args[1:]))

        self._run(args, duration, progress, cancel_event)

        if not destination.is_file() or destination.stat().st_size == 0:
            raise ConversionError(
                f"FFmpeg reported success but produced no output for {source.name}."
            )
        return ConversionResult(destination, stream_copied, effective)

    # ---------------------------------------------------------------- internals
    def _build_args(
        self,
        source: Path,
        destination: Path,
        fmt: formats.AudioFormat,
        bitrate: str,
    ) -> tuple:
        """Assemble the ffmpeg command line. Returns (args, copied, bitrate_label)."""
        source_codec, source_bitrate = probe_audio_stream(self.ffprobe_path, source)
        native = bitrate == formats.NATIVE_BITRATE
        stream_copied = False
        effective = bitrate

        output_args: List[str]
        if native and source_codec in _COPY_COMPATIBLE.get(fmt.key, set()):
            # Identical codec at native quality: remux, do not re-encode.
            output_args = ["-vn", "-c:a", "copy", *fmt.extra_args]
            stream_copied = True
            effective = f"{source_bitrate // 1000}k (copy)" if source_bitrate else "native (copy)"
        elif native and fmt.supports_bitrate and source_bitrate:
            kbps = _clamp_bitrate(source_bitrate // 1000)
            output_args = ["-vn", "-c:a", fmt.encoder, "-b:a", f"{kbps}k", *fmt.extra_args]
            effective = f"{kbps}k"
        else:
            output_args = fmt.output_args(bitrate)
            effective = "lossless" if fmt.lossless else f"{bitrate}k"

        args = [
            self.ffmpeg_path,
            "-hide_banner",
            "-nostdin",
            "-loglevel", "error",
            "-y",
            "-i", str(source),
            "-map", "0:a:0",
            "-map_metadata", "-1",     # audix writes tags itself, via mutagen
            *output_args,
            "-progress", "pipe:1",
            "-nostats",
            str(destination),
        ]
        return args, stream_copied, effective

    def _run(
        self,
        args: List[str],
        duration: Optional[float],
        progress: Optional[ProgressCallback],
        cancel_event: Optional[threading.Event],
    ) -> None:
        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                errors="replace",
                bufsize=1,
                **no_window_kwargs(),
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
                if progress and duration:
                    fraction = _parse_progress_line(line, duration)
                    if fraction is not None:
                        progress(fraction)
        finally:
            if cancelled:
                process.wait(timeout=10)
                raise ConversionCancelled("Conversion cancelled by user.")
            stderr = process.stderr.read() if process.stderr else ""
            returncode = process.wait()

        if returncode != 0:
            detail = (stderr or "").strip().splitlines()
            message = detail[-1] if detail else f"exit code {returncode}"
            raise ConversionError(f"FFmpeg failed: {message}")
        if progress:
            progress(1.0)


def _parse_progress_line(line: str, duration: float) -> Optional[float]:
    """Translate an ``-progress`` key=value line into a 0.0-1.0 fraction."""
    line = line.strip()
    if line == "progress=end":
        return 1.0
    if not line.startswith("out_time_us=") and not line.startswith("out_time_ms="):
        return None
    _, _, raw = line.partition("=")
    raw = raw.strip()
    if not raw.isdigit():
        return None
    # FFmpeg's out_time_ms is actually microseconds; both keys use the same unit.
    seconds = int(raw) / 1_000_000.0
    return max(0.0, min(seconds / duration, 1.0))


def _terminate(process: subprocess.Popen) -> None:
    """Ask FFmpeg to stop, then insist."""
    try:
        process.terminate()
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
    except OSError:
        pass


def _clamp_bitrate(kbps: int) -> int:
    """Keep probed native bitrates inside a range every encoder accepts."""
    return max(32, min(kbps, 512))
