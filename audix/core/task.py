"""The download engine's unit of work.

Defined in its own module so both the pipeline (which executes tasks) and the
download manager (which schedules them) can depend on it without importing each
other.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from audix.core.downloader import MediaEntry


class TaskState(str, Enum):
    PENDING = "Waiting"
    PAUSED = "Paused"
    RESOLVING = "Preparing"
    DOWNLOADING = "Downloading"
    CONVERTING = "Converting"
    TAGGING = "Tagging"
    COMPLETED = "Finished"
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

    @property
    def can_pause(self) -> bool:
        """FFmpeg cannot be suspended, so a task stops being pausable once it converts."""
        return self in (TaskState.PENDING, TaskState.RESOLVING, TaskState.DOWNLOADING)


#: The stages a task passes through, in order, as the UI's signal path shows them.
STAGES: List[TaskState] = [
    TaskState.RESOLVING,
    TaskState.DOWNLOADING,
    TaskState.CONVERTING,
    TaskState.TAGGING,
]


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

    # the detail the Downloads page shows
    downloaded_bytes: int = 0
    total_bytes: int = 0
    output_bytes: int = 0
    source_format: str = ""                   # the stream fetched, e.g. opus 129 kbps
    added_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    #: Stage name -> [entered, left] as epoch seconds.
    stage_times: Dict[str, List[float]] = field(default_factory=dict)

    #: The yt-dlp info dict this download produced. Retained so the editor can
    #: read chapters, artwork, and tags without re-fetching - the thing a
    #: standalone audio editor structurally cannot do.
    source_info: dict = field(default_factory=dict, repr=False)

    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    pause_event: threading.Event = field(default_factory=threading.Event, repr=False)

    # ------------------------------------------------------------------ helpers
    @property
    def title(self) -> str:
        return self.entry.title or "Untitled"

    @property
    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    @property
    def elapsed(self) -> Optional[float]:
        if self.started_at is None:
            return None
        return (self.finished_at or time.time()) - self.started_at

    def cancel(self) -> None:
        self.cancel_event.set()

    def request_pause(self) -> None:
        self.pause_event.set()

    def clear_pause(self) -> None:
        self.pause_event = threading.Event()

    def enter_stage(self, state: TaskState) -> None:
        """Record the moment a stage began, closing whichever one was open."""
        now = time.time()
        if self.started_at is None:
            self.started_at = now
        key = state.name
        for name, times in self.stage_times.items():
            if name != key and len(times) == 1:
                times.append(now)
        if key in self.stage_times:
            del self.stage_times[key][1:]       # a resume reopens the stage
        elif state in STAGES:
            self.stage_times[key] = [now]

    def close_stages(self) -> None:
        now = time.time()
        for times in self.stage_times.values():
            if len(times) == 1:
                times.append(now)

    def reset_for_retry(self) -> None:
        self.cancel_event = threading.Event()
        self.pause_event = threading.Event()
        self.state = TaskState.PENDING
        self.progress = 0.0
        self.speed = None
        self.eta = None
        self.message = ""
        self.output_path = ""
        self.output_bytes = 0
        self.started_at = None
        self.finished_at = None
        self.stage_times = {}
