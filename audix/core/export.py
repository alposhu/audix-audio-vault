"""Export orchestration: render, split, and tag.

Wraps :mod:`audix.core.render` with the parts that need to happen around it —
the loudness measurement pass, chapter splitting, per-track metadata, and cover
art — and runs the whole thing on a pool thread with progress and cancellation.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from audix.core import formats, metadata
from audix.core.chapters import Chapter
from audix.core.converter import ConversionCancelled
from audix.core.edits import EditState, NormalizeMode
from audix.core.ffmpeg_manager import FFmpegManager
from audix.core.metadata import TrackMetadata
from audix.core.render import RenderRequest, Renderer
from audix.utils import naming

log = logging.getLogger("audix.export")


@dataclass
class ExportJob:
    """One export, which may produce a single file or a whole chapter split."""

    source: Path
    destination: Path                 # a file when single, a folder when split
    state: EditState
    audio_format: str
    bitrate: str
    source_duration: float
    chapters: List[Chapter] = field(default_factory=list)
    info: Dict[str, Any] = field(default_factory=dict)
    split: bool = False
    embed_metadata: bool = True
    embed_thumbnail: bool = True

    @property
    def track_count(self) -> int:
        return len(self.chapters) if self.split and self.chapters else 1

    @classmethod
    def from_dict(cls, payload: Dict[str, Any], config) -> "ExportJob":
        return cls(
            source=Path(payload["source"]),
            destination=Path(payload["destination"]),
            state=payload["state"],
            audio_format=payload["audio_format"],
            bitrate=payload["bitrate"],
            source_duration=float(payload["source_duration"]),
            chapters=list(payload.get("chapters") or []),
            info=dict(payload.get("info") or {}),
            split=bool(payload.get("split")),
            embed_metadata=bool(getattr(config, "embed_metadata", True)),
            embed_thumbnail=bool(getattr(config, "embed_thumbnail", True)),
        )


class ExportSignals(QObject):
    progress = Signal(float, str)          # 0..1, stage description
    finished = Signal(list)                # written paths
    failed = Signal(str)
    cancelled = Signal()


class ExportRunner(QRunnable):
    """Runs an :class:`ExportJob` on a pool thread."""

    def __init__(self, job: ExportJob, ffmpeg: FFmpegManager) -> None:
        super().__init__()
        self.job = job
        self.ffmpeg = ffmpeg
        self.signals = ExportSignals()
        self.cancel_event = threading.Event()
        self.setAutoDelete(False)

    def cancel(self) -> None:
        self.cancel_event.set()

    @Slot()
    def run(self) -> None:  # noqa: D102
        try:
            written = self._execute()
        except ConversionCancelled:
            self.signals.cancelled.emit()
            return
        except Exception as exc:  # noqa: BLE001 - report, never crash the pool
            log.exception("Export failed")
            self.signals.failed.emit(str(exc) or exc.__class__.__name__)
            return
        self.signals.finished.emit([str(p) for p in written])

    # ---------------------------------------------------------------- internals
    def _execute(self) -> List[Path]:
        job = self.job
        renderer = Renderer(self.ffmpeg.ffmpeg(), self.ffmpeg.ffprobe())

        # Loudness needs a measurement pass before the corrective render.
        measurement = None
        if job.state.normalize is not NormalizeMode.NONE:
            self.signals.progress.emit(0.02, "Measuring loudness")
            measurement = renderer.measure_if_needed(
                RenderRequest(job.source, job.destination, job.state,
                              job.audio_format, job.bitrate, job.source_duration)
            )
        self._check_cancelled()

        cover = None
        if job.embed_metadata and job.embed_thumbnail and job.info:
            self.signals.progress.emit(0.05, "Fetching cover art")
            cover = metadata.fetch_cover(
                metadata.best_thumbnail_url(job.info),
                ffmpeg_path=self.ffmpeg.ffmpeg(),
            )

        if job.split and job.chapters:
            return self._export_split(renderer, measurement, cover)
        return self._export_single(renderer, measurement, cover)

    def _export_single(self, renderer: Renderer, measurement, cover) -> List[Path]:
        job = self.job
        fmt = formats.get(job.audio_format)
        destination = job.destination
        if destination.suffix.lower().lstrip(".") != fmt.ext:
            destination = destination.with_suffix(f".{fmt.ext}")
        destination = naming.unique_path(destination)

        request = RenderRequest(
            source=job.source, destination=destination, state=job.state,
            audio_format=job.audio_format, bitrate=job.bitrate,
            source_duration=job.source_duration,
        )
        renderer.render(
            request,
            progress=lambda f: self.signals.progress.emit(
                0.1 + f * 0.85, "Rendering audio"),
            cancel_event=self.cancel_event,
            measurement=measurement,
        )

        if job.embed_metadata:
            self.signals.progress.emit(0.97, "Writing tags")
            meta = TrackMetadata.from_info(job.info) if job.info else TrackMetadata(
                title=job.source.stem)
            meta.cover = cover
            metadata.apply_tags(destination, meta, embed_cover=job.embed_thumbnail)

        self.signals.progress.emit(1.0, "Done")
        return [destination]

    def _export_split(self, renderer: Renderer, measurement, cover) -> List[Path]:
        """Write one tagged file per chapter.

        Chapter times are on the source timeline; they are mapped through the
        edit so a trim or a cut earlier in the file shifts them correctly.
        """
        from audix.core.render import map_to_output

        job = self.job
        fmt = formats.get(job.audio_format)
        folder = job.destination
        folder.mkdir(parents=True, exist_ok=True)

        album = (job.info.get("playlist_title") or job.info.get("album")
                 or job.info.get("title") or job.source.stem)
        artist = (job.info.get("artist") or job.info.get("uploader")
                  or job.info.get("channel") or "")
        year = _year_from(job.info)

        total = len(job.chapters)
        written: List[Path] = []

        for position, chapter in enumerate(job.chapters, start=1):
            self._check_cancelled()
            base = 0.05 + (position - 1) / total * 0.9

            start = map_to_output(job.state, chapter.start, job.source_duration)
            end = map_to_output(job.state, chapter.end, job.source_duration)
            if end - start < 0.05:
                log.info("Skipping chapter %d: removed by the current edit",
                         chapter.index)
                continue

            destination = naming.unique_path(
                folder / f"{chapter.filename_stem(total)}.{fmt.ext}")

            request = RenderRequest(
                source=job.source, destination=destination, state=job.state,
                audio_format=job.audio_format, bitrate=job.bitrate,
                source_duration=job.source_duration, segment=(start, end),
            )
            renderer.render(
                request,
                progress=lambda f, b=base: self.signals.progress.emit(
                    b + f * (0.9 / total),
                    f"Rendering track {position} of {total}"),
                cancel_event=self.cancel_event,
                measurement=measurement,
            )

            if job.embed_metadata:
                meta = TrackMetadata(
                    title=chapter.title,
                    artist=artist,
                    album=album,
                    album_artist=artist,
                    year=year,
                    track_number=chapter.index,
                    track_total=total,
                    comment=str(job.info.get("webpage_url") or ""),
                    cover=cover,
                )
                metadata.apply_tags(destination, meta,
                                    embed_cover=job.embed_thumbnail)
            written.append(destination)

        if not written:
            raise RuntimeError(
                "The current edit removes every chapter, so nothing was written."
            )
        self.signals.progress.emit(1.0, "Done")
        log.info("Split export wrote %d track(s) to %s", len(written), folder)
        return written

    def _check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise ConversionCancelled("Export cancelled.")


def _year_from(info: Dict[str, Any]) -> str:
    for key in ("release_year", "release_date", "upload_date"):
        value = info.get(key)
        if value and len(str(value)) >= 4 and str(value)[:4].isdigit():
            return str(value)[:4]
    return ""
