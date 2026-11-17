import io
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import mutagen

from spotify_to_yoto import state
from spotify_to_yoto.yoto import push as yoto


def make_files(folder, names, size=10):
    for name in names:
        (folder / name).write_bytes(b"x" * size)


def upload_result(n):
    return {"sha": f"sha{n}", "format": "opus", "channels": "stereo", "duration": 100 + n}


class Image(io.BytesIO):
    headers = {"Content-Type": "image/jpeg"}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ReadTracksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def read(self, probed):
        with mock.patch.object(yoto, "read_tags", side_effect=lambda path: probed[path.name]):
            return yoto.read_tracks(self.folder)

    def test_reads_numbered_files_in_order(self):
        make_files(self.folder, ["02 - B - Two.m4a", "01 - A - One.m4a", "cover.png", "notes.m4a"])
        tracks, missing = self.read({"01 - A - One.m4a": ("One", 100.0), "02 - B - Two.m4a": ("Two", 200.0)})
        self.assertEqual([t.title for t in tracks], ["One", "Two"])
        self.assertEqual([t.number for t in tracks], [1, 2])
        self.assertEqual(missing, [])
        self.assertEqual(tracks[1].seconds, 200.0)
        self.assertEqual(tracks[0].size, 10)

    def test_gap_is_reported(self):
        names = ["01 - A - One.m4a", "02 - B - Two.m4a", "04 - D - Four.m4a"]
        make_files(self.folder, names)
        tracks, missing = self.read({n: ("t", 1.0) for n in names})
        self.assertEqual([t.number for t in tracks], [1, 2, 4])
        self.assertEqual(missing, [3])

    def test_title_falls_back_to_file_name(self):
        make_files(self.folder, ["01 - A - One.m4a"])
        tracks, _ = self.read({"01 - A - One.m4a": (None, 1.0)})
        self.assertEqual(tracks[0].title, "A - One")


class TagsTest(unittest.TestCase):
    def test_read_tags_uses_mutagen(self):
        song = mock.Mock(tags={"\xa9nam": ["春泥棒"]}, info=mock.Mock(length=245.3))
        with mock.patch.object(yoto, "MP4", return_value=song) as mp4:
            self.assertEqual(yoto.read_tags(Path("/x/01 - a.m4a")), ("春泥棒", 245.3))
        mp4.assert_called_once_with(Path("/x/01 - a.m4a"))

    def test_no_title_tag(self):
        song = mock.Mock(tags=None, info=mock.Mock(length=10.0))
        with mock.patch.object(yoto, "MP4", return_value=song):
            self.assertEqual(yoto.read_tags(Path("/x/01 - a.m4a")), (None, 10.0))

    def test_unreadable_file_stops_the_push(self):
        with mock.patch.object(yoto, "MP4", side_effect=mutagen.MutagenError("not an MP4")):
            with self.assertRaises(yoto.PushError) as err:
                yoto.read_tags(Path("/x/02 - B - Two.m4a"))
        self.assertIn("02 - B - Two.m4a", str(err.exception))


class CheckLimitsTest(unittest.TestCase):
    def tracks(self, count, size=1_000_000, seconds=100.0):
        return [yoto.Track(i, Path(f"{i:02d} - a.m4a"), "t", seconds, size) for i in range(1, count + 1)]

    def test_normal_playlist_passes(self):
        self.assertEqual(yoto.check_limits(self.tracks(41)), [])

    def test_too_many_tracks(self):
        problems = yoto.check_limits(self.tracks(101))
        self.assertEqual(len(problems), 1)
        self.assertIn("100 tracks", problems[0])

    def test_track_too_big(self):
        tracks = self.tracks(2)
        tracks[1] = tracks[1]._replace(size=100_000_001)
        problems = yoto.check_limits(tracks)
        self.assertTrue(any("100 MB" in p and "02 - a.m4a" in p for p in problems), problems)

    def test_track_too_long(self):
        tracks = self.tracks(2)
        tracks[0] = tracks[0]._replace(seconds=3601.0)
        self.assertTrue(any("60 minutes" in p for p in yoto.check_limits(tracks)))

    def test_total_too_big(self):
        problems = yoto.check_limits(self.tracks(6, size=90_000_000))
        self.assertTrue(any("500 MB" in p for p in problems), problems)

    def test_total_too_long(self):
        problems = yoto.check_limits(self.tracks(6, seconds=3001.0))
        self.assertTrue(any("5 hours" in p for p in problems), problems)


class ChaptersTest(unittest.TestCase):
    def test_chapters_shape(self):
        # File numbers 1, 2, 4 (3 failed to download): the player still counts 1, 2, 3.
        tracks = [yoto.Track(n, Path(f"{n:02d} - x.m4a"), f"Song {n}", 100.0, 10) for n in (1, 2, 4)]
        out = yoto.chapters(tracks, [upload_result(n) for n in (1, 2, 4)])
        self.assertEqual(out[2], {
            "key": "03", "title": "Song 4", "overlayLabel": "3",
            "tracks": [{"key": "01", "title": "Song 4", "overlayLabel": "3", "type": "audio",
                        "trackUrl": "yoto:#sha4", "format": "opus", "channels": "stereo", "duration": 104}]})
        self.assertEqual([c["key"] for c in out], ["01", "02", "03"])


class PushTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.name = "Road Trip Mix"
        self.folder = Path(self.tmp.name) / self.name
        self.folder.mkdir()
        self.tracks = [yoto.Track(n, self.folder / f"{n:02d} - a.m4a", f"Song {n}", 100.0, 10) for n in (1, 2)]
        self.read = self.patch("read_tracks", mock.Mock(return_value=(self.tracks, [])))
        self.upload = self.patch("upload", mock.Mock(side_effect=lambda p: upload_result(int(p.name[:2]))))
        self.get_card = self.patch("get_card", mock.Mock(return_value=None))
        self.save_card = self.patch("save_card", mock.Mock(return_value="new1"))
        self.upload_cover = self.patch("upload_cover", mock.Mock(return_value="https://yoto/cover"))
        self.fetch = self.patch("urlopen", mock.Mock(side_effect=lambda url, timeout=None: Image(b"jpg")))

    def patch(self, name, value):
        patcher = mock.patch.object(yoto, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def remember(self, **values):
        data = state.load(self.folder)
        data.update(values)
        state.save(self.folder, data)

    def stored(self):
        return state.load(self.folder)["yoto"]

    def push(self):
        out = io.StringIO()
        with redirect_stdout(out):
            card = yoto.push(self.folder)
        return card, out.getvalue()

    def test_first_push_creates_and_remembers(self):
        self.assertEqual(self.push()[0], "new1")
        payload = self.save_card.call_args[0][0]
        self.assertNotIn("cardId", payload)
        self.assertEqual(payload["title"], self.name)
        self.assertEqual([c["title"] for c in payload["content"]["chapters"]], ["Song 1", "Song 2"])
        self.get_card.assert_not_called()
        self.assertEqual(self.stored(), "new1")

    def test_title_is_the_playlist_name_from_state(self):
        self.remember(name="Ari: Mixtape")
        self.push()
        self.assertEqual(self.save_card.call_args[0][0]["title"], "Ari: Mixtape")

    def test_rerun_updates_and_keeps_cover(self):
        self.remember(yoto="c1", cover="https://i.scdn.co/image/x")
        metadata = {"cover": {"imageL": "https://cover"}, "description": "mine"}
        self.get_card.return_value = {"cardId": "c1", "title": "old", "metadata": metadata}
        self.save_card.return_value = "c1"
        self.assertEqual(self.push()[0], "c1")
        payload = self.save_card.call_args[0][0]
        self.assertEqual(payload["cardId"], "c1")
        self.assertEqual(payload["metadata"], metadata)
        self.upload_cover.assert_not_called()
        self.assertEqual(self.stored(), "c1")

    def test_first_push_sets_spotify_cover(self):
        self.remember(cover="https://i.scdn.co/image/x")
        self.push()
        self.assertEqual(self.fetch.call_args[0][0], "https://i.scdn.co/image/x")
        self.upload_cover.assert_called_once_with(b"jpg", "image/jpeg")
        self.assertEqual(self.save_card.call_args[0][0]["metadata"], {"cover": {"imageL": "https://yoto/cover"}})

    def test_deleted_playlist_is_made_again_with_cover(self):
        self.remember(yoto="gone", cover="https://i.scdn.co/image/x")
        self.assertEqual(self.push()[0], "new1")
        payload = self.save_card.call_args[0][0]
        self.assertNotIn("cardId", payload)
        self.assertEqual(payload["metadata"], {"cover": {"imageL": "https://yoto/cover"}})
        self.assertEqual(self.stored(), "new1")

    def test_cover_failure_does_not_stop_push(self):
        self.remember(cover="https://i.scdn.co/image/x")
        self.fetch.side_effect = urllib.error.URLError("no network")
        card, out = self.push()
        self.assertEqual(card, "new1")
        self.assertNotIn("metadata", self.save_card.call_args[0][0])
        self.assertIn("cover", out)

    def test_cover_refused_by_yoto_does_not_stop_push(self):
        self.remember(cover="https://i.scdn.co/image/x")
        self.upload_cover.side_effect = yoto.YotoError("Yoto answered 400")
        self.assertEqual(self.push()[0], "new1")
        self.assertNotIn("metadata", self.save_card.call_args[0][0])

    def test_failed_upload_saves_nothing(self):
        def fail_second(path):
            if path.name.startswith("02"):
                raise yoto.YotoError("Yoto answered 500 to GET /media/transcode/audio/uploadUrl: oops")
            return upload_result(1)
        self.upload.side_effect = fail_second
        with self.assertRaises(yoto.PushError) as err:
            self.push()
        self.assertIn("02 - a.m4a", str(err.exception))
        self.save_card.assert_not_called()
        self.assertIsNone(self.stored())

    def test_connection_failure_names_the_song(self):
        self.upload.side_effect = ConnectionResetError("connection reset")
        with self.assertRaises(yoto.PushError) as err:
            self.push()
        self.assertIn("a.m4a", str(err.exception))
        self.assertIn("connection reset", str(err.exception))
        self.save_card.assert_not_called()

    def test_over_limits_uploads_nothing(self):
        with mock.patch.object(yoto, "check_limits", return_value=["Too big."]):
            with self.assertRaises(yoto.PushError) as err:
                self.push()
        self.assertIn("Too big.", str(err.exception))
        self.upload.assert_not_called()

    def test_gap_is_printed(self):
        self.read.return_value = (self.tracks, [3])
        _, out = self.push()
        self.assertIn("3", out.splitlines()[0])

    def test_unicode_names(self):
        self.folder = self.folder.with_name("Kids' キャンディ Mix")
        self.folder.mkdir()
        self.tracks[1] = self.tracks[1]._replace(title="キャンディーキューティー")
        self.push()
        payload = self.save_card.call_args[0][0]
        self.assertEqual(payload["title"], "Kids' キャンディ Mix")
        self.assertEqual(payload["content"]["chapters"][1]["title"], "キャンディーキューティー")

    def test_no_songs(self):
        self.read.return_value = ([], [])
        with self.assertRaises(yoto.PushError):
            self.push()

    def test_missing_folder(self):
        self.folder = self.folder.with_name("Nope")
        with self.assertRaises(yoto.PushError) as err:
            self.push()
        self.assertIn("Nope", str(err.exception))
        self.assertIn(self.name, str(err.exception))


if __name__ == "__main__":
    unittest.main()
