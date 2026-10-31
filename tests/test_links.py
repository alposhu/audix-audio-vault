"""A link that names a video must mean that video, whatever else it carries."""
import unittest
from unittest import mock

from audix.core import links
from audix.core.downloader import (
    ExtractionError, MIX_TRACK_LIMIT, Scope, _batch_from_playlist, resolve_targets,
)

VIDEO = "dQw4w9WgXcQ"
#: Exactly what the embedded browser's address bar holds after clicking a Mix.
MIX_URL = f"https://www.youtube.com/watch?v={VIDEO}&list=RD{VIDEO}&start_radio=1"
PLAYLIST_URL = f"https://www.youtube.com/watch?v={VIDEO}&list=PLabcdefghij1234567890&index=3"


class ParseLink(unittest.TestCase):
    def test_every_video_url_shape_yields_the_id(self):
        for url in (
            f"https://www.youtube.com/watch?v={VIDEO}",
            f"https://youtube.com/watch?feature=share&v={VIDEO}",
            f"https://m.youtube.com/watch?v={VIDEO}",
            f"https://music.youtube.com/watch?v={VIDEO}&si=abc",
            f"https://youtu.be/{VIDEO}",
            f"https://youtu.be/{VIDEO}?si=tracking&t=30",
            f"https://www.youtube.com/shorts/{VIDEO}",
            f"https://www.youtube.com/live/{VIDEO}?feature=share",
            f"https://www.youtube.com/embed/{VIDEO}",
            f"https://www.youtube-nocookie.com/embed/{VIDEO}",
        ):
            with self.subTest(url=url):
                self.assertEqual(links.parse(url).video_id, VIDEO)

    def test_mix_is_recognised_in_every_form(self):
        for list_id in (f"RD{VIDEO}", "RDMM", f"RDMM{VIDEO}", f"RDAMVM{VIDEO}",
                        "RDEMabcdefghijklmnop", "RDCMUCabcdefghij"):
            with self.subTest(list_id=list_id):
                self.assertTrue(links.is_mix_id(list_id))

    def test_curated_and_ordinary_lists_are_not_mixes(self):
        for list_id in ("RDCLAK5uy_kmPRjHDECIcuVwnKsx2Ng7fyNgFKWNJFs",
                        "PLabcdefghij", "OLAK5uy_abcdefg", "UUabcdefg", "WL", "LL", "LM"):
            with self.subTest(list_id=list_id):
                self.assertFalse(links.is_mix_id(list_id))

    def test_video_url_drops_list_and_tracking(self):
        link = links.parse(f"{MIX_URL}&pp=ygUIcmljayBhc3Rs&t=42s")
        self.assertEqual(link.video_url, f"https://www.youtube.com/watch?v={VIDEO}")
        self.assertTrue(link.is_mix)

    def test_list_only_link_has_no_video(self):
        link = links.parse("https://www.youtube.com/playlist?list=PLabcdefghij")
        self.assertFalse(link.has_video)
        self.assertEqual(link.list_id, "PLabcdefghij")

    def test_host_is_parsed_not_substring_matched(self):
        self.assertFalse(links.parse(f"https://evil.example/?u=youtube.com&v={VIDEO}").is_youtube)
        self.assertFalse(links.parse(f"https://notyoutube.com/watch?v={VIDEO}").is_youtube)

    def test_invalid_ids_are_rejected(self):
        self.assertEqual(links.parse("https://www.youtube.com/watch?v=short").video_id, "")

    def test_garbage_never_raises(self):
        for text in ("", None, "not a url", "http://[bad", "https://", "ftp://youtube.com"):
            with self.subTest(text=text):
                self.assertFalse(links.parse(text).is_youtube)


class FindLinks(unittest.TestCase):
    def test_multi_line_paste_in_order_without_duplicates(self):
        text = (f"https://youtu.be/{VIDEO}\n"
                f"check this: (https://youtu.be/{VIDEO}x), and\n"
                f"https://youtu.be/{VIDEO}\n"
                "plain words")
        self.assertEqual(links.find_links(text), [
            f"https://youtu.be/{VIDEO}", f"https://youtu.be/{VIDEO}x",
        ])

    def test_missing_scheme_is_filled_in(self):
        self.assertEqual(links.find_links(f"youtube.com/watch?v={VIDEO}"),
                         [f"https://youtube.com/watch?v={VIDEO}"])


class _FakeYoutubeDL:
    """Records what yt-dlp was asked for, and answers the way the real one does."""

    calls = []

    def __init__(self, options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def extract_info(self, url, download=False):
        _FakeYoutubeDL.calls.append((url, self.options))
        if self.options["noplaylist"] or "list=" not in url:
            return {"id": VIDEO, "title": "The one song", "webpage_url": url,
                    "duration": 213, "uploader": "Rick"}
        return {"_type": "playlist", "title": "Mix - The one song",
                "entries": [{"id": f"video{n:06d}", "title": f"Track {n}"}
                            for n in range(383)]}


class ResolveTargets(unittest.TestCase):
    def setUp(self):
        _FakeYoutubeDL.calls = []
        patcher = mock.patch("yt_dlp.YoutubeDL", _FakeYoutubeDL)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.config = mock.Mock(use_browser_cookies=False, proxy="",
                                fixed_user_agent="", rotate_user_agent=False)

    def test_browser_mix_url_yields_only_the_video(self):
        """The reported bug: one song arriving as a 383-track radio mix."""
        batch = resolve_targets(MIX_URL, self.config)
        self.assertFalse(batch.is_playlist)
        self.assertEqual(len(batch.entries), 1)
        self.assertEqual(batch.entries[0].title, "The one song")

        url, options = _FakeYoutubeDL.calls[0]
        self.assertEqual(url, f"https://www.youtube.com/watch?v={VIDEO}")
        self.assertTrue(options["noplaylist"])

    def test_video_inside_a_playlist_yields_only_the_video(self):
        batch = resolve_targets(PLAYLIST_URL, self.config)
        self.assertEqual(len(batch.entries), 1)
        self.assertFalse(batch.is_playlist)

    def test_the_skipped_list_is_kept_as_an_offer(self):
        batch = resolve_targets(MIX_URL, self.config)
        self.assertTrue(batch.parent_list.is_mix)
        self.assertEqual(batch.parent_list.list_id, f"RD{VIDEO}")
        self.assertEqual(batch.parent_list.url, MIX_URL)

        plain = resolve_targets(f"https://youtu.be/{VIDEO}", self.config)
        self.assertIsNone(plain.parent_list)

    def test_a_plain_playlist_link_still_expands(self):
        batch = resolve_targets("https://www.youtube.com/playlist?list=PLabcdefghij",
                                self.config)
        self.assertTrue(batch.is_playlist)
        self.assertEqual(len(batch.entries), 383)

    def test_whole_list_is_available_when_asked_for(self):
        batch = resolve_targets(MIX_URL, self.config, Scope.WHOLE_LIST)
        self.assertTrue(batch.is_playlist)
        self.assertTrue(batch.is_mix)
        _url, options = _FakeYoutubeDL.calls[0]
        self.assertFalse(options["noplaylist"])
        self.assertEqual(options["playlistend"], MIX_TRACK_LIMIT)

    def test_a_real_playlist_has_no_ceiling(self):
        resolve_targets(PLAYLIST_URL, self.config, Scope.WHOLE_LIST)
        _url, options = _FakeYoutubeDL.calls[0]
        self.assertNotIn("playlistend", options)

    def test_a_mix_that_loops_keeps_each_track_once_numbered_in_order(self):
        looped = [{"id": f"video{n:06d}", "title": f"Track {n}"} for n in (1, 2, 3, 1, 2, 4, 1)]
        batch = _batch_from_playlist({"title": "Mix - Someone", "entries": looped})
        self.assertEqual([e.video_id for e in batch.entries],
                         ["video000001", "video000002", "video000003", "video000004"])
        self.assertEqual([e.playlist_index for e in batch.entries], [1, 2, 3, 4])
        self.assertEqual({e.playlist_count for e in batch.entries}, {4})

    def test_non_urls_are_refused_with_a_reason(self):
        with self.assertRaises(ExtractionError):
            resolve_targets("rick astley", self.config)


if __name__ == "__main__":
    unittest.main()
