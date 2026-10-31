"""Parallel download engine built on ``QThreadPool``.

The manager owns the task list and the dispatch policy; each :class:`_TaskRunner`
owns exactly one task's execution. Concurrency is enforced by the manager rather
than by the pool's own limit, so pausing, removal and live concurrency changes all
behave predictably.

This is the far side of the Queue: :mod:`audix.core.link_queue` holds what the user
might want, and tasks only exist here once they have decided to take it.

Threading contract
------------------
* While a task runs, only its runner mutates it, broadcasting each change via a
  queued signal; the UI reads it on the main thread once that signal lands.
* A runner never sets a final state. It records its outcome and the manager applies
  that on the main thread, so a task stops counting as running at the exact moment
  the manager learns it has stopped. Otherwise a Pause, Cancel, or Resume pressed
  between the two would act on a task the manager still believes is running, which
  can leave it stuck or start a second runner on it.
* Cancelling and pausing are cooperative, through each task's ``threading.Event``.
* Runnables use ``setAutoDelete(False)`` and are kept alive by Python references
  until their completion signal has been handled — letting Qt delete the C++ side
  while a queued signal is still in flight is a crash waiting to happen.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from audix.core.downloader import discard_partials
from audix.core.ffmpeg_manager import FFmpegManager
from audix.core.pipeline import AudioPipeline, PipelineCancelled, PipelinePaused
from audix.core.task import DownloadTask, TaskState

log = logging.getLogger("audix.downloads")

#: "All at once" still needs a ceiling: each task is a yt-dlp session plus an FFmpeg
#: process, and YouTube answers a burst much past this with rate limiting.
MAX_PARALLEL = 16


@dataclass(frozen=True)
class _Outcome:
    """How a run ended, for the manager to apply on the main thread."""

    state: TaskState
    message: str
    output: str = ""


class _RunnerSignals(QObject):
    """Signal carrier for a :class:`QRunnable` (which cannot own signals itself)."""

    progress = Signal(str)                    # task id
    finished = Signal(str)                    # task id; see _TaskRunner.outcome


class _TaskRunner(QRunnable):
    """Executes one task on a pool thread."""

    def __init__(self, task: DownloadTask, pipeline: AudioPipeline) -> None:
        super().__init__()
        self.task = task
        self.pipeline = pipeline
        self.signals = _RunnerSignals()
        self.outcome = _Outcome(TaskState.CANCELLED, "Cancelled")
        self.setAutoDelete(False)

    @Slot()
    def run(self) -> None:  # noqa: D102 - QRunnable entry point
        task = self.task

        def on_stage(state: TaskState, fraction: float, speed, eta) -> None:
            task.enter_stage(state)
            task.progress = max(0.0, min(fraction, 1.0))
            task.speed = speed
            task.eta = eta
            task.state = state      # last, so a new state never shows stale figures
            self.signals.progress.emit(task.id)

        try:
            if not task.is_cancelled:
                output = str(self.pipeline.process(task, on_stage))
                self.outcome = _Outcome(TaskState.COMPLETED, "Finished", output)
        except PipelinePaused:
            self.outcome = _Outcome(TaskState.PAUSED, "Paused")
        except PipelineCancelled:
            pass
        except Exception as exc:  # noqa: BLE001 - one bad task must not kill the pool
            log.exception("Task failed: %s", task.title)
            self.outcome = _Outcome(TaskState.FAILED,
                                    str(exc) or exc.__class__.__name__)
        self.signals.finished.emit(task.id)


class DownloadManager(QObject):
    """Schedules :class:`DownloadTask` objects across a bounded thread pool."""

    task_added = Signal(str)                  # task id
    task_updated = Signal(str)                # task id
    task_finished = Signal(str, bool, str)    # task id, success, message/path
    task_removed = Signal(str)                # task id
    stats_changed = Signal(int, int, int)     # active, pending, completed

    def __init__(self, ffmpeg: FFmpegManager, config, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.ffmpeg = ffmpeg
        self.config = config

        self._tasks: Dict[str, DownloadTask] = {}
        self._order: List[str] = []
        self._pending: List[str] = []
        self._active: Dict[str, _TaskRunner] = {}
        self._remove_when_done: Set[str] = set()
        self._paused = False

        self._pool = QThreadPool(self)
        # Headroom above our own limit; the manager, not the pool, gates dispatch.
        self._pool.setMaxThreadCount(MAX_PARALLEL + 2)

    # --------------------------------------------------------------- accessors
    @property
    def max_concurrent(self) -> int:
        configured = int(getattr(self.config, "concurrent_downloads", 3))
        return max(1, min(configured, MAX_PARALLEL))

    @property
    def is_paused(self) -> bool:
        return self._paused

    def tasks(self) -> List[DownloadTask]:
        """Tasks in insertion order."""
        return [self._tasks[tid] for tid in self._order if tid in self._tasks]

    def task(self, task_id: str) -> Optional[DownloadTask]:
        return self._tasks.get(task_id)

    def counts(self) -> tuple:
        active = len(self._active)
        pending = len(self._pending)
        completed = sum(1 for t in self._tasks.values()
                        if t.state == TaskState.COMPLETED)
        return active, pending, completed

    def has_unfinished_work(self) -> bool:
        return bool(self._active or self._pending or self.unfinished())

    def unfinished(self) -> List[DownloadTask]:
        """Everything that would be lost if the app closed now."""
        return [t for t in self.tasks() if not t.state.is_terminal]

    def waiting_order(self) -> List[str]:
        """Waiting task ids, next to start first."""
        return list(self._pending)

    # ------------------------------------------------------------- task edits
    def add_tasks(self, tasks: List[DownloadTask], autostart: bool = True) -> None:
        for task in tasks:
            self._tasks[task.id] = task
            self._order.append(task.id)
            self._pending.append(task.id)
            self.task_added.emit(task.id)
        if tasks:
            log.info("Added %d download(s)", len(tasks))
        self._emit_stats()
        if autostart:
            self._pump()

    def restore(self, tasks: List[DownloadTask]) -> None:
        """Bring finished work from an earlier session back into the list."""
        for task in tasks:
            self._tasks[task.id] = task
            self._order.append(task.id)
            self.task_added.emit(task.id)
        self._emit_stats()

    def retry(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task is None or task.state.is_active:
            return
        task.reset_for_retry()
        if task_id not in self._pending:
            self._pending.append(task_id)
        self.task_updated.emit(task_id)
        self._emit_stats()
        self._pump()

    def retry_failed(self) -> int:
        failed = [t.id for t in self.tasks() if t.state == TaskState.FAILED]
        for task_id in failed:
            self.retry(task_id)
        return len(failed)

    def prioritize(self, task_id: str) -> None:
        """Move a waiting task to the front of the line."""
        if task_id in self._pending:
            self._pending.remove(task_id)
            self._pending.insert(0, task_id)
            self.task_updated.emit(task_id)

    def cancel(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task is None or task.state.is_terminal:
            return
        task.cancel()
        if task_id in self._active:
            task.message = "Cancelling…"
            self.task_updated.emit(task_id)
            return
        # Never started, or paused with a partial file: retire it immediately.
        if task_id in self._pending:
            self._pending.remove(task_id)
        discard_partials(task.id)
        task.state = TaskState.CANCELLED
        task.message = "Cancelled"
        self.task_updated.emit(task_id)
        self.task_finished.emit(task_id, False, "Cancelled")
        self._emit_stats()
        self._pump()

    def cancel_all(self) -> None:
        for task_id in list(self._order):
            self.cancel(task_id)

    def remove(self, task_id: str) -> None:
        """Drop a task from the list entirely (cancelling it first if running)."""
        task = self._tasks.get(task_id)
        if task is None:
            return
        if task.state.is_active:
            # The row goes once the runner has unwound and reported back.
            self._remove_when_done.add(task_id)
            task.cancel()
            task.message = "Removing…"
            self.task_updated.emit(task_id)
            return
        if not task.state.is_terminal:
            discard_partials(task.id)
        self._forget(task_id)
        self._emit_stats()

    def clear_finished(self) -> List[str]:
        """Remove every finished/failed/cancelled task. Returns removed ids."""
        removed = [tid for tid, task in self._tasks.items() if task.state.is_terminal]
        for task_id in removed:
            self._forget(task_id)
        self._emit_stats()
        return removed

    def _forget(self, task_id: str) -> None:
        self._pending = [t for t in self._pending if t != task_id]
        self._order = [t for t in self._order if t != task_id]
        self._tasks.pop(task_id, None)
        self._remove_when_done.discard(task_id)
        self.task_removed.emit(task_id)

    # ----------------------------------------------------------------- control
    def pause(self, task_id: str) -> None:
        """Stop one task, keeping its partial file so it can continue later."""
        task = self._tasks.get(task_id)
        if task is None or not task.state.can_pause:
            return
        if task_id in self._pending:
            self._pending.remove(task_id)
            task.state = TaskState.PAUSED
            task.message = "Paused"
            self.task_updated.emit(task_id)
            self._emit_stats()
        elif task_id in self._active:
            task.request_pause()
            task.message = "Pausing…"
            self.task_updated.emit(task_id)

    def resume(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task is None or task.state != TaskState.PAUSED:
            return
        task.clear_pause()
        task.state = TaskState.PENDING
        task.message = ""
        self._pending.insert(0, task_id)
        self.task_updated.emit(task_id)
        self._emit_stats()
        self._pump()

    def pause_all(self) -> None:
        """Hold the line and stop everything that can stop.

        Tasks already converting finish, because FFmpeg cannot be suspended and
        they are moments from done anyway.
        """
        self._paused = True
        log.info("Downloads paused")
        for task_id in list(self._order):
            self.pause(task_id)
        self._emit_stats()

    def resume_all(self) -> None:
        self._paused = False
        log.info("Downloads resumed")
        for task_id in reversed(list(self._order)):
            self.resume(task_id)
        self._emit_stats()
        self._pump()

    def set_concurrency(self, value: int) -> None:
        self.config.concurrent_downloads = max(1, min(int(value), MAX_PARALLEL))
        self._pump()

    def shutdown(self, wait_ms: int = 8000) -> None:
        """Cancel everything and let in-flight yt-dlp/FFmpeg calls unwind."""
        self.cancel_all()
        self._pool.waitForDone(wait_ms)
        self._active.clear()

    # --------------------------------------------------------------- dispatch
    def _pump(self) -> None:
        """Start as many pending tasks as the concurrency limit allows."""
        if self._paused:
            return
        while self._pending and len(self._active) < self.max_concurrent:
            task_id = self._pending.pop(0)
            task = self._tasks.get(task_id)
            if task is None or task.is_cancelled:
                continue
            try:
                pipeline = AudioPipeline(self.ffmpeg, self.config)
            except RuntimeError as exc:
                # FFmpeg vanished after startup: fail loudly rather than stall.
                task.state = TaskState.FAILED
                task.message = str(exc)
                self.task_updated.emit(task_id)
                self.task_finished.emit(task_id, False, str(exc))
                continue

            runner = _TaskRunner(task, pipeline)
            runner.signals.progress.connect(self.task_updated)
            runner.signals.finished.connect(self._on_runner_finished)
            self._active[task_id] = runner
            task.state = TaskState.RESOLVING
            task.message = ""
            task.enter_stage(TaskState.RESOLVING)
            self.task_updated.emit(task_id)
            self._pool.start(runner)
        self._emit_stats()

    @Slot(str)
    def _on_runner_finished(self, task_id: str) -> None:
        runner = self._active.pop(task_id, None)    # releases the runner reference
        if runner is None:
            return                  # arrived after shutdown let go of everything
        outcome = self._apply(runner.task, runner.outcome)

        if task_id in self._remove_when_done:
            self._forget(task_id)
        else:
            self.task_updated.emit(task_id)
            self.task_finished.emit(task_id, outcome.state == TaskState.COMPLETED,
                                    outcome.output or outcome.message)
        self._emit_stats()
        self._pump()

    @staticmethod
    def _apply(task: DownloadTask, outcome: _Outcome) -> _Outcome:
        """Write how a run ended onto its task. Returns what finally applied."""
        if outcome.state == TaskState.PAUSED and task.is_cancelled:
            # Cancelled in the moment the run was stopping for a pause.
            discard_partials(task.id)
            outcome = _Outcome(TaskState.CANCELLED, "Cancelled")

        task.state = outcome.state
        task.message = outcome.message
        task.speed = None
        if outcome.state == TaskState.PAUSED:
            task.eta = None
            return outcome

        task.finished_at = time.time()
        task.close_stages()
        if outcome.state == TaskState.COMPLETED:
            task.progress = 1.0
            task.eta = 0.0
            task.output_path = outcome.output
        return outcome

    def _emit_stats(self) -> None:
        active, pending, completed = self.counts()
        self.stats_changed.emit(active, pending, completed)
