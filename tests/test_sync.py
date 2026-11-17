import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from spotdl.providers.audio.base import AudioProviderError

from spotify_to_yoto import spotify, state, sync
from spotify_to_yoto.matcher import Match
from spotify_to_yoto.spotify import Playlist, SongInfo
from spotify_to_yoto.yoto import push

URL = "https://open.spotify.com/playlist/p"


def song(n, name=None):
    name = name or f"Song {n}"
    spotdl = types.SimpleNamespace(url=f"https://open.spotify.com/track/t{n}", name=name, download_url=None)
    return SongInfo(spotdl.url, name, ["A"], 200, False, n, spotdl)


def match_for(url):
    n = url.rsplit("v=", 1)[-1]
    return Match(url, f"Song {n}", ["A"], None, "Album", 200.0, False)


class FakeMatcher:
    def __init__(self, missing=()):
        self.found, self.described, self.missing = [], [], set(missing)

    def find(self, spotdl):
        self.found.append(spotdl.url)
        if spotdl.url in self.missing:
            return None
        return match_for(f"https://music.youtube.com/watch?v={spotdl.url[-1]}")

    def describe(self, url):
        self.described.append(url)
        return match_for(url)


class FakeFetcher:
    asked = []
    drop = set()

    def __init__(self, folder):
        self.folder = folder

    def get(self, songs):
        got = {}
        for s in songs:
            FakeFetcher.asked.append(s.url)
            if s.url in FakeFetcher.drop:
                continue
            path = self.folder / f"A - {s.name}.m4a"
            path.write_text(s.download_url)  # the file's content says which upload it came from
            got[s.url] = path
        return got


class SyncTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.music = Path(tmp.name)
        FakeFetcher.asked, FakeFetcher.drop = [], set()
        self.matcher = FakeMatcher()
        patcher = mock.patch.object(push, "read_tags", side_effect=lambda path: (path.stem, 200.0))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.albums = {}
        patcher = mock.patch.object(push, "read_album", side_effect=lambda path: self.albums.get(path.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_sync(self, songs, name="Mix", length=None):
        playlist = Playlist(URL, name, "https://cover", length or len(songs), songs)
        return sync.sync(URL, self.music, fetch=lambda url: playlist, matcher=self.matcher, fetcher=FakeFetcher)

    def files(self, folder):
        return sorted(p.name for p in folder.iterdir() if p.suffix == ".m4a")

    def test_first_sync_downloads_numbers_and_writes_m3u8(self):
        result = self.run_sync([song(1), song(2)])
        folder = self.music / "Mix"
        self.assertEqual(result.folder, folder)
        self.assertEqual(self.files(folder), ["01 - A - Song 1.m4a", "02 - A - Song 2.m4a"])
        self.assertEqual((self.music / "Mix.m3u8").read_text(encoding="utf-8"), "\n".join([
            "#EXTM3U", "#EXTINF:200,A - Song 1", "Mix/01 - A - Song 1.m4a",
            "#EXTINF:200,A - Song 2", "Mix/02 - A - Song 2.m4a"]) + "\n")
        data = state.load(folder)
        self.assertEqual((data["spotify"], data["name"], data["cover"]), (URL, "Mix", "https://cover"))
        self.assertEqual(data["songs"]["https://open.spotify.com/track/t2"]["file"], "02 - A - Song 2.m4a")
        self.assertEqual(result.report, "Mix: 2 songs, all fine")

    def test_second_sync_downloads_nothing(self):
        self.run_sync([song(1), song(2)])
        FakeFetcher.asked, self.matcher.found = [], []
        self.run_sync([song(1), song(2)])
        self.assertEqual(FakeFetcher.asked, [])
        self.assertEqual(self.matcher.found, [])

    def test_reorder_swaps_without_overwriting(self):
        self.run_sync([song(1), song(2)])
        a, b = song(1)._replace(position=2), song(2)._replace(position=1)
        self.run_sync([b, a])
        folder = self.music / "Mix"
        self.assertEqual(self.files(folder), ["01 - A - Song 2.m4a", "02 - A - Song 1.m4a"])
        self.assertTrue((folder / "01 - A - Song 2.m4a").read_text().endswith("v=2"))
        self.assertTrue((folder / "02 - A - Song 1.m4a").read_text().endswith("v=1"))

    def test_removed_song_is_deleted(self):
        self.run_sync([song(1), song(2)])
        self.run_sync([song(1)])
        folder = self.music / "Mix"
        self.assertEqual(self.files(folder), ["01 - A - Song 1.m4a"])
        self.assertNotIn("https://open.spotify.com/track/t2", state.load(folder)["songs"])

    def test_fix_replaces_the_match_and_file(self):
        self.run_sync([song(1), song(2)])
        folder = self.music / "Mix"
        data = state.load(folder)
        data["fixes"]["https://open.spotify.com/track/t2"] = "https://music.youtube.com/watch?v=fixed"
        state.save(folder, data)
        FakeFetcher.asked = []
        self.run_sync([song(1), song(2)])
        self.assertEqual(FakeFetcher.asked, ["https://open.spotify.com/track/t2"])
        self.assertEqual(self.matcher.described, ["https://music.youtube.com/watch?v=fixed"])
        self.assertEqual((folder / "02 - A - Song 2.m4a").read_text(), "https://music.youtube.com/watch?v=fixed")
        entry = state.load(folder)["songs"]["https://open.spotify.com/track/t2"]
        self.assertEqual(entry["match"]["url"], "https://music.youtube.com/watch?v=fixed")
        FakeFetcher.asked = []
        self.run_sync([song(1), song(2)])
        self.assertEqual(FakeFetcher.asked, [])  # the fix is kept, not downloaded again

    def test_dropped_download_is_reported_missing(self):
        FakeFetcher.drop = {"https://open.spotify.com/track/t2"}
        result = self.run_sync([song(1), song(2)])
        self.assertIn("02 Missing", result.report)
        self.assertIn("download failed", result.report)
        FakeFetcher.asked = []
        FakeFetcher.drop = set()
        self.run_sync([song(1), song(2)])
        self.assertEqual(FakeFetcher.asked, ["https://open.spotify.com/track/t2"])  # tried again next time

    def test_no_match_is_reported_and_retried(self):
        self.matcher.missing = {"https://open.spotify.com/track/t1"}
        result = self.run_sync([song(1)])
        self.assertIn("no match on YouTube Music", result.report)
        self.matcher.missing, self.matcher.found = set(), []
        self.run_sync([song(1)])
        self.assertEqual(self.matcher.found, ["https://open.spotify.com/track/t1"])

    def test_state_saved_before_numbering(self):
        with mock.patch.object(sync, "_number", side_effect=RuntimeError("stopped")):
            with self.assertRaises(RuntimeError):
                self.run_sync([song(1)])
        entry = state.load(self.music / "Mix")["songs"]["https://open.spotify.com/track/t1"]
        self.assertEqual(entry["base"], "A - Song 1.m4a")
        self.assertTrue((self.music / "Mix" / entry["file"]).exists())
        FakeFetcher.asked = []
        self.run_sync([song(1)])
        self.assertEqual(FakeFetcher.asked, [])
        self.assertEqual(self.files(self.music / "Mix"), ["01 - A - Song 1.m4a"])

    def test_fixed_song_is_not_flagged_for_its_title(self):
        self.run_sync([song(1)])
        folder = self.music / "Mix"
        data = state.load(folder)
        data["fixes"]["https://open.spotify.com/track/t1"] = "https://music.youtube.com/watch?v=cover"
        state.save(folder, data)
        self.matcher.describe = lambda url: Match(url, "Song 1 (Tom Petty Cover)", [], "A", None, 200.0, None)
        self.assertEqual(self.run_sync([song(1)]).report, "Mix: 1 songs, all fine")

    def test_spotify_album_reaches_the_checks(self):
        self.matcher.find = lambda spotdl: Match("https://music.youtube.com/watch?v=1", "Song 1 (Live)", ["A"], None,
                                                 "Live at Home", 200.0, False)
        self.albums = {"01 - A - Song 1.m4a": "Live at Home"}
        self.assertEqual(self.run_sync([song(1)]).report, "Mix: 1 songs, all fine")

    def test_two_songs_with_one_name_keep_two_files(self):
        # The same song added from the album and from a single: spotDL names both "A - Same.m4a".
        a, b = song(1, name="Same"), song(2, name="Same")
        self.run_sync([a, b])
        folder = self.music / "Mix"
        self.assertEqual(self.files(folder), ["01 - A - Same.m4a", "02 - A - Same (2).m4a"])
        self.assertTrue((folder / "01 - A - Same.m4a").read_text().endswith("v=1"))
        self.assertTrue((folder / "02 - A - Same (2).m4a").read_text().endswith("v=2"))
        FakeFetcher.asked = []
        self.run_sync([a, b])
        self.assertEqual(FakeFetcher.asked, [])

    def test_names_differing_only_in_case_keep_two_files(self):
        # Mac and Windows folders treat "Same" and "same" as one name.
        self.run_sync([song(1, name="Same"), song(2, name="same")])
        self.assertEqual(self.files(self.music / "Mix"), ["01 - A - Same.m4a", "02 - A - same (2).m4a"])

    def test_interrupted_renumbering_recovers(self):
        self.run_sync([song(1), song(2)])
        swapped = [song(2)._replace(position=1), song(1)._replace(position=2)]
        with mock.patch.object(sync, "_place", side_effect=RuntimeError("stopped")):
            with self.assertRaises(RuntimeError):
                self.run_sync(swapped)
        FakeFetcher.asked = []
        self.run_sync(swapped)
        self.assertEqual(FakeFetcher.asked, [])
        self.assertEqual(self.files(self.music / "Mix"), ["01 - A - Song 2.m4a", "02 - A - Song 1.m4a"])

    def test_stray_temporary_files_are_swept(self):
        self.run_sync([song(1)])
        (self.music / "Mix" / ".renaming-3.m4a").write_text("old")
        (self.music / "Mix" / ".download-9.m4a").write_text("old")
        self.run_sync([song(1)])
        self.assertEqual(self.files(self.music / "Mix"), ["01 - A - Song 1.m4a"])

    def test_short_listing_deletes_nothing(self):
        # Spotify's listing can drop a song it can't format: its file must not go.
        self.run_sync([song(1), song(2), song(3)])
        report = self.run_sync([song(1), song(3)], length=3).report
        self.assertEqual(self.files(self.music / "Mix"),
                         ["01 - A - Song 1.m4a", "02 - A - Song 2.m4a", "03 - A - Song 3.m4a"])
        self.assertIn("nothing was deleted", report)

    def test_empty_listing_changes_nothing(self):
        self.run_sync([song(1)])
        with self.assertRaises(spotify.SpotifyFailure):
            self.run_sync([], length=0)
        self.assertEqual(self.files(self.music / "Mix"), ["01 - A - Song 1.m4a"])

    def test_dead_fix_keeps_the_song_and_says_so(self):
        self.run_sync([song(1)])
        folder = self.music / "Mix"
        data = state.load(folder)
        data["fixes"]["https://open.spotify.com/track/t1"] = "https://music.youtube.com/watch?v=dead"
        state.save(folder, data)
        self.matcher.describe = mock.Mock(side_effect=AudioProviderError("YT-DLP download error"))
        report = self.run_sync([song(1)]).report
        self.assertEqual(self.files(folder), ["01 - A - Song 1.m4a"])
        self.assertIn("watch?v=dead", report)

    def test_search_error_reports_missing(self):
        self.matcher.find = mock.Mock(side_effect=Exception("YouTube Music said no"))
        self.assertIn("01 Missing", self.run_sync([song(1)]).report)

    def test_unsafe_playlist_name(self):
        result = self.run_sync([song(1)], name="Road: Trip?")
        self.assertEqual(result.folder.name, "Road_ Trip_")
        self.assertEqual(state.load(result.folder)["name"], "Road: Trip?")
        self.assertTrue(result.report.startswith("Road: Trip?: 1 songs"))

    def test_wide_playlist_numbers_with_three_digits(self):
        self.run_sync([song(1)], length=120)
        self.assertEqual(self.files(self.music / "Mix"), ["001 - A - Song 1.m4a"])


if __name__ == "__main__":
    unittest.main()
