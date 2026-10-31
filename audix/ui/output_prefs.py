"""Where audio goes and what it becomes: one answer, shared by every page.

The Queue's transport strip, the browser's dock, and Settings all show and change
the same format, quality, folder, and parallelism. Keeping them here means none of
those pages can disagree, and a change on one is true on the others straight away.
Tasks are stamped from this at the moment of pressing Download, so changing a
setting afterwards never alters a run that has already started.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Tuple

from PySide6.QtCore import QObject, Signal

from audix.core import formats
from audix.core.download_manager import MAX_PARALLEL
from audix.core.downloader import MediaEntry
from audix.core.task import DownloadTask

#: The choices a parallelism selector offers: (value, label).
PARALLEL_CHOICES: List[Tuple[int, str]] = [
    (1, "One at a time"),
    (2, "2 at a time"),
    (3, "3 at a time"),
    (4, "4 at a time"),
    (6, "6 at a time"),
    (8, "8 at a time"),
    (12, "12 at a time"),
    (MAX_PARALLEL, "All at once"),
]

PARALLEL_TOOLTIP = (
    f"How many tracks download together. All at once runs up to {MAX_PARALLEL}; "
    "past that YouTube starts refusing requests."
)


class OutputPrefs(QObject):
    """The current output settings, written through to the config."""

    changed = Signal()

    def __init__(self, config, parent: QObject = None) -> None:
        super().__init__(parent)
        self.config = config

    # ------------------------------------------------------------------ reading
    @property
    def audio_format(self) -> str:
        return self.config.audio_format

    @property
    def bitrate(self) -> str:
        return self.config.bitrate

    @property
    def output_dir(self) -> str:
        return self.config.output_dir

    @property
    def parallel(self) -> int:
        return self.config.concurrent_downloads

    def describe(self) -> str:
        """``MP3 · 320 kbps``, the short form shown wherever space is tight."""
        fmt = formats.get(self.audio_format)
        if fmt.lossless:
            return f"{fmt.label} · lossless"
        if self.bitrate == formats.NATIVE_BITRATE:
            return f"{fmt.label} · source bitrate"
        return f"{fmt.label} · {self.bitrate} kbps"

    # ------------------------------------------------------------------ changing
    def set_format(self, audio_format: str, bitrate: str) -> None:
        if (audio_format, bitrate) != (self.audio_format, self.bitrate):
            self.config.update(audio_format=audio_format, bitrate=bitrate)
            self.changed.emit()

    def set_output_dir(self, folder: str) -> None:
        if folder and folder != self.output_dir:
            self.config.update(output_dir=folder)
            self.changed.emit()

    def set_parallel(self, value: int) -> None:
        if value != self.parallel:
            self.config.update(concurrent_downloads=value)
            self.changed.emit()

    def refresh(self) -> None:
        """Tell every page that Settings rewrote the config underneath them."""
        self.changed.emit()

    # ---------------------------------------------------------------------- tasks
    def make_tasks(self, entries: Iterable[MediaEntry]) -> List[DownloadTask]:
        """Stamp tracks with the current settings, ready for the download engine."""
        config = self.config
        Path(config.output_dir).expanduser().mkdir(parents=True, exist_ok=True)
        return [
            DownloadTask(
                entry=entry,
                audio_format=config.audio_format,
                bitrate=config.bitrate,
                output_dir=config.output_dir,
                embed_metadata=config.embed_metadata,
                embed_thumbnail=config.embed_thumbnail,
                write_track_numbers=config.write_track_numbers,
                keep_source_file=config.keep_source_file,
                filename_template=config.filename_template,
            )
            for entry in entries
        ]
