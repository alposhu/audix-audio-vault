"""Finished downloads, remembered between sessions.

Two jobs depend on this: the Downloads page reopens with what you already fetched,
and the Queue can tell you when a track is one you already have.

Records are one JSON object per line, so finishing a track only appends and a crash
mid-write costs at most that last line.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from audix.core.downloader import MediaEntry
from audix.core.task import DownloadTask, TaskState
from audix.utils import paths

log = logging.getLogger("audix.history")

#: Oldest records fall off past this, so the file cannot grow without bound.
MAX_RECORDS = 2000

#: What the editor reads from a yt-dlp info dict. Keeping these means reopening an
#: old download still offers chapters and correct tags, without storing the
#: multi-kilobyte format list that makes up most of a full info dict.
_KEPT_INFO_FIELDS = (
    "id", "title", "track", "artist", "creator", "uploader", "channel", "album",
    "album_artist", "duration", "chapters", "description", "webpage_url", "thumbnail",
    "release_year", "release_date", "upload_date", "playlist_title",
)


class DownloadHistory:
    """An append-mostly log of finished downloads, keyed by task id."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path or paths.history_file()
        self._records: Dict[str, Dict[str, Any]] = {}
        self._load()

    # ------------------------------------------------------------------ queries
    def __len__(self) -> int:
        return len(self._records)

    def has(self, video_id: str) -> bool:
        return bool(video_id) and any(
            record["entry"].get("video_id") == video_id
            for record in self._records.values()
        )

    def tasks(self) -> List[DownloadTask]:
        """Every record as a finished task, oldest first."""
        return [_to_task(record) for record in self._records.values()]

    # ------------------------------------------------------------------ changes
    def add(self, task: DownloadTask) -> None:
        record = _to_record(task)
        self._records[task.id] = record
        if len(self._records) > MAX_RECORDS:
            for stale in list(self._records)[:-MAX_RECORDS]:
                del self._records[stale]
            self._rewrite()
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            log.warning("Could not record finished download: %s", exc)

    def remove(self, task_ids: Iterable[str]) -> None:
        removed = [self._records.pop(tid, None) for tid in task_ids]
        if any(record is not None for record in removed):
            self._rewrite()

    # ---------------------------------------------------------------- persistence
    def _load(self) -> None:
        if not self._path.is_file():
            return
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            log.warning("Could not read download history: %s", exc)
            return
        for line in lines[-MAX_RECORDS:]:
            try:
                record = json.loads(line)
                self._records[record["id"]] = record
                record["entry"]["url"]              # proves the record is whole
            except (ValueError, KeyError, TypeError):
                continue    # a torn final line from a crash; the rest still load

    def _rewrite(self) -> None:
        temporary = self._path.with_suffix(".tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                for record in self._records.values():
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            os.replace(temporary, self._path)
        except OSError as exc:
            log.warning("Could not update download history: %s", exc)


def _to_record(task: DownloadTask) -> Dict[str, Any]:
    info = {key: task.source_info[key] for key in _KEPT_INFO_FIELDS
            if task.source_info.get(key) is not None}
    return {
        "id": task.id,
        "entry": task.entry.to_dict(),
        "audio_format": task.audio_format,
        "bitrate": task.bitrate,
        "output_dir": task.output_dir,
        "output_path": task.output_path,
        "output_bytes": task.output_bytes,
        "source_format": task.source_format,
        "added_at": task.added_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "stage_times": task.stage_times,
        "info": info,
    }


def _to_task(record: Dict[str, Any]) -> DownloadTask:
    size = int(record.get("output_bytes") or 0)
    return DownloadTask(
        entry=MediaEntry.from_dict(record["entry"]),
        audio_format=record.get("audio_format", "mp3"),
        bitrate=record.get("bitrate", "320"),
        output_dir=record.get("output_dir", ""),
        id=record["id"],
        state=TaskState.COMPLETED,
        progress=1.0,
        message="Finished",
        output_path=record.get("output_path", ""),
        output_bytes=size,
        source_format=record.get("source_format", ""),
        added_at=record.get("added_at") or 0.0,
        started_at=record.get("started_at"),
        finished_at=record.get("finished_at"),
        stage_times=record.get("stage_times") or {},
        source_info=record.get("info") or {},
    )
