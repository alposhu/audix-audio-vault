"""Parallel download queue built on ``QThreadPool``.

The manager owns the task list and the dispatch policy; each :class:`_TaskRunner`
owns exactly one task's execution. Concurrency is enforced by the manager rather
than by the pool's own limit, so pausing, removal and live concurrency changes all
behave predictably.

Threading contract
------------------
* Task objects are mutated only inside their own runner, then broadcast via a
  queued signal; the UI reads them on the main thread once that signal lands.
* Cancellation is cooperative, through each task's ``threading.Event``.
* Runnables use ``setAutoDelete(False)`` and are kept alive by Python references
  until their completion signal has been handled — letting Qt delete the C++ side
  while a queued signal is still in flight is a crash waiting to happen.
"""
from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional, Set

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from audix.core.downloader import ExtractionError, MediaEntry, ResolvedBatch, resolve_targets
from audix.core.ffmpeg_manager import FFmpegManager
from audix.core.pipeline import AudioPipeline, PipelineCancelled
from audix.core.task import DownloadTask, TaskState

log = logging.getLogger("audix.queue")

TaskFactory = Callable[[MediaEntry], DownloadTask]


class _RunnerSignals(QObject):
    """Signal carrier for a :class:`QRunnable` (which cannot own signals itself)."""

    progress = Signal(str)                    # task id
    finished = Signal(str, bool, str)         # task id, success, message


class _TaskRunner(QRunnable):
    """Executes one task on a pool thread."""

    def __init__(self, task: DownloadTask, pipeline: AudioPipeline) -> None:
        super().__init__()
        self.task = task
        self.pipeline = pipeline
        self.signals = _RunnerSignals()
        self.setAutoDelete(False)

    @Slot()
    def run(self) -> None:  # noqa: D102 - QRunnable entry point
        task = self.task
        if task.is_cancelled:
            task.state = TaskState.CANCELLED
            task.message = "Cancelled"
            self.signals.finished.emit(task.id, False, "Cancelled")
            return

        def on_stage(state: TaskState, fraction: float, speed, eta) -> None:
            task.state = state
            task.progress = max(0.0, min(fraction, 1.0))
            task.speed = speed
            task.eta = eta
            self.signals.progress.emit(task.id)

        try:
            output = self.pipeline.process(task, on_stage)
            task.state = TaskState.COMPLETED
            task.progress = 1.0
            task.speed = None
            task.eta = 0.0
            task.output_path = str(output)
            task.message = "Completed"
            self.signals.finished.emit(task.id, True, str(output))
        except PipelineCancelled:
            task.state = TaskState.CANCELLED
            task.message = "Cancelled"
            self.signals.finished.emit(task.id, False, "Cancelled")
        except Exception as exc:  # noqa: BLE001 - one bad task must not kill the pool
            message = str(exc) or exc.__class__.__name__
            log.exception("Task failed: %s", task.title)
            task.state = TaskState.FAILED
            task.message = message
            self.signals.finished.emit(task.id, False, message)


class _ResolveSignals(QObject):
    resolved = Signal(str, object)     # token, ResolvedBatch
    failed = Signal(str, str)          # token, message


class _ResolveRunner(QRunnable):
    """Expands a pasted URL into tracks without blocking the UI."""

    def __init__(self, token: str, url: str, config) -> None:
        super().__init__()
        self.token = token
        self.url = url
        self.config = config
        self.signals = _ResolveSignals()
        self.setAutoDelete(False)

    @Slot()
    def run(self) -> None:  # noqa: D102
        try:
            batch = resolve_targets(self.url, self.config)
            self.signals.resolved.emit(self.token, batch)
        except ExtractionError as exc:
            self.signals.failed.emit(self.token, str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("URL resolution failed")
            self.signals.failed.emit(self.token, str(exc) or "Could not read that URL.")


class QueueManager(QObject):
    """Schedules :class:`DownloadTask` objects across a bounded thread pool."""

    task_added = Signal(str)                  # task id
    task_updated = Signal(str)                # task id
    task_finished = Signal(str, bool, str)    # task id, success, message/path
    stats_changed = Signal(int, int, int)     # active, pending, completed

    # Emitted for resolutions started via `resolve_url` (the Quick Convert flow).
    batch_resolved = Signal(object)           # ResolvedBatch
    resolve_failed = Signal(str)

    # Emitted for one-shot `resolve_and_enqueue` calls (the Browser flow).
    autoqueue_finished = Signal(int, str)     # tasks added, error message ("" if ok)

    #: Token prefixes distinguishing the two resolution flows.
    _PREVIEW = "preview"
    _AUTOQUEUE = "autoqueue"

    def __init__(self, ffmpeg: FFmpegManager, config, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.ffmpeg = ffmpeg
        self.config = config

        self._tasks: Dict[str, DownloadTask] = {}
        self._order: List[str] = []
        self._pending: List[str] = []
        self._active: Dict[str, _TaskRunner] = {}
        self._paused = False

        self._resolvers: Set[_ResolveRunner] = set()
        self._factories: Dict[str, TaskFactory] = {}

        self._pool = QThreadPool(self)
        # Headroom above our own limit; the manager, not the pool, gates dispatch.
        self._pool.setMaxThreadCount(max(8, self.max_concurrent + 4))

        self._resolve_pool = QThreadPool(self)
        self._resolve_pool.setMaxThreadCount(2)

    # --------------------------------------------------------------- accessors
    @property
    def max_concurrent(self) -> int:
        return max(1, int(getattr(self.config, "concurrent_downloads", 3)))

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
        return bool(self._active or self._pending)

    # ------------------------------------------------------------- resolution
    def resolve_url(self, url: str) -> None:
        """Asynchronously expand ``url`` for preview.

        Emits :attr:`batch_resolved` or :attr:`resolve_failed`.
        """
        self._start_resolver(self._PREVIEW, url)

    def resolve_and_enqueue(self, url: str, factory: TaskFactory) -> None:
        """Resolve ``url`` and queue every track it yields, in one step.

        ``factory`` turns a :class:`MediaEntry` into a configured task. Emits
        :attr:`autoqueue_finished` when done.
        """
        token = f"{self._AUTOQUEUE}:{id(factory)}"
        self._factories[token] = factory
        self._start_resolver(token, url)

    def _start_resolver(self, token: str, url: str) -> None:
        runner = _ResolveRunner(token, url, self.config)
        runner.signals.resolved.connect(self._on_resolved)
        runner.signals.failed.connect(self._on_resolve_failed)
        self._resolvers.add(runner)
        self._resolve_pool.start(runner)

    @Slot(str, object)
    def _on_resolved(self, token: str, batch: ResolvedBatch) -> None:
        self._retire_resolver(token)
        if token.startswith(self._AUTOQUEUE):
            factory = self._factories.pop(token, None)
            if factory is None:
                return
            tasks = [factory(entry) for entry in batch.entries]
            self.add_tasks(tasks)
            self.autoqueue_finished.emit(len(tasks), "")
        else:
            self.batch_resolved.emit(batch)

    @Slot(str, str)
    def _on_resolve_failed(self, token: str, message: str) -> None:
        self._retire_resolver(token)
        if token.startswith(self._AUTOQUEUE):
            self._factories.pop(token, None)
            self.autoqueue_finished.emit(0, message)
        else:
            self.resolve_failed.emit(message)

    def _retire_resolver(self, token: str) -> None:
        """Release a resolve runner now that its signal has been delivered."""
        self._resolvers = {r for r in self._resolvers if r.token != token}

    # ------------------------------------------------------------- queue edits
    def add_tasks(self, tasks: List[DownloadTask], autostart: bool = True) -> None:
        for task in tasks:
            self._tasks[task.id] = task
            self._order.append(task.id)
            self._pending.append(task.id)
            self.task_added.emit(task.id)
        if tasks:
            log.info("Queued %d task(s)", len(tasks))
        self._emit_stats()
        if autostart:
            self._pump()

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

    def cancel(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task is None or task.state.is_terminal:
            return
        task.cancel()
        if task_id in self._pending:
            # Never started: retire it immediately.
            self._pending.remove(task_id)
            task.state = TaskState.CANCELLED
            task.message = "Cancelled"
            self.task_updated.emit(task_id)
            self.task_finished.emit(task_id, False, "Cancelled")
            self._emit_stats()
            self._pump()
        else:
            task.message = "Cancelling…"
            self.task_updated.emit(task_id)

    def cancel_all(self) -> None:
        for task_id in list(self._order):
            self.cancel(task_id)

    def remove(self, task_id: str) -> None:
        """Drop a task from the queue entirely (cancelling it first if running)."""
        task = self._tasks.get(task_id)
        if task is None:
            return
        if task.state.is_active:
            task.cancel()
            return          # actual removal happens once the runner reports back
        self._pending = [t for t in self._pending if t != task_id]
        self._order = [t for t in self._order if t != task_id]
        self._tasks.pop(task_id, None)
        self._emit_stats()

    def clear_finished(self) -> List[str]:
        """Remove every completed/failed/cancelled task. Returns removed ids."""
        removed = [tid for tid, task in self._tasks.items() if task.state.is_terminal]
        for task_id in removed:
            self._order = [t for t in self._order if t != task_id]
            self._tasks.pop(task_id, None)
        self._emit_stats()
        return removed

    # ----------------------------------------------------------------- control
    def set_paused(self, paused: bool) -> None:
        """Pause dispatch. In-flight downloads finish; nothing new starts."""
        if self._paused == paused:
            return
        self._paused = paused
        log.info("Queue %s", "paused" if paused else "resumed")
        if not paused:
            self._pump()
        self._emit_stats()

    def toggle_paused(self) -> bool:
        self.set_paused(not self._paused)
        return self._paused

    def set_concurrency(self, value: int) -> None:
        self.config.concurrent_downloads = max(1, int(value))
        self._pool.setMaxThreadCount(max(8, self.max_concurrent + 4))
        self._pump()

    def shutdown(self, wait_ms: int = 8000) -> None:
        """Cancel everything and let in-flight yt-dlp/FFmpeg calls unwind."""
        self.cancel_all()
        self._pool.waitForDone(wait_ms)
        self._resolve_pool.waitForDone(2000)
        self._active.clear()
        self._resolvers.clear()

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
            runner.signals.finished.connect(self._on_task_finished)
            self._active[task_id] = runner
            task.state = TaskState.RESOLVING
            task.message = ""
            self.task_updated.emit(task_id)
            self._pool.start(runner)
        self._emit_stats()

    @Slot(str, bool, str)
    def _on_task_finished(self, task_id: str, success: bool, message: str) -> None:
        self._active.pop(task_id, None)     # releases the runner reference
        self.task_updated.emit(task_id)
        self.task_finished.emit(task_id, success, message)
        self._emit_stats()
        self._pump()

    def _emit_stats(self) -> None:
        active, pending, completed = self.counts()
        self.stats_changed.emit(active, pending, completed)
