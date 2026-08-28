"""Decode any audio file into a random-access sample buffer.

The design constraint here is memory. A 90-minute stereo track at 44.1 kHz is
238 million frames; held as float32 in RAM that is ~1.9 GB, which is not
acceptable for a desktop app that may have several files open.

So audix decodes through FFmpeg into a temporary raw ``f32le`` file and
memory-maps it. RAM stays flat regardless of duration, the OS page cache makes
sequential playback fast, and the audio callback can seek anywhere instantly.

This buffer exists only for **display and preview**. Export never reads it — it
re-renders from the original source file through FFmpeg, so no quality is lost
to the intermediate representation.
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from audix.core.ffmpeg_manager import probe_duration
from audix.utils import paths
from audix.utils.proc import no_window_kwargs, run_capture

log = logging.getLogger("audix.audio.decoder")

ProgressCallback = Callable[[float], None]      # 0.0 - 1.0

#: Read size when pumping FFmpeg's stdout. Large enough to keep the pipe full.
_CHUNK = 1 << 20


class DecodeError(RuntimeError):
    """FFmpeg could not decode the source file."""


class DecodeCancelled(RuntimeError):
    """Decoding was cancelled before completion."""


@dataclass(frozen=True)
class AudioFormat:
    sample_rate: int
    channels: int

    @property
    def bytes_per_frame(self) -> int:
        return 4 * self.channels        # float32


class AudioBuffer:
    """A memory-mapped, random-access view of decoded PCM.

    Indexing returns ``float32`` samples shaped ``(frames, channels)`` in the
    range [-1, 1]. The backing file is deleted when :meth:`close` is called or
    the object is garbage-collected.
    """

    def __init__(self, path: Path, fmt: AudioFormat, frames: int,
                 owns_file: bool = True) -> None:
        self._path = Path(path)
        self.format = fmt
        self.frames = frames
        self._owns_file = owns_file
        self._closed = False
        self._lock = threading.RLock()
        self._map: Optional[np.memmap] = None
        if frames > 0:
            self._map = np.memmap(
                self._path, dtype=np.float32, mode="r",
                shape=(frames, fmt.channels),
            )

    # ---------------------------------------------------------------- access
    @property
    def sample_rate(self) -> int:
        return self.format.sample_rate

    @property
    def channels(self) -> int:
        return self.format.channels

    @property
    def duration(self) -> float:
        return self.frames / self.format.sample_rate if self.format.sample_rate else 0.0

    def read(self, start: int, count: int) -> np.ndarray:
        """Frames ``[start, start+count)``, clipped to the buffer, as a copy."""
        with self._lock:
            if self._closed or self._map is None:
                return np.zeros((0, self.channels), dtype=np.float32)
            start = max(0, min(int(start), self.frames))
            end = max(start, min(start + int(count), self.frames))
            return np.array(self._map[start:end], dtype=np.float32, copy=True)

    def view(self, start: int = 0, count: Optional[int] = None) -> np.ndarray:
        """Zero-copy view for read-only analysis. Do not retain across close()."""
        with self._lock:
            if self._closed or self._map is None:
                return np.zeros((0, self.channels), dtype=np.float32)
            start = max(0, min(int(start), self.frames))
            end = self.frames if count is None else min(start + int(count), self.frames)
            return self._map[start:max(start, end)]

    def seconds_to_frame(self, seconds: float) -> int:
        return int(round(max(0.0, seconds) * self.format.sample_rate))

    def frame_to_seconds(self, frame: int) -> float:
        rate = self.format.sample_rate
        return frame / rate if rate else 0.0

    # ---------------------------------------------------------------- teardown
    def close(self) -> None:
        """Release the mapping and delete the backing file.

        Windows refuses to unlink a file while any mapping of it is open, and a
        caller may still hold a :meth:`view` result. Since the backing file can
        be gigabytes for a long recording, a silent leak is not acceptable: drop
        our reference, force a collection to reclaim any stray view, then retry.
        Anything still undeletable is swept by :func:`cleanup_orphans` on the
        next launch, so the leak is bounded either way.
        """
        with self._lock:
            if self._closed:
                return
            self._closed = True

            # Dropping the Python reference is NOT enough: numpy keeps the
            # underlying mmap object alive, which holds an OS handle, and
            # Windows refuses to unlink a mapped file. The handle must be
            # closed explicitly or the backing file - potentially gigabytes -
            # leaks for the rest of the session.
            mapping = self._map
            self._map = None
            if mapping is not None:
                handle = getattr(mapping, "_mmap", None)
                if handle is not None:
                    try:
                        handle.close()
                    except (BufferError, ValueError, OSError) as exc:
                        # A live view() still references it; fall through to
                        # the retry below.
                        log.debug("Mapping still referenced: %s", exc)
                del mapping

            if not self._owns_file:
                return

            for attempt in range(2):
                try:
                    self._path.unlink(missing_ok=True)
                    return
                except OSError as exc:
                    if attempt == 0:
                        import gc

                        gc.collect()        # reclaim any lingering view()
                        continue
                    log.debug("Decode buffer %s still mapped (%s); it will be "
                              "removed at next startup", self._path, exc)

    def __del__(self) -> None:            # pragma: no cover - GC timing
        try:
            self.close()
        except Exception:
            pass

    def __repr__(self) -> str:
        return (f"<AudioBuffer {self.duration:.2f}s "
                f"{self.format.sample_rate}Hz x{self.format.channels}>")


def probe_stream_format(ffprobe: str, source: Path) -> AudioFormat:
    """Read sample rate and channel count from the source's first audio stream."""
    result = run_capture(
        [
            ffprobe, "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=sample_rate,channels",
            "-of", "default=noprint_wrappers=1",
            str(source),
        ],
        timeout=30,
    )
    sample_rate, channels = 44100, 2
    if result.returncode == 0:
        for line in (result.stdout or "").splitlines():
            key, _, value = line.partition("=")
            value = value.strip()
            if key == "sample_rate" and value.isdigit():
                sample_rate = int(value)
            elif key == "channels" and value.isdigit():
                channels = int(value)
    # Guard against absurd probe results before they become allocation sizes.
    if not (8000 <= sample_rate <= 384000):
        sample_rate = 44100
    channels = max(1, min(channels, 8))
    return AudioFormat(sample_rate, channels)


def decode(
    ffmpeg: str,
    ffprobe: str,
    source: Path,
    progress: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
    max_channels: int = 2,
) -> AudioBuffer:
    """Decode ``source`` into a memory-mapped :class:`AudioBuffer`.

    Streams FFmpeg's output to disk in chunks, reporting progress against the
    probed duration, and honours cancellation between chunks.
    """
    source = Path(source)
    if not source.is_file():
        raise DecodeError(f"File not found: {source}")

    fmt = probe_stream_format(ffprobe, source)
    channels = min(fmt.channels, max_channels)
    fmt = AudioFormat(fmt.sample_rate, channels)

    duration = probe_duration(ffprobe, source)
    expected_frames = int(duration * fmt.sample_rate) if duration else 0
    expected_bytes = expected_frames * fmt.bytes_per_frame

    scratch = paths.cache_dir() / "decoded"
    scratch.mkdir(parents=True, exist_ok=True)
    target = scratch / f"{uuid.uuid4().hex}.f32"

    cmd = [
        ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error",
        "-i", str(source),
        "-map", "0:a:0",
        "-f", "f32le",
        "-acodec", "pcm_f32le",
        "-ac", str(channels),
        "-ar", str(fmt.sample_rate),
        "-",
    ]

    log.debug("Decoding %s -> %s", source.name, target.name)
    written = 0
    try:
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, **no_window_kwargs(),
        )
    except OSError as exc:
        raise DecodeError(f"Could not start FFmpeg: {exc}") from exc

    try:
        with target.open("wb") as handle:
            assert process.stdout is not None
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    _kill(process)
                    raise DecodeCancelled("Decoding cancelled.")
                chunk = process.stdout.read(_CHUNK)
                if not chunk:
                    break
                handle.write(chunk)
                written += len(chunk)
                if progress and expected_bytes:
                    progress(min(written / expected_bytes, 1.0))
        stderr = process.stderr.read() if process.stderr else ""
        code = process.wait()
    except DecodeCancelled:
        target.unlink(missing_ok=True)
        raise
    except Exception:
        _kill(process)
        target.unlink(missing_ok=True)
        raise

    if code != 0:
        target.unlink(missing_ok=True)
        detail = (stderr or "").strip().splitlines()
        raise DecodeError(f"FFmpeg failed to decode: "
                          f"{detail[-1] if detail else f'exit {code}'}")

    frames = written // fmt.bytes_per_frame
    if frames == 0:
        target.unlink(missing_ok=True)
        raise DecodeError("The file contains no decodable audio.")

    # Truncate any partial trailing frame so the memmap shape is exact.
    exact = frames * fmt.bytes_per_frame
    if written != exact:
        with target.open("r+b") as handle:
            handle.truncate(exact)

    if progress:
        progress(1.0)
    log.info("Decoded %s: %d frames, %d Hz, %d ch",
             source.name, frames, fmt.sample_rate, fmt.channels)
    return AudioBuffer(target, fmt, frames)


def _kill(process: subprocess.Popen) -> None:
    try:
        process.terminate()
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
    except OSError:
        pass


def cleanup_orphans() -> int:
    """Remove decode buffers left behind by a previous crash. Returns the count."""
    scratch = paths.cache_dir() / "decoded"
    if not scratch.is_dir():
        return 0
    removed = 0
    for path in scratch.glob("*.f32"):
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    if removed:
        log.info("Cleaned up %d orphaned decode buffer(s)", removed)
    return removed
