"""The real pages, driven by real input events.

Only yt-dlp and FFmpeg are stood in for. Clicks land on painted zones at the
coordinates a user would hit, which is the only way to prove that a row with no child
widgets actually behaves.
"""
import threading
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QMimeData, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from audix.config import AppConfig
from audix.core import download_manager as dm
from audix.core import link_queue as lq
from audix.core.downloader import ParentList, ResolvedBatch, Scope
from audix.core.pipeline import PipelineCancelled, PipelinePaused
from audix.core.task import DownloadTask, TaskState
from audix.ui import theme, web_profile
from audix.ui.tabs.downloads_tab import INSPECTOR_WIDTH, columns_for
from audix.ui.tokens import COLORS
from audix.ui.widgets.controls import ParallelCombo
from audix.utils import paths
from tests.test_queue_and_downloads import entry, playlist_batch, spin

APP = QApplication.instance() or QApplication([])
paths.cache_dir().mkdir(parents=True, exist_ok=True)
theme.apply(APP)


class _FakeFFmpeg:
    ready = True

    def ffmpeg(self):
        return "ffmpeg"

    def ffprobe(self):
        return "ffprobe"


class _Pipeline:
    """Finishes at once, or holds at a gate until the test releases it."""

    gate = threading.Event()

    def __init__(self, _ffmpeg, _config):
        pass

    def process(self, task, on_stage):
        on_stage(TaskState.DOWNLOADING, 0.4, 2_000_000.0, 7.0)
        task.downloaded_bytes, task.total_bytes = 2_000_000, 5_000_000
        while not self.gate.wait(0.01):
            if task.is_cancelled:
                raise PipelineCancelled("Cancelled")
            if task.pause_event.is_set():
                raise PipelinePaused("Paused")
        output = Path(task.output_dir) / f"{task.entry.video_id}.mp3"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"audio")
        task.output_bytes = 5
        return output


class WindowCase(unittest.TestCase):
    """A real MainWindow, minus Chromium, which adds minutes and tests nothing here."""

    def setUp(self):
        paths.queue_file().unlink(missing_ok=True)
        paths.history_file().unlink(missing_ok=True)
        _Pipeline.gate = threading.Event()
        self.answers = {}

        def fake_resolve(url, _config, scope=Scope.AUTO):
            return self.answers.get(url) or ResolvedBatch(entries=[entry("fallback000")])

        for patcher in (
            mock.patch.object(lq, "resolve_targets", fake_resolve),
            mock.patch.object(dm, "AudioPipeline", _Pipeline),
            mock.patch.object(web_profile, "webengine_available", lambda: False),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

        from audix.ui.main_window import MainWindow

        self.config = AppConfig()
        self.config.output_dir = str(paths.app_home() / "Music")
        self.window = MainWindow(self.config, _FakeFFmpeg())
        self.window.resize(1320, 860)
        self.window.show()
        self.addCleanup(self.finish)
        self.queue = self.window.link_queue
        self.downloads = self.window.downloads
        self.page = self.window.queue_page
        QApplication.processEvents()

    def finish(self):
        _Pipeline.gate.set()
        self.downloads.shutdown(2000)
        self.queue.shutdown()
        self.window.downloads_page._timer.stop()
        self.window.hide()
        self.window.deleteLater()
        QApplication.processEvents()

    # ---------------------------------------------------------------- input
    def layout(self):
        self.page.list.doItemsLayout()
        QApplication.processEvents()

    def click_zone(self, row, zone, modifiers=Qt.NoModifier):
        """Click a named zone in a row, at its real on-screen position."""
        view = self.page.list
        self.layout()
        index = self.page.model.index(row)
        rect = view.visualRect(index)
        zones = self.page.delegate.zones(index, QRectF(rect))
        point = zones[zone].center().toPoint() if zone else rect.center()
        QTest.mouseClick(view.viewport(), Qt.LeftButton, modifiers, point)
        QApplication.processEvents()

    def click_task(self, task, zone=""):
        view = self.window.downloads_page.list
        model = self.window.downloads_page.model
        model.flush(force=True)
        view.doItemsLayout()
        QApplication.processEvents()
        index = model.index_of(task.id)
        rect = view.visualRect(index)
        delegate = self.window.downloads_page.delegate
        point = (delegate.zones(index, QRectF(rect))[zone].center().toPoint() if zone
                 else QPoint(rect.left() + 300, rect.center().y()))
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, point)
        QApplication.processEvents()

    def fill(self, *ids):
        for video_id in ids:
            self.queue.add_entry(entry(video_id, f"Song {video_id}", duration=120.0))
        self.layout()

    def add_playlist(self, *ids):
        url = "https://www.youtube.com/playlist?list=PLx"
        self.answers[url] = playlist_batch(*ids)
        self.queue.add_link(url)
        spin(lambda: self.queue.group_items(self.queue.rows()[-1].id)
             if isinstance(self.queue.rows()[-1], lq.QueueGroup) else
             any(isinstance(r, lq.QueueGroup) for r in self.queue.rows()))
        self.layout()


class QueuePage(WindowCase):
    def test_the_app_opens_on_the_queue_with_an_invitation_not_an_error(self):
        self.assertEqual(self.window.pages.currentWidget(), self.page)
        self.assertEqual(self.page.stack.currentIndex(), 1)
        self.assertFalse(self.page.download_key.isEnabled())
        self.assertIn("first", self.page.download_key.toolTip().lower())

    def test_clicking_a_row_ticks_it_and_updates_the_keys(self):
        self.fill("aaaaaaaaaaa", "bbbbbbbbbbb")
        self.assertEqual(self.page.download_key.text(), "Download selected (2)")
        self.click_zone(0, "")
        self.assertFalse(self.queue.items()[0].checked)
        self.assertEqual(self.page.download_key.text(), "Download selected (1)")
        self.assertEqual(self.page.select_all.checkState(), Qt.PartiallyChecked)

    def test_shift_click_carries_the_tick_across_a_range(self):
        self.fill(*[f"video{n:06d}" for n in range(6)])
        self.queue.set_all_checked(False)
        self.click_zone(1, "box")
        self.click_zone(4, "box", Qt.ShiftModifier)
        self.assertEqual([i.checked for i in self.queue.items()],
                         [False, True, True, True, True, False])

    def test_ticking_a_playlist_header_and_collapsing_it(self):
        self.add_playlist("a", "b", "c")
        self.assertEqual(self.page.model.rowCount(), 4)
        self.click_zone(0, "box")
        self.assertEqual(len(self.queue.checked_items()), 0)
        self.click_zone(0, "chevron")
        self.assertEqual(self.page.model.rowCount(), 1)
        self.click_zone(0, "chevron")
        self.assertEqual(self.page.model.rowCount(), 4)

    def test_the_row_download_key_starts_only_that_track(self):
        self.fill("aaaaaaaaaaa", "bbbbbbbbbbb")
        self.click_zone(1, "download")
        self.assertEqual([t.entry.video_id for t in self.downloads.tasks()], ["bbbbbbbbbbb"])
        self.assertEqual([i.entry.video_id for i in self.queue.items()], ["aaaaaaaaaaa"])

    def test_download_selected_starts_only_what_is_ticked(self):
        self.fill("aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc")
        self.click_zone(1, "box")
        QTest.mouseClick(self.page.download_key, Qt.LeftButton)
        started = {t.entry.video_id for t in self.downloads.tasks()}
        self.assertEqual(started, {"aaaaaaaaaaa", "ccccccccccc"})
        self.assertEqual([i.entry.video_id for i in self.queue.items()], ["bbbbbbbbbbb"])
        self.assertEqual(self.window.pages.currentWidget(), self.page)

    def test_download_all_takes_everything_and_opens_downloads(self):
        self.fill("aaaaaaaaaaa", "bbbbbbbbbbb")
        self.queue.set_all_checked(False)
        QTest.mouseClick(self.page.download_all_key, Qt.LeftButton)
        self.assertEqual(len(self.downloads.tasks()), 2)
        self.assertTrue(self.queue.is_empty())
        self.assertEqual(self.window.pages.currentWidget(), self.window.downloads_page)

    def test_tasks_are_stamped_with_the_format_shown_in_the_strip(self):
        self.fill("aaaaaaaaaaa")
        selector = self.page.format_selector
        selector.format_combo.setCurrentIndex(selector.format_combo.findData("flac"))
        QTest.mouseClick(self.page.download_all_key, Qt.LeftButton)
        task = self.downloads.tasks()[0]
        self.assertEqual(task.audio_format, "flac")
        self.assertEqual(self.config.audio_format, "flac")

    def test_all_at_once_reaches_the_engine_from_the_strip(self):
        combo = self.page.findChild(ParallelCombo)
        combo.setCurrentIndex(combo.count() - 1)
        combo.activated.emit(combo.count() - 1)
        self.assertEqual(self.downloads.max_concurrent, dm.MAX_PARALLEL)

    def test_keyboard_space_enter_delete(self):
        self.fill("aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc")
        view = self.page.list
        view.setCurrentIndex(self.page.model.index(0))
        QTest.keyClick(view, Qt.Key_Space)
        self.assertFalse(self.queue.items()[0].checked)
        QTest.keyClick(view, Qt.Key_Delete)
        self.assertEqual(len(self.queue.items()), 2)
        QTest.keyClick(view, Qt.Key_Return)
        self.assertEqual(len(self.downloads.tasks()), 1)

    def test_pasting_several_links_at_once(self):
        self.page.link_input.setText("https://youtu.be/aaaaaaaaaaa\nhttps://youtu.be/bbbbbbbbbbb")
        self.answers["https://youtu.be/aaaaaaaaaaa"] = ResolvedBatch(entries=[entry("aaaaaaaaaaa")])
        self.answers["https://youtu.be/bbbbbbbbbbb"] = ResolvedBatch(entries=[entry("bbbbbbbbbbb")])
        QTest.keyClick(self.page.link_input, Qt.Key_Return)
        spin(lambda: len(self.queue.items()) == 2)
        self.assertEqual(self.page.link_input.text(), "")

    def test_words_that_are_not_a_link_offer_a_search_instead_of_failing(self):
        searches = []
        self.page.search_requested.connect(searches.append)
        self.page.link_input.setText("rick astley")
        QTest.keyClick(self.page.link_input, Qt.Key_Return)
        self.assertTrue(self.page.link_hint.isVisibleTo(self.page))
        self.assertTrue(self.queue.is_empty())
        QTest.keyClick(self.page.link_input, Qt.Key_Return)
        self.assertEqual(searches, ["rick astley"])

    def test_a_link_on_the_clipboard_is_offered_and_can_be_declined(self):
        QApplication.clipboard().setText("https://youtu.be/ddddddddddd")
        self.page._offer_clipboard()
        self.assertTrue(self.page.clip_notice.isVisibleTo(self.page))
        self.page._dismiss_clipboard()
        self.page._offer_clipboard()
        self.assertFalse(self.page.clip_notice.isVisibleTo(self.page))
        QApplication.clipboard().clear()

    def test_clipboard_watching_can_be_turned_off(self):
        self.config.watch_clipboard = False
        QApplication.clipboard().setText("https://youtu.be/eeeeeeeeeee")
        self.page._offer_clipboard()
        self.assertFalse(self.page.clip_notice.isVisibleTo(self.page))
        QApplication.clipboard().clear()

    def test_dropping_a_link_on_the_page_adds_it(self):
        self.answers["https://youtu.be/fffffffffff"] = ResolvedBatch(entries=[entry("fffffffffff")])
        mime = QMimeData()
        mime.setText("https://youtu.be/fffffffffff")
        drop = QDropEvent(QPointF(100, 300), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        self.page.dropEvent(drop)
        spin(lambda: self.queue.items())

    def test_the_mix_is_offered_after_adding_just_the_video(self):
        offers = []
        parent = ParentList("https://youtube.com/watch?v=x&list=RDx", "RDx", True)
        url = "https://youtu.be/ggggggggggg"
        self.answers[url] = ResolvedBatch(entries=[entry("ggggggggggg")], parent_list=parent)
        with mock.patch.object(self.window.toasts, "show",
                               lambda *a, **k: offers.append((a, k))):
            self.queue.add_link(url)
            spin(lambda: self.queue.items())
        self.assertIn("just this video", offers[0][0][0])
        self.assertEqual(offers[0][0][2], "Add the Mix")

        offers[0][0][3]()
        self.assertEqual(self.queue.rows()[-1].scope, Scope.WHOLE_LIST)
        self.queue.remove([self.queue.rows()[-1].id])


class DownloadsPage(WindowCase):
    def start(self, *ids):
        tasks = [DownloadTask(entry=entry(v, f"Song {v}", uploader="Artist"),
                              audio_format="mp3", bitrate="320",
                              output_dir=self.config.output_dir) for v in ids]
        self.downloads.add_tasks(tasks)
        self.window._go(2, animate=False)
        spin(lambda: all(t.state == TaskState.DOWNLOADING for t in tasks[:1]))
        return tasks

    def tick(self):
        page = self.window.downloads_page
        page._tick()
        QApplication.processEvents()
        return page

    def test_a_running_row_shows_its_figures_and_the_summary_adds_up(self):
        self.start("aaaaaaaaaaa")
        page = self.tick()
        self.assertEqual(page.model.rowCount(), 1)
        self.assertIn("1 running", page.summary_label.text())
        self.assertIn("MB/s", page.speed_label.text())
        self.assertIn("left", page.left_label.text())

    def test_the_row_pause_key_pauses_and_resumes(self):
        task = self.start("aaaaaaaaaaa")[0]
        self.tick()
        self.click_task(task, "pause")
        spin(lambda: task.state == TaskState.PAUSED)
        self.tick()
        self.click_task(task, "resume")
        spin(lambda: task.state == TaskState.DOWNLOADING)

    def test_selecting_a_row_opens_the_inspector_with_real_detail(self):
        task = self.start("aaaaaaaaaaa")[0]
        page = self.tick()
        self.click_task(task)
        self.assertTrue(page.inspector.isVisibleTo(page))
        self.assertEqual(page.inspector.title_label.text(), "Song aaaaaaaaaaa")
        self.assertEqual(page.inspector.channel_label.text(), "Artist")
        self.assertTrue(page.inspector.pause_key.isVisibleTo(page.inspector))
        self.assertFalse(page.inspector.open_key.isVisibleTo(page.inspector))
        self.click_task(task)
        self.assertFalse(page.inspector.isVisibleTo(page))

    def test_opening_the_inspector_moves_no_column(self):
        task = self.start("aaaaaaaaaaa")[0]
        page = self.tick()
        view = page.list
        before = view.visualRect(page.model.index(0))
        self.click_task(task)
        QApplication.processEvents()
        self.assertEqual(view.visualRect(page.model.index(0)), before)
        self.assertTrue(page.inspector.isVisibleTo(page))
        cols = columns_for(QRectF(before))
        inspector_left = page.inspector.mapTo(view.viewport(), QPoint(0, 0)).x()
        self.assertGreater(inspector_left, cols.percent.right())

    def test_the_inspector_never_leaves_half_a_figure_showing(self):
        for width in (1008, 1288):
            rect = QRectF(0, 0, width, 60)
            full = columns_for(rect)
            covered = columns_for(rect, INSPECTOR_WIDTH + 1)
            edge = width - (INSPECTOR_WIDTH + 1)
            for name in ("size", "speed", "eta"):
                kept = getattr(covered, name)
                self.assertTrue(kept is None or kept.right() <= edge, f"{name} at {width}")
                if kept is not None:
                    self.assertEqual(kept, getattr(full, name))      # kept, never moved
            self.assertEqual(covered.ladder, full.ladder)
            self.assertEqual(covered.percent, full.percent)

        task = self.start("aaaaaaaaaaa")[0]
        page = self.tick()
        self.click_task(task)
        self.assertEqual(page.delegate.covered, INSPECTOR_WIDTH + 1)
        self.click_task(task)
        self.assertEqual(page.delegate.covered, 0.0)

    def test_the_inspector_shows_live_figures_for_a_running_item(self):
        task = self.start("aaaaaaaaaaa")[0]
        page = self.tick()
        self.click_task(task)
        inspector = page.inspector
        self.assertIn("MB/s", inspector._rows["Speed"].text())
        self.assertEqual(inspector._rows["Time left"].text(), "7s")
        self.assertEqual(inspector._captions["Elapsed"].text(), "Elapsed")
        self.assertFalse(inspector._holders["Average speed"].isVisibleTo(inspector))

    def test_time_left_claims_only_what_it_can_know(self):
        self.config.concurrent_downloads = 1
        first, second = self.start("aaaaaaaaaaa", "bbbbbbbbbbb")
        page = self.tick()
        self.assertEqual(page.left_label.text(), "These tracks: about 7s left")
        self.downloads.cancel(second.id)
        page = self.tick()
        self.assertEqual(page.left_label.text(), "About 7s left")

    def test_a_finished_item_offers_open_show_edit_and_is_remembered(self):
        task = self.start("aaaaaaaaaaa")[0]
        _Pipeline.gate.set()
        spin(lambda: task.state == TaskState.COMPLETED)
        page = self.tick()
        self.click_task(task)
        self.assertTrue(page.inspector.open_key.isVisibleTo(page.inspector))
        self.assertTrue(page.inspector.edit_key.isVisibleTo(page.inspector))
        self.assertTrue(self.window.history.has("aaaaaaaaaaa"))

    def test_filters_and_search_narrow_the_list(self):
        self.config.concurrent_downloads = 1
        self.start("aaaaaaaaaaa", "bbbbbbbbbbb")
        page = self.tick()
        self.assertEqual(page.filter_keys["waiting"].text(), "Waiting 1")
        QTest.mouseClick(page.filter_keys["waiting"], Qt.LeftButton)
        self.assertEqual(page.model.rowCount(), 1)
        QTest.mouseClick(page.filter_keys["all"], Qt.LeftButton)
        page.search_input.setText("bbbb")
        self.assertEqual(page.model.rowCount(), 1)
        page.search_input.setText("no such song")
        self.assertEqual(page.model.rowCount(), 0)
        self.assertEqual(page.empty_heading.text(), "Nothing matches")

    def test_running_work_ranks_above_finished_work(self):
        self.config.concurrent_downloads = 1
        first, second = self.start("aaaaaaaaaaa", "bbbbbbbbbbb")
        page = self.tick()
        self.assertEqual(page.model.task_at(page.model.index(0)), first)
        _Pipeline.gate.set()
        spin(lambda: second.state == TaskState.COMPLETED)
        page = self.tick()
        self.assertEqual(page.model.rowCount(), 2)

    def test_pause_all_key_holds_everything_then_resumes(self):
        task = self.start("aaaaaaaaaaa")[0]
        page = self.tick()
        QTest.mouseClick(page.pause_key, Qt.LeftButton)
        spin(lambda: task.state == TaskState.PAUSED)
        self.assertEqual(page.pause_key.text(), "Resume all")
        QTest.mouseClick(page.pause_key, Qt.LeftButton)
        spin(lambda: task.state == TaskState.DOWNLOADING)

    def test_finishing_elsewhere_stays_lit_until_you_visit(self):
        task = self.start("aaaaaaaaaaa")[0]
        self.window._go(1, animate=False)
        QApplication.processEvents()
        _Pipeline.gate.set()
        spin(lambda: task.state == TaskState.COMPLETED)
        page = self.tick()
        self.assertIn(task.id, page.model.unseen)
        self.assertEqual(self.window._unseen, 1)
        self.window._go(2, animate=False)
        QApplication.processEvents()
        self.assertEqual(self.window._unseen, 0)
        self.assertIn(task.id, page.model.unseen)      # still lit during this visit
        self.window._go(1, animate=False)
        QApplication.processEvents()
        self.assertNotIn(task.id, page.model.unseen)

    def test_removing_a_finished_item_forgets_it(self):
        task = self.start("aaaaaaaaaaa")[0]
        _Pipeline.gate.set()
        spin(lambda: task.state == TaskState.COMPLETED)
        self.tick()
        self.window.downloads_page._perform("remove", task.id)
        self.assertIsNone(self.downloads.task(task.id))
        self.assertFalse(self.window.history.has("aaaaaaaaaaa"))

    def test_a_finished_list_survives_a_restart(self):
        task = self.start("aaaaaaaaaaa")[0]
        _Pipeline.gate.set()
        spin(lambda: task.state == TaskState.COMPLETED)
        self.tick()

        from audix.ui.main_window import MainWindow

        second = MainWindow(self.config, _FakeFFmpeg())
        self.addCleanup(second.deleteLater)
        self.addCleanup(second.downloads_page._timer.stop)
        self.assertEqual([t.entry.video_id for t in second.downloads.tasks()], ["aaaaaaaaaaa"])
        self.assertEqual(second.downloads.tasks()[0].state, TaskState.COMPLETED)


class Shell(WindowCase):
    def test_alt_numbers_tune_the_dial_without_touching_editor_zoom(self):
        self.window.activateWindow()
        for index in range(5):
            self.window.dial._activate(index)
            QApplication.processEvents()
            self.assertEqual(self.window.pages.currentIndex(), index)
            self.assertEqual(self.window.dial.current(), index)

    def test_badges_follow_the_queue_and_downloads(self):
        dial = self.window.dial
        self.fill("aaaaaaaaaaa", "bbbbbbbbbbb")
        self.assertEqual(dial._buttons[1].badge, "2")
        QTest.mouseClick(self.page.download_all_key, Qt.LeftButton)
        self.assertEqual(dial._buttons[1].badge, "")
        self.assertEqual(dial._buttons[2].badge, "2")

    def test_a_busy_count_cannot_hide_an_unseen_failure(self):
        dial = self.window.dial
        self.config.concurrent_downloads = 2
        tasks = [DownloadTask(entry=entry(v), audio_format="mp3", bitrate="320",
                              output_dir=self.config.output_dir)
                 for v in ("aaaaaaaaaaa", "bbbbbbbbbbb")]
        self.downloads.add_tasks(tasks)
        spin(lambda: all(t.state == TaskState.DOWNLOADING for t in tasks))

        tasks[0].state = TaskState.FAILED
        page = self.window.downloads_page
        page.model.unseen.add(tasks[0].id)
        page._report_attention()
        self.assertEqual(dial._buttons[2].badge, "2")
        self.assertEqual(dial._buttons[2].lamp, COLORS["accent"])

        self.window._go(2, animate=False)
        QApplication.processEvents()
        self.assertEqual(dial._buttons[2].lamp, "")

    def test_the_editor_invitation_fills_the_recessed_waveform(self):
        self.window._go(3, animate=False)
        QApplication.processEvents()
        editor = self.window.editor_page
        self.assertEqual(editor._empty_overlay.size(), editor.waveform.size())
        self.window.resize(1100, 760)
        QApplication.processEvents()
        self.assertEqual(editor._empty_overlay.size(), editor.waveform.size())

    def test_an_empty_queue_shows_no_keys_that_could_only_refuse(self):
        self.assertFalse(self.page.list_header.isVisibleTo(self.page))
        self.fill("aaaaaaaaaaa")
        self.assertTrue(self.page.list_header.isVisibleTo(self.page))

    def test_the_signal_meter_opens_downloads(self):
        QTest.mouseClick(self.window.dial.signal, Qt.LeftButton)
        self.assertEqual(self.window.pages.currentWidget(), self.window.downloads_page)

    def test_quitting_mid_download_returns_tracks_to_the_queue(self):
        self.fill("aaaaaaaaaaa", "bbbbbbbbbbb")
        QTest.mouseClick(self.page.download_all_key, Qt.LeftButton)
        self.assertTrue(self.queue.is_empty())

        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes) as asked:
            self.window.close()
        self.assertIn("go back to your Queue", asked.call_args[0][2])

        from audix.core.link_queue import LinkQueue

        reborn = LinkQueue(self.config, self.window.history)
        self.addCleanup(reborn.shutdown)
        self.assertEqual({i.entry.video_id for i in reborn.items()},
                         {"aaaaaaaaaaa", "bbbbbbbbbbb"})

    def test_declining_to_quit_keeps_everything_running(self):
        self.fill("aaaaaaaaaaa")
        QTest.mouseClick(self.page.download_all_key, Qt.LeftButton)
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.No):
            self.assertFalse(self.window.close())
        self.assertTrue(self.downloads.tasks()[0].state.is_active
                        or self.downloads.tasks()[0].state == TaskState.PENDING)

    def test_an_unwritable_folder_keeps_tracks_in_the_queue(self):
        self.fill("aaaaaaaaaaa")
        self.config.output_dir = str(paths.config_file() / "not-a-folder")
        paths.config_file().write_text("{}", encoding="utf-8")
        with mock.patch.object(self.window.toasts, "show") as note:
            QTest.mouseClick(self.page.download_all_key, Qt.LeftButton)
        self.assertEqual(len(self.queue.items()), 1)
        self.assertFalse(self.downloads.tasks())
        self.assertIn("cannot be written", note.call_args[0][0])


class SettingsPage(WindowCase):
    def test_a_change_saves_itself_and_reaches_the_queue_strip(self):
        page = self.window.settings_page
        selector = page.format_selector
        selector.format_combo.setCurrentIndex(selector.format_combo.findData("opus"))
        spin(lambda: self.config.audio_format == "opus", timeout=2)
        self.assertEqual(self.page.format_selector.format_key(), "opus")

    def test_a_format_chosen_in_the_queue_reaches_settings(self):
        selector = self.page.format_selector
        selector.format_combo.setCurrentIndex(selector.format_combo.findData("flac"))
        self.assertEqual(self.window.settings_page.format_selector.format_key(), "flac")

    def test_a_bad_folder_is_refused_with_the_reason(self):
        page = self.window.settings_page
        paths.config_file().write_text("{}", encoding="utf-8")
        page.output_input.setText(str(paths.config_file() / "not-a-folder"))
        page.save_to_config()
        self.assertIn("cannot be used", page.feedback_label.text())


if __name__ == "__main__":
    unittest.main()
