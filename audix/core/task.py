"""The queue's unit of work.

Defined in its own module so both the pipeline (which executes tasks) and the queue
manager (which schedules them) can depend on it without importing each other.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from audix.core.downloader import MediaEntry


class TaskState(str, Enum):
    PENDING = "Pending"
    RESOLVING = "Resolving"
    DOWNLOADING = "Downloading"
    CONVERTING = "Converting"
    TAGGING = "Tagging"
    COMPLETED = "Completed"
    FAILED = "Failed"
    CANCELLED = "Cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED)

    @property
    def is_active(self) -> bool:
        return self in (
            TaskState.RESOLVING,
            TaskState.DOWNLOADING,
            TaskState.CONVERTING,
            TaskState.TAGGING,
        )


@dataclass
class DownloadTask:
    """One track to extract, convert, and tag."""

    entry: MediaEntry
    audio_format: str
    bitrate: str
    output_dir: str

    # tagging behaviour, snapshotted from settings when the task was queued
    embed_metadata: bool = True
    embed_thumbnail: bool = True
    write_track_numbers: bool = True
    keep_source_file: bool = False
    filename_template: str = "{title}"

    # identity and live state
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    state: TaskState = TaskState.PENDING
    progress: float = 0.0                     # 0.0 - 1.0, whole pipeline
    speed: Optional[float] = None             # bytes/sec
    eta: Optional[float] = None               # seconds
    message: str = ""
    output_path: str = ""

    #: The yt-dlp info dict this download produced. Retained so the editor can
    #: read chapters, artwork, and tags without re-fetching - the thing a
    #: standalone audio editor structurally cannot do.
    source_info: dict = field(default_factory=dict, repr=False)

    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)

    # ------------------------------------------------------------------ helpers
    @property
    def title(self) -> str:
        return self.entry.title or "Untitled"

    @property
    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def cancel(self) -> None:
        self.cancel_event.set()

    def reset_for_retry(self) -> None:
        self.cancel_event = threading.Event()
        self.state = TaskState.PENDING
        self.progress = 0.0
        self.speed = None
        self.eta = None
        self.message = ""
        self.output_path = ""
