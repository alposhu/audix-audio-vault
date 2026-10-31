"""The Queue holds choices; the download manager runs the ones that were made."""
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from audix.config import AppConfig
from audix.core import download_manager as dm
from audix.core import link_queue as lq
from audix.core.downloader import MediaEntry, ParentList, ResolvedBatch, Scope
from audix.core.history import DownloadHistory
from audix.core.link_queue import LinkQueue, PendingLink, QueueGroup, QueueItem
from audix.core.pipeline import PipelineCancelled, PipelinePaused
from audix.core.task import DownloadTask, TaskState
from audix.utils import paths

APP = QApplication.instance() or QApplication([])


def spin(condition, timeout=5.0):
    """Run the event loop until ``condition()`` holds. Fails the test on timeout."""
    deadline = time.time() + timeout
    loop = QEventLoop()
    while not condition():
        if time.time() > deadline:
            raise AssertionError("timed out waiting for the event loop")
        QTimer.singleShot(5, loop.quit)
        loop.exec()


def entry(video_id, title="Song", **extra):
    return MediaEntry(url=f"https://youtu.be/{video_id}", video_id=video_id,
                      title=title, **extra)


def playlist_batch(*ids, title="Road trip"):
    return ResolvedBatch(
        entries=[entry(v, f"Track {v}", playlist_title=title, playlist_index=i + 1,
                       playlist_count=len(ids)) for i, v in enumerate(ids)],
        playlist_title=title, is_playlist=True,
    )


class QueueCase(unittest.TestCase):
    def setUp(self):
        paths.queue_file().unlink(missing_ok=True)
        self.history = DownloadHistory(paths.app_home() / "history-test.jsonl")
        self.queue = LinkQueue(AppConfig(), self.history)
        self.addCleanup(self.queue.shutdown)
        self.results = {}

        def fake_resolve(url, _config, scope=Scope.AUTO):
            self.seen_scope = scope
            answer = self.results[url]
            if isinstance(answer, Exception):
                raise answer
            return answer

        patcher = mock.patch.object(lq, "resolve_targets", fake_resolve)
        patcher.start()
        self.addCleanup(patcher.stop)

    def add_and_wait(self, url, result, scope=Scope.AUTO):
        self.results[url] = result
        self.queue.add_link(url, scope)
        spin(lambda: not any(isinstance(row, PendingLink) and not row.error
                             for row in self.queue.rows()))

    def test_adding_a_link_starts_nothing_and_shows_a_reading_row(self):
        self.results["https://youtu.be/aaaaaaaaaaa"] = ResolvedBatch(
            entries=[entry("aaaaaaaaaaa")])
        self.queue.add_link("https://youtu.be/aaaaaaaaaaa")
        self.assertIsInstance(self.queue.rows()[0], PendingLink)
        spin(lambda: self.queue.items())
        self.assertEqual(len(self.queue.rows()), 1)
        self.assertTrue(self.queue.items()[0].checked)

    def test_a_playlist_becomes_a_group_of_individually_tickable_tracks(self):
        self.add_and_wait("https://youtube.com/playlist?list=PLx", playlist_batch("a", "b", "c"))
        rows = self.queue.rows()
        self.assertIsInstance(rows[0], QueueGroup)
        self.assertEqual(len(self.queue.items()), 3)
        self.assertTrue(all(i.group_id == rows[0].id for i in self.queue.items()))

        first = self.queue.items()[0]
        self.queue.set_checked([first.id], False)
        self.assertEqual(len(self.queue.checked_items()), 2)

    def test_take_hands_over_only_what_was_chosen(self):
        self.add_and_wait("https://youtube.com/playlist?list=PLx", playlist_batch("a", "b", "c"))
        first, second, third = self.queue.items()
        self.queue.set_checked([second.id], False)

        taken = self.queue.take([i.id for i in self.queue.checked_items()])
        self.assertEqual([e.video_id for e in taken], ["a", "c"])
        self.assertEqual([i.id for i in self.queue.items()], [second.id])
        self.assertIsInstance(self.queue.rows()[0], QueueGroup)

    def test_taking_everything_drops_the_empty_group(self):
        self.add_and_wait("https://youtube.com/playlist?list=PLx", playlist_batch("a", "b"))
        self.queue.take([i.id for i in self.queue.items()])
        self.assertTrue(self.queue.is_empty())

    def test_group_toggle_ticks_all_then_none(self):
        self.add_and_wait("https://youtube.com/playlist?list=PLx", playlist_batch("a", "b"))
        group = self.queue.rows()[0]
        self.queue.set_checked([self.queue.items()[0].id], False)
        self.queue.toggle_group(group.id)
        self.assertEqual(len(self.queue.checked_items()), 2)
        self.queue.toggle_group(group.id)
        self.assertEqual(len(self.queue.checked_items()), 0)

    def test_collapsing_hides_tracks_without_unticking_them(self):
        self.add_and_wait("https://youtube.com/playlist?list=PLx", playlist_batch("a", "b"))
        group = self.queue.rows()[0]
        self.queue.set_group_expanded(group.id, False)
        self.assertEqual(self.queue.visible_rows(), [group])
        self.assertEqual(len(self.queue.checked_items()), 2)

    def test_the_same_video_is_not_queued_twice(self):
        notices = []
        self.queue.notice.connect(notices.append)
        self.queue.add_entry(entry("dQw4w9WgXcQ"))
        self.queue.add_link("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDx")
        self.assertEqual(len(self.queue.rows()), 1)
        self.assertEqual(len(notices), 1)

    def test_tracks_you_already_have_arrive_unticked_and_labelled(self):
        task = DownloadTask(entry=entry("a"), audio_format="mp3", bitrate="320", output_dir="x")
        self.history.add(task)
        self.add_and_wait("https://youtube.com/playlist?list=PLx", playlist_batch("a", "b"))
        have, new = self.queue.items()
        self.assertTrue(have.already_have)
        self.assertFalse(have.checked)
        self.assertTrue(new.checked)

    def test_a_bad_link_stays_visible_with_its_reason_and_can_retry(self):
        url = "https://youtu.be/bbbbbbbbbbb"
        failures = []
        self.queue.link_failed.connect(lambda u, m: failures.append(m))
        self.add_and_wait(url, lq.ExtractionError("This video is private."))
        self.assertEqual(self.queue.rows()[0].error, "This video is private.")
        self.assertEqual(failures, ["This video is private."])

        self.results[url] = ResolvedBatch(entries=[entry("bbbbbbbbbbb")])
        self.queue.retry(self.queue.rows()[0].id)
        spin(lambda: self.queue.items())
        self.assertEqual(self.queue.items()[0].entry.video_id, "bbbbbbbbbbb")

    def test_the_offered_list_survives_on_the_row(self):
        parent = ParentList(url="https://x", list_id="RDx", is_mix=True)
        added = []
        self.queue.link_added.connect(added.append)
        self.add_and_wait("https://youtu.be/ccccccccccc",
                          ResolvedBatch(entries=[entry("ccccccccccc")], parent_list=parent))
        self.assertEqual(self.queue.items()[0].parent_list, parent)
        self.assertEqual(added[0].parent_list, parent)

    def test_the_queue_survives_a_restart(self):
        self.add_and_wait("https://youtube.com/playlist?list=PLx", playlist_batch("a", "b"))
        self.queue.set_checked([self.queue.items()[0].id], False)
        self.queue.add_entry(entry("ddddddddddd"), ParentList("u", "PLy", False))
        self.queue.save()

        reborn = LinkQueue(AppConfig(), self.history)
        self.addCleanup(reborn.shutdown)
        self.assertEqual(
            [type(r) for r in reborn.rows()],
            [QueueGroup, QueueItem, QueueItem, QueueItem],
        )
        self.assertFalse(reborn.items()[0].checked)
        self.assertEqual(reborn.items()[2].parent_list.list_id, "PLy")

    def test_a_corrupt_queue_file_starts_empty(self):
        paths.queue_file().write_text("{not json", encoding="utf-8")
        reborn = LinkQueue(AppConfig(), self.history)
        self.addCleanup(reborn.shutdown)
        self.assertTrue(reborn.is_empty())


class _FakePipeline:
    """Stands in for yt-dlp and FFmpeg, driven by the test through ``gate``."""

    gate = None
    running = 0
    peak = 0
    runs = {}
    lock = threading.Lock()

    def __init__(self, _ffmpeg, _config):
        pass

    def process(self, task, on_stage):
        cls = type(self)
        with cls.lock:
            cls.running += 1
            cls.peak = max(cls.peak, cls.running)
            cls.runs[task.id] = cls.runs.get(task.id, 0) + 1
        try:
            on_stage(TaskState.DOWNLOADING, 0.3, 1000.0, 5.0)
            while not cls.gate.wait(0.01):
                if task.is_cancelled:
                    raise PipelineCancelled("Cancelled")
                if task.pause_event.is_set():
                    raise PipelinePaused("Paused")
            on_stage(TaskState.CONVERTING, 0.8, None, None)
            return Path("finished.mp3")
        finally:
            with cls.lock:
                cls.running -= 1


class ManagerCase(unittest.TestCase):
    def setUp(self):
        _FakePipeline.gate = threading.Event()
        _FakePipeline.running = 0
        _FakePipeline.peak = 0
        _FakePipeline.runs = {}
        patcher = mock.patch.object(dm, "AudioPipeline", _FakePipeline)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.config = AppConfig()
        self.config.concurrent_downloads = 2
        self.manager = dm.DownloadManager(mock.Mock(ready=True), self.config)
        self.addCleanup(self.finish)

    def finish(self):
        _FakePipeline.gate.set()
        self.manager.shutdown(2000)

    def tasks(self, count):
        return [DownloadTask(entry=entry(f"video{i:06d}"), audio_format="mp3",
                             bitrate="320", output_dir=".") for i in range(count)]

    def test_concurrency_is_a_live_limit(self):
        tasks = self.tasks(5)
        self.manager.add_tasks(tasks)
        spin(lambda: _FakePipeline.running == 2)
        self.assertEqual(self.manager.counts()[:2], (2, 3))

        self.manager.set_concurrency(4)
        spin(lambda: _FakePipeline.running == 4)
        _FakePipeline.gate.set()
        spin(lambda: self.manager.counts()[2] == 5)
        self.assertEqual(_FakePipeline.peak, 4)

    def test_all_at_once_runs_a_whole_batch_in_parallel(self):
        self.manager.set_concurrency(dm.MAX_PARALLEL)
        self.manager.add_tasks(self.tasks(6))
        spin(lambda: _FakePipeline.running == 6)

    def test_concurrency_is_capped(self):
        self.manager.set_concurrency(1000)
        self.assertEqual(self.manager.max_concurrent, dm.MAX_PARALLEL)

    def test_pause_keeps_the_task_and_resume_runs_it_again(self):
        task = self.tasks(1)[0]
        self.manager.add_tasks([task])
        spin(lambda: task.state == TaskState.DOWNLOADING)

        self.manager.pause(task.id)
        spin(lambda: task.state == TaskState.PAUSED)
        self.assertEqual(self.manager.counts()[:2], (0, 0))
        self.assertTrue(self.manager.has_unfinished_work())

        _FakePipeline.gate.set()
        self.manager.resume(task.id)
        spin(lambda: task.state == TaskState.COMPLETED)
        self.assertEqual(_FakePipeline.runs[task.id], 2)

    def test_pausing_a_waiting_task_lets_the_next_one_go_first(self):
        first, second, third = self.tasks(3)
        self.config.concurrent_downloads = 1
        self.manager.add_tasks([first, second, third])
        self.manager.pause(second.id)
        self.assertEqual(second.state, TaskState.PAUSED)

        _FakePipeline.gate.set()
        spin(lambda: third.state == TaskState.COMPLETED)
        self.assertEqual(second.state, TaskState.PAUSED)

    def test_pause_all_then_resume_all(self):
        tasks = self.tasks(3)
        self.manager.add_tasks(tasks)
        spin(lambda: _FakePipeline.running == 2)

        self.manager.pause_all()
        spin(lambda: all(t.state == TaskState.PAUSED for t in tasks))

        _FakePipeline.gate.set()
        self.manager.resume_all()
        spin(lambda: all(t.state == TaskState.COMPLETED for t in tasks))

    def test_a_paused_task_can_be_cancelled(self):
        task = self.tasks(1)[0]
        self.manager.add_tasks([task])
        spin(lambda: task.state == TaskState.DOWNLOADING)
        self.manager.pause(task.id)
        spin(lambda: task.state == TaskState.PAUSED)

        paths.cache_dir().mkdir(parents=True, exist_ok=True)
        (paths.cache_dir() / f"{task.id}.webm.part").write_bytes(b"partial")
        self.manager.cancel(task.id)
        self.assertEqual(task.state, TaskState.CANCELLED)
        self.assertFalse(list(paths.cache_dir().glob(f"{task.id}*")))

    def test_cancel_while_a_pause_is_landing_ends_cancelled(self):
        """Cancel pressed between the run stopping and the manager hearing of it."""
        task = self.tasks(1)[0]
        self.manager.add_tasks([task])
        spin(lambda: task.state == TaskState.DOWNLOADING)

        self.manager.pause(task.id)
        self.manager.cancel(task.id)
        spin(lambda: task.state.is_terminal)
        self.assertEqual(task.state, TaskState.CANCELLED)
        self.assertEqual(self.manager.counts()[:2], (0, 0))

    def test_a_task_counts_as_running_until_the_manager_hears_it_stopped(self):
        """Resume cannot start a second runner while the first is still landing."""
        task = self.tasks(1)[0]
        self.manager.add_tasks([task])
        spin(lambda: task.state == TaskState.DOWNLOADING)

        self.manager.pause(task.id)
        self.manager.resume(task.id)        # too early: it has not stopped yet
        spin(lambda: task.state == TaskState.PAUSED)
        self.assertEqual(_FakePipeline.runs[task.id], 1)
        self.assertEqual(self.manager.counts()[:2], (0, 0))

    def test_removing_a_running_task_waits_for_it_to_unwind(self):
        task = self.tasks(1)[0]
        removed = []
        self.manager.task_removed.connect(removed.append)
        self.manager.add_tasks([task])
        spin(lambda: task.state == TaskState.DOWNLOADING)

        self.manager.remove(task.id)
        self.assertIsNotNone(self.manager.task(task.id))
        spin(lambda: removed == [task.id])
        self.assertIsNone(self.manager.task(task.id))

    def test_prioritize_moves_a_waiting_task_to_the_front(self):
        first, second, third = self.tasks(3)
        self.config.concurrent_downloads = 1
        self.manager.add_tasks([first, second, third])
        self.manager.prioritize(third.id)
        _FakePipeline.gate.set()
        spin(lambda: self.manager.counts()[2] == 3)
        self.assertLess(third.finished_at, second.finished_at)

    def test_clear_finished_leaves_running_work_alone(self):
        first, second = self.tasks(2)
        self.config.concurrent_downloads = 1
        self.manager.add_tasks([first, second])
        self.manager.pause(second.id)
        _FakePipeline.gate.set()
        spin(lambda: first.state == TaskState.COMPLETED)

        self.assertEqual(self.manager.clear_finished(), [first.id])
        self.assertIsNotNone(self.manager.task(second.id))

    def test_stage_timing_is_recorded_across_a_pause(self):
        task = self.tasks(1)[0]
        self.manager.add_tasks([task])
        spin(lambda: task.state == TaskState.DOWNLOADING)
        self.manager.pause(task.id)
        spin(lambda: task.state == TaskState.PAUSED)
        _FakePipeline.gate.set()
        self.manager.resume(task.id)
        spin(lambda: task.state == TaskState.COMPLETED)
        self.assertEqual(len(task.stage_times["DOWNLOADING"]), 2)
        self.assertIsNotNone(task.finished_at)


class History(unittest.TestCase):
    def setUp(self):
        self.path = paths.app_home() / "history-roundtrip.jsonl"
        self.path.unlink(missing_ok=True)

    def finished_task(self, video_id="abcdefghijk"):
        return DownloadTask(
            entry=entry(video_id, "Finished song", uploader="Someone", duration=120.0),
            audio_format="flac", bitrate="native", output_dir="D:/music",
            state=TaskState.COMPLETED, output_path="D:/music/song.flac",
            output_bytes=4096, source_format="opus · 129 kbps · webm",
            source_info={"chapters": [{"title": "One"}], "title": "Finished song",
                         "formats": ["huge"] * 100},
        )

    def test_round_trip_keeps_what_the_editor_needs_and_nothing_else(self):
        history = DownloadHistory(self.path)
        history.add(self.finished_task())

        task = DownloadHistory(self.path).tasks()[0]
        self.assertEqual(task.state, TaskState.COMPLETED)
        self.assertEqual(task.title, "Finished song")
        self.assertEqual(task.output_bytes, 4096)
        self.assertEqual(task.source_info["chapters"], [{"title": "One"}])
        self.assertNotIn("formats", task.source_info)

    def test_knows_which_videos_you_already_have(self):
        history = DownloadHistory(self.path)
        history.add(self.finished_task())
        self.assertTrue(history.has("abcdefghijk"))
        self.assertFalse(history.has("zzzzzzzzzzz"))
        self.assertFalse(history.has(""))

    def test_a_torn_last_line_costs_only_that_record(self):
        history = DownloadHistory(self.path)
        history.add(self.finished_task())
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write('{"id": "half-writ')
        self.assertEqual(len(DownloadHistory(self.path)), 1)

    def test_removing_is_permanent(self):
        history = DownloadHistory(self.path)
        task = self.finished_task()
        history.add(task)
        history.remove([task.id])
        self.assertEqual(len(DownloadHistory(self.path)), 0)


if __name__ == "__main__":
    unittest.main()
