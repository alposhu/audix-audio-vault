"""The Queue: what the user might want, before they decide to take it.

Adding a link must never start a download on its own. A playlist can be hundreds of
tracks and a link can turn out to be something else entirely, so every link lands
here first as a row with a tick beside it. Nothing reaches the download engine until
the user chooses, and tasks only exist from that point on. That is also why a
queued row carries no format or destination: those are decided at the moment of
pressing Download, not when a link happened to be pasted.

The list survives a restart, so a selection built up over an evening is still there
tomorrow.

Threading: reading a link runs on a pool thread, and the outcome returns through a
queued signal. Every row is only ever touched on the main thread.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Union

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot

from audix.core import links
from audix.core.downloader import (
    ExtractionError, MediaEntry, ParentList, ResolvedBatch, Scope, resolve_targets,
)
from audix.core.history import DownloadHistory
from audix.utils import paths

log = logging.getLogger("audix.queue")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class QueueItem:
    """One track the user can tick."""

    entry: MediaEntry
    checked: bool = True
    group_id: str = ""
    already_have: bool = False
    #: The list this video was reached through, offered as a separate choice.
    parent_list: Optional[ParentList] = None
    id: str = field(default_factory=_new_id)


@dataclass
class QueueGroup:
    """A header row for the tracks one playlist link expanded into."""

    title: str
    url: str
    is_mix: bool = False
    expanded: bool = True
    id: str = field(default_factory=_new_id)


@dataclass
class PendingLink:
    """A link still being read, or one that could not be read."""

    url: str
    scope: Scope = Scope.AUTO
    error: str = ""
    id: str = field(default_factory=_new_id)


Row = Union[QueueItem, QueueGroup, PendingLink]


@dataclass(frozen=True)
class LinkAdded:
    """What came of a link, for the confirmation the user sees."""

    count: int
    title: str = ""
    is_playlist: bool = False
    parent_list: Optional[ParentList] = None


class _ResolveSignals(QObject):
    resolved = Signal(str, object)     # pending row id, ResolvedBatch
    failed = Signal(str, str)          # pending row id, message


class _ResolveRunner(QRunnable):
    """Expands a pasted URL into tracks without blocking the UI."""

    def __init__(self, token: str, url: str, scope: Scope, config) -> None:
        super().__init__()
        self.token = token
        self.url = url
        self.scope = scope
        self.config = config
        self.signals = _ResolveSignals()
        self.setAutoDelete(False)

    @Slot()
    def run(self) -> None:  # noqa: D102
        try:
            batch = resolve_targets(self.url, self.config, self.scope)
            self.signals.resolved.emit(self.token, batch)
        except ExtractionError as exc:
            self.signals.failed.emit(self.token, str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("URL resolution failed")
            self.signals.failed.emit(self.token, str(exc) or "Could not read that URL.")


class LinkQueue(QObject):
    """An ordered list of tickable tracks, grouped by the link they came from."""

    changed = Signal()                 # rows were added, removed, or reordered
    checks_changed = Signal()          # only the ticks moved
    link_added = Signal(object)        # LinkAdded
    link_failed = Signal(str, str)     # url, message
    notice = Signal(str)               # something worth saying that is not a failure

    def __init__(self, config, history: Optional[DownloadHistory] = None,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.config = config
        self.history = history
        self._rows: List[Row] = []
        self._runners: Dict[str, _ResolveRunner] = {}

        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(3)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self.save)

        self._load()

    # ------------------------------------------------------------------ queries
    def rows(self) -> List[Row]:
        return list(self._rows)

    def visible_rows(self) -> List[Row]:
        """Every row, minus the tracks of collapsed playlists."""
        collapsed = {row.id for row in self._rows
                     if isinstance(row, QueueGroup) and not row.expanded}
        return [row for row in self._rows
                if not (isinstance(row, QueueItem) and row.group_id in collapsed)]

    def items(self) -> List[QueueItem]:
        return [row for row in self._rows if isinstance(row, QueueItem)]

    def checked_items(self) -> List[QueueItem]:
        return [item for item in self.items() if item.checked]

    def group_items(self, group_id: str) -> List[QueueItem]:
        return [item for item in self.items() if item.group_id == group_id]

    def group_duration(self, group_id: str) -> float:
        return sum(item.entry.duration or 0.0 for item in self.group_items(group_id))

    def is_empty(self) -> bool:
        return not self._rows

    def contains_video(self, video_id: str) -> bool:
        return bool(video_id) and any(
            item.entry.video_id == video_id for item in self.items()
        )

    # ------------------------------------------------------------------- adding
    def add_text(self, text: str) -> int:
        """Queue every link found in ``text``. Returns how many were found."""
        found = links.find_links(text)
        for url in found:
            self.add_link(url)
        return len(found)

    def add_link(self, url: str, scope: Scope = Scope.AUTO) -> None:
        """Read ``url`` on a worker; its rows appear here once that finishes."""
        link = links.parse(url)
        if scope is Scope.AUTO and link.has_video and self.contains_video(link.video_id):
            self.notice.emit("That video is already in your Queue.")
            return
        pending = PendingLink(url=url, scope=scope)
        self._rows.append(pending)
        self._start_reading(pending)
        self._commit()

    def add_entry(self, entry: MediaEntry,
                  parent_list: Optional[ParentList] = None) -> bool:
        """Queue a track whose details are already known, skipping the read."""
        if self.contains_video(entry.video_id):
            self.notice.emit("That video is already in your Queue.")
            return False
        self._rows.append(QueueItem(
            entry=entry,
            already_have=self._already_have(entry.video_id),
            parent_list=parent_list,
        ))
        self._commit()
        return True

    def return_entries(self, entries: Iterable[MediaEntry]) -> None:
        """Take back tracks that never finished, ticked and ready to run again."""
        for entry in entries:
            if not self.contains_video(entry.video_id):
                self._rows.append(QueueItem(entry=entry))
        self._commit()

    def retry(self, row_id: str) -> None:
        pending = self._find(row_id)
        if isinstance(pending, PendingLink) and pending.error:
            pending.error = ""
            self._start_reading(pending)
            self._commit()

    # ----------------------------------------------------------------- removing
    def remove(self, row_ids: Iterable[str]) -> None:
        """Remove rows. Removing a playlist header removes its tracks with it."""
        doomed: Set[str] = set(row_ids)
        doomed.update(item.id for item in self.items() if item.group_id in doomed)
        self._rows = [row for row in self._rows if row.id not in doomed]
        self._drop_empty_groups()
        self._commit()

    def remove_checked(self) -> int:
        doomed = [item.id for item in self.checked_items()]
        self.remove(doomed)
        return len(doomed)

    def clear(self) -> None:
        self._rows = []
        self._commit()

    def take(self, item_ids: Iterable[str]) -> List[MediaEntry]:
        """Remove tracks from the Queue and hand them over to be downloaded."""
        wanted = set(item_ids)
        entries = [item.entry for item in self.items() if item.id in wanted]
        self.remove(wanted)
        return entries

    # ------------------------------------------------------------------- ticking
    def set_checked(self, item_ids: Iterable[str], checked: bool) -> None:
        wanted = set(item_ids)
        for item in self.items():
            if item.id in wanted:
                item.checked = checked
        self._commit_checks()

    def set_all_checked(self, checked: bool) -> None:
        for item in self.items():
            item.checked = checked
        self._commit_checks()

    def invert_checks(self) -> None:
        for item in self.items():
            item.checked = not item.checked
        self._commit_checks()

    def toggle_group(self, group_id: str) -> None:
        """Tick the whole playlist, unless it is already fully ticked."""
        items = self.group_items(group_id)
        target = not all(item.checked for item in items)
        for item in items:
            item.checked = target
        self._commit_checks()

    def set_group_expanded(self, group_id: str, expanded: bool) -> None:
        group = self._find(group_id)
        if isinstance(group, QueueGroup):
            group.expanded = expanded
            self._commit()

    # ---------------------------------------------------------------- persistence
    def save(self) -> None:
        self._save_timer.stop()
        target = paths.queue_file()
        temporary = target.with_suffix(".tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps({"rows": [_row_to_dict(row) for row in self._rows]},
                           ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(temporary, target)
        except OSError as exc:
            log.warning("Could not save the Queue: %s", exc)

    def shutdown(self) -> None:
        self.save()
        self._pool.waitForDone(2000)
        self._runners.clear()

    def _load(self) -> None:
        target = paths.queue_file()
        if not target.is_file():
            return
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
            self._rows = [row for row in map(_row_from_dict, raw.get("rows", [])) if row]
        except (ValueError, OSError, AttributeError) as exc:
            log.warning("Could not read the saved Queue (%s); starting empty", exc)
            self._rows = []
        for row in self._rows:
            if isinstance(row, PendingLink) and not row.error:
                self._start_reading(row)

    # --------------------------------------------------------------- resolution
    def _start_reading(self, pending: PendingLink) -> None:
        runner = _ResolveRunner(pending.id, pending.url, pending.scope, self.config)
        runner.signals.resolved.connect(self._on_resolved)
        runner.signals.failed.connect(self._on_failed)
        self._runners[pending.id] = runner
        self._pool.start(runner)

    @Slot(str, object)
    def _on_resolved(self, token: str, batch: ResolvedBatch) -> None:
        self._runners.pop(token, None)
        pending = self._find(token)
        if not isinstance(pending, PendingLink):
            return                  # removed while it was still being read

        rows = self._rows_for(batch, pending)
        position = self._rows.index(pending)
        self._rows[position:position + 1] = rows
        self._commit()

        added = sum(isinstance(row, QueueItem) for row in rows)
        if added:
            self.link_added.emit(LinkAdded(
                count=added,
                title=batch.playlist_title or batch.entries[0].title,
                is_playlist=batch.is_playlist,
                parent_list=batch.parent_list,
            ))
        else:
            self.notice.emit("Everything on that link is already in your Queue.")

    @Slot(str, str)
    def _on_failed(self, token: str, message: str) -> None:
        self._runners.pop(token, None)
        pending = self._find(token)
        if not isinstance(pending, PendingLink):
            return
        pending.error = message
        self._commit()
        self.link_failed.emit(pending.url, message)

    def _rows_for(self, batch: ResolvedBatch, pending: PendingLink) -> List[Row]:
        known = {item.entry.video_id for item in self.items()}
        fresh = []
        for entry in batch.entries:
            if not entry.video_id or entry.video_id not in known:
                fresh.append(entry)
                known.add(entry.video_id)

        if not batch.is_playlist:
            return [
                QueueItem(entry=entry, parent_list=batch.parent_list,
                          already_have=self._already_have(entry.video_id))
                for entry in fresh
            ]
        if not fresh:
            return []

        group = QueueGroup(title=batch.playlist_title, url=pending.url,
                           is_mix=batch.is_mix)
        rows: List[Row] = [group]
        for entry in fresh:
            # Tracks you already own arrive unticked, so a re-run of a playlist
            # fetches only what is new. The tick stays one click away.
            have = self._already_have(entry.video_id)
            rows.append(QueueItem(entry=entry, group_id=group.id, checked=not have,
                                  already_have=have))
        return rows

    # ----------------------------------------------------------------- internals
    def _already_have(self, video_id: str) -> bool:
        return self.history is not None and self.history.has(video_id)

    def _find(self, row_id: str) -> Optional[Row]:
        return next((row for row in self._rows if row.id == row_id), None)

    def _drop_empty_groups(self) -> None:
        occupied = {row.group_id for row in self._rows if isinstance(row, QueueItem)}
        self._rows = [row for row in self._rows
                      if not isinstance(row, QueueGroup) or row.id in occupied]

    def _commit(self) -> None:
        self.changed.emit()
        self._save_timer.start()

    def _commit_checks(self) -> None:
        self.checks_changed.emit()
        self._save_timer.start()


def _row_to_dict(row: Row) -> dict:
    if isinstance(row, QueueItem):
        return {
            "kind": "item",
            "id": row.id,
            "entry": row.entry.to_dict(),
            "checked": row.checked,
            "group_id": row.group_id,
            "already_have": row.already_have,
            "parent_list": _parent_to_dict(row.parent_list),
        }
    if isinstance(row, QueueGroup):
        return {"kind": "group", "id": row.id, "title": row.title, "url": row.url,
                "is_mix": row.is_mix, "expanded": row.expanded}
    return {"kind": "pending", "id": row.id, "url": row.url,
            "scope": row.scope.value, "error": row.error}


def _row_from_dict(raw: dict) -> Optional[Row]:
    kind = raw.get("kind")
    try:
        if kind == "item":
            return QueueItem(
                entry=MediaEntry.from_dict(raw["entry"]),
                checked=bool(raw.get("checked", True)),
                group_id=raw.get("group_id", ""),
                already_have=bool(raw.get("already_have", False)),
                parent_list=_parent_from_dict(raw.get("parent_list")),
                id=raw.get("id") or _new_id(),
            )
        if kind == "group":
            return QueueGroup(title=raw["title"], url=raw["url"],
                              is_mix=bool(raw.get("is_mix", False)),
                              expanded=bool(raw.get("expanded", True)),
                              id=raw.get("id") or _new_id())
        if kind == "pending":
            return PendingLink(url=raw["url"], scope=Scope(raw.get("scope", "auto")),
                               error=raw.get("error", ""), id=raw.get("id") or _new_id())
    except (KeyError, TypeError, ValueError) as exc:
        log.debug("Skipping unreadable Queue row: %s", exc)
    return None


def _parent_to_dict(parent: Optional[ParentList]) -> Optional[dict]:
    if parent is None:
        return None
    return {"url": parent.url, "list_id": parent.list_id, "is_mix": parent.is_mix}


def _parent_from_dict(raw: Optional[dict]) -> Optional[ParentList]:
    if not raw:
        return None
    return ParentList(url=raw["url"], list_id=raw["list_id"],
                      is_mix=bool(raw.get("is_mix", False)))
