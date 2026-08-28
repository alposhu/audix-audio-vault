"""The extract → convert → tag pipeline for a single task.

This is the seam where the downloader, converter and tagger meet. It owns the
temporary working file, the progress weighting across the three stages, and the
cleanup guarantees (a cancelled or failed job must not leave debris behind).

Deliberately Qt-free: it takes plain callbacks, so it can be driven from a thread
pool, a CLI, or a test.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Callable, Optional

from audix.core import formats, metadata
from audix.core.converter import AudioConverter, ConversionCancelled
from audix.core.downloader import DownloadCancelled, YoutubeDownloader
from audix.core.ffmpeg_manager import FFmpegManager
from audix.core.metadata import TrackMetadata
from audix.core.task import DownloadTask, TaskState
from audix.utils import naming, paths

log = logging.getLogger("audix.pipeline")

# (state, overall fraction, speed bytes/s or None, eta seconds or None)
StageCallback = Callable[[TaskState, float, Optional[float], Optional[float]], None]

# How much of the overall progress bar each stage owns.
_DOWNLOAD_SHARE = 0.75
_CONVERT_SHARE = 0.22
# The remaining 0.03 covers tagging and the move into place.


class PipelineCancelled(RuntimeError):
    """The task was cancelled; nothing was left on disk."""


class AudioPipeline:
    """Executes one :class:`DownloadTask` end to end."""

    def __init__(self, ffmpeg: FFmpegManager, config) -> None:
        if not ffmpeg.ready:
            raise RuntimeError(
                "FFmpeg is not ready. Downloads cannot start before setup completes."
            )
        self.ffmpeg = ffmpeg
        self.config = config
        self.downloader = YoutubeDownloader(config)
        self.converter = AudioConverter(ffmpeg.ffmpeg(), ffmpeg.ffprobe())

    # ------------------------------------------------------------------ public
    def process(self, task: DownloadTask, on_stage: Optional[StageCallback] = None) -> Path:
        """Run the full pipeline and return the finished file's path."""
        report = on_stage or (lambda *_args: None)
        working_dir = paths.cache_dir()
        source: Optional[Path] = None
        destination: Optional[Path] = None

        try:
            # -- 1. download ---------------------------------------------------
            report(TaskState.DOWNLOADING, 0.0, None, None)

            def download_progress(fraction: float, speed, eta) -> None:
                report(TaskState.DOWNLOADING, fraction * _DOWNLOAD_SHARE, speed, eta)

            media = self.downloader.download(
                entry=task.entry,
                working_dir=working_dir,
                job_id=task.id,
                progress=download_progress,
                cancel_event=task.cancel_event,
            )
            source = media.path
            # Keep the info dict on the task so the editor can offer chapter
            # splitting and correct tags without another network round-trip.
            task.source_info = media.info
            self._check_cancelled(task)

            # -- 2. resolve names and metadata --------------------------------
            meta = self._build_metadata(task, media.info)
            destination = self._resolve_destination(task, meta, media.info)

            # -- 3. convert ----------------------------------------------------
            report(TaskState.CONVERTING, _DOWNLOAD_SHARE, None, None)

            def convert_progress(fraction: float) -> None:
                report(
                    TaskState.CONVERTING,
                    _DOWNLOAD_SHARE + fraction * _CONVERT_SHARE,
                    None,
                    None,
                )

            result = self.converter.convert(
                source=source,
                destination=destination,
                audio_format=task.audio_format,
                bitrate=task.bitrate,
                duration=media.duration,
                progress=convert_progress,
                cancel_event=task.cancel_event,
            )
            self._check_cancelled(task)

            # -- 4. tag --------------------------------------------------------
            if task.embed_metadata:
                report(TaskState.TAGGING, _DOWNLOAD_SHARE + _CONVERT_SHARE, None, None)
                if task.embed_thumbnail:
                    meta.cover = metadata.fetch_cover(
                        metadata.best_thumbnail_url(media.info),
                        ffmpeg_path=self.ffmpeg.ffmpeg(),
                    )
                metadata.apply_tags(result.output_path, meta,
                                    embed_cover=task.embed_thumbnail)

            report(TaskState.COMPLETED, 1.0, None, 0.0)
            log.info("Finished %s -> %s (%s)", task.title, result.output_path.name,
                     result.effective_bitrate)
            return result.output_path

        except (DownloadCancelled, ConversionCancelled) as exc:
            self._discard(destination)
            raise PipelineCancelled(str(exc)) from exc
        except Exception:
            self._discard(destination)
            raise
        finally:
            if source is not None and not task.keep_source_file:
                self._discard(source)
            elif source is not None and task.keep_source_file:
                self._preserve_source(task, source)

    # --------------------------------------------------------------- internals
    def _build_metadata(self, task: DownloadTask, info: dict) -> TrackMetadata:
        entry = task.entry
        track_number = entry.playlist_index if task.write_track_numbers else None
        track_total = entry.playlist_count if task.write_track_numbers else None
        return TrackMetadata.from_info(
            info,
            playlist_title=entry.playlist_title,
            track_number=track_number,
            track_total=track_total,
        )

    def _resolve_destination(self, task: DownloadTask, meta: TrackMetadata,
                             info: dict) -> Path:
        """Decide the final file path, creating the playlist subfolder if needed."""
        fmt = formats.get(task.audio_format)
        root = Path(task.output_dir).expanduser()

        if task.entry.is_playlist_item and task.entry.playlist_title:
            root = root / naming.sanitize_filename(task.entry.playlist_title, "Playlist")
        root.mkdir(parents=True, exist_ok=True)

        stem = naming.render_template(
            task.filename_template,
            {
                "index": task.entry.playlist_index,
                "title": meta.title or task.title,
                "artist": meta.artist,
                "album": meta.album,
                "year": meta.year,
                "id": info.get("id") or task.entry.video_id,
            },
        )
        return naming.unique_path(root / f"{stem}.{fmt.ext}")

    @staticmethod
    def _check_cancelled(task: DownloadTask) -> None:
        if task.is_cancelled:
            raise PipelineCancelled("Cancelled by user.")

    @staticmethod
    def _discard(path: Optional[Path]) -> None:
        if path is None:
            return
        try:
            Path(path).unlink(missing_ok=True)
        except OSError as exc:
            log.debug("Could not remove %s: %s", path, exc)

    def _preserve_source(self, task: DownloadTask, source: Path) -> None:
        """Move the untouched source stream next to the converted output."""
        try:
            target_dir = Path(task.output_dir).expanduser() / "_source"
            target_dir.mkdir(parents=True, exist_ok=True)
            stem = naming.sanitize_filename(task.title, task.id)
            target = naming.unique_path(target_dir / f"{stem}{source.suffix}")
            shutil.move(str(source), str(target))
        except OSError as exc:
            log.warning("Could not keep source file for %s: %s", task.title, exc)
            self._discard(source)
