import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from spotify_to_yoto import download


class FakeDownloader:
    made = []

    def __init__(self, settings):
        self.settings = settings
        self.calls = []
        FakeDownloader.made.append(self)

    def download_multiple_songs(self, songs):
        self.calls.append([s.url for s in songs])
        out = []
        for s in songs:
            dropped = s.url.endswith("flaky") and len(self.calls) == 1
            out.append((s, None if dropped or s.url.endswith("gone") else Path(f"/m/{s.url[-5:]}.m4a")))
        return out


def song(url):
    return types.SimpleNamespace(url=url, download_url="https://music.youtube.com/watch?v=x")


class FetcherTest(unittest.TestCase):
    def setUp(self):
        FakeDownloader.made = []
        patcher = mock.patch.object(download, "Downloader", FakeDownloader)
        patcher.start()
        self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)

    def test_fetcher_settings(self):
        download.Fetcher(self.folder).get([song("u/a")])
        s = FakeDownloader.made[0].settings
        self.assertEqual(s["format"], "m4a")
        self.assertEqual(s["bitrate"], "disable")
        self.assertEqual(s["output"], str(self.folder / "{artists} - {title}.{output-ext}"))
        self.assertEqual(s["threads"], 8)
        self.assertEqual(s["lyrics_providers"], [])
        self.assertEqual(s["audio_providers"], ["youtube-music"])
        self.assertTrue(s["only_verified_results"])
        self.assertEqual(s["overwrite"], "force")
        self.assertFalse(s["scan_for_songs"])

    def test_sign_in_reaches_the_downloader(self):
        download.use_sign_in({"browser": "chrome"})
        self.addCleanup(download.use_sign_in, None)
        download.Fetcher(self.folder).get([song("u/a")])
        self.assertEqual(FakeDownloader.made[0].settings["yt_dlp_args"], "--cookies-from-browser chrome")
        self.assertTrue(download.premium())
        download.use_sign_in(False)
        download.Fetcher(self.folder).get([song("u/a")])
        self.assertNotIn("yt_dlp_args", FakeDownloader.made[1].settings)
        self.assertFalse(download.premium())

    def test_sign_in_works_asks_youtube_for_the_premium_stream(self):
        download.use_sign_in({"browser": "chrome"})
        self.addCleanup(download.use_sign_in, None)
        with mock.patch.object(download.youtube, "has_premium", return_value=True) as has:
            self.assertTrue(download.sign_in_works())
        has.assert_called_once_with({"browser": "chrome"})
        with mock.patch.object(download.youtube, "has_premium", side_effect=download.youtube.SignInError("x")):
            self.assertFalse(download.sign_in_works())

    def test_fetcher_retries_dropped_downloads_once(self):
        got = download.Fetcher(self.folder).get([song("u/aaaaa"), song("u/flaky"), song("u/gone")])
        self.assertEqual(FakeDownloader.made[0].calls, [["u/aaaaa", "u/flaky", "u/gone"], ["u/flaky", "u/gone"]])
        self.assertEqual(set(got), {"u/aaaaa", "u/flaky"})

    def test_nothing_to_get(self):
        self.assertEqual(download.Fetcher(self.folder).get([]), {})
        self.assertEqual(FakeDownloader.made, [])


class ToolsTest(unittest.TestCase):
    def test_tools_downloaded_once_when_missing(self):
        with mock.patch.object(download, "is_ffmpeg_installed", return_value=False), \
                mock.patch.object(download, "is_deno_installed", return_value=False), \
                mock.patch.object(download, "download_ffmpeg") as ffmpeg, \
                mock.patch.object(download, "download_deno") as deno, \
                mock.patch("builtins.print"):
            download.ensure_tools()
        ffmpeg.assert_called_once()
        deno.assert_called_once()

    def test_tools_present(self):
        with mock.patch.object(download, "is_ffmpeg_installed", return_value=True), \
                mock.patch.object(download, "is_deno_installed", return_value=True), \
                mock.patch.object(download, "download_ffmpeg") as ffmpeg, \
                mock.patch.object(download, "download_deno") as deno:
            download.ensure_tools()
        ffmpeg.assert_not_called()
        deno.assert_not_called()


if __name__ == "__main__":
    unittest.main()
