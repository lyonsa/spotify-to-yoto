import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from spotdl.providers.audio.base import AudioProviderError

from spotify_to_yoto import cli, download, matcher, settings, spotify, state, sync
from spotify_to_yoto.yoto import push

A = "https://open.spotify.com/playlist/AAAAAAAAaaaa"
B = "https://open.spotify.com/playlist/BBBBBBBBbbbb"
TRACK = "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC"


class CliTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.music = Path(tmp.name)
        self.saved = {"music": str(self.music)}
        self.patch(settings, "load", mock.Mock(side_effect=lambda: dict(self.saved)))
        self.patch(settings, "save", mock.Mock(side_effect=lambda values: self.saved.update(values)))
        self.patch(download, "ensure_tools", mock.Mock())
        self.patch(spotify, "connect", mock.Mock())
        self.sync = self.patch(sync, "sync", mock.Mock(side_effect=self.fake_sync))
        self.push = self.patch(push, "push", mock.Mock(return_value="card1"))
        self.describe = mock.Mock(return_value=None)
        self.patch(matcher, "Matcher", mock.Mock(return_value=mock.Mock(describe=self.describe)))

    def patch(self, owner, name, value):
        patcher = mock.patch.object(owner, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def fake_sync(self, url, music):
        name = {A: "Mix A", B: "Mix B"}[url]
        folder = music / name
        folder.mkdir(parents=True, exist_ok=True)
        data = state.load(folder)
        data.update(spotify=url, name=name)
        state.save(folder, data)
        return sync.Result(folder, f"{name}: 2 songs, all fine")

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_sync_then_prints_push_hint(self):
        code, out, _ = self.run_cli(A, B + "?si=x")
        self.assertEqual(code, 0)
        self.assertEqual([c.args for c in self.sync.call_args_list], [(A, self.music), (B, self.music)])
        self.assertIn("Mix A: 2 songs, all fine", out)
        self.assertIn('To put them on Yoto: spotify-to-yoto push "Mix A" "Mix B"', out)
        self.push.assert_not_called()

    def test_push_flag_pushes_each_after_its_sync(self):
        order = []
        self.sync.side_effect = lambda url, music: order.append(("sync", url)) or self.fake_sync(url, music)
        self.push.side_effect = lambda folder: order.append(("push", folder.name)) or "card"
        code, out, _ = self.run_cli(A, B, "--push")
        self.assertEqual(code, 0)
        self.assertEqual(order, [("sync", A), ("push", "Mix A"), ("sync", B), ("push", "Mix B")])
        self.assertIn('"Mix A" is in your Yoto library. Link it to a card in the Yoto app.', out)
        self.assertNotIn("To put them on Yoto", out)

    def test_one_bad_link_does_not_stop_the_rest(self):
        def flaky(url, music):
            if url == A:
                raise spotify.SpotifyFailure(f"Couldn't read {url} from Spotify. The playlist must be public.")
            return self.fake_sync(url, music)
        self.sync.side_effect = flaky
        code, out, err = self.run_cli(A, B)
        self.assertEqual(code, 1)
        self.assertIn("must be public", err)
        self.assertIn("Mix B: 2 songs", out)

    def test_not_a_playlist_link(self):
        code, _, err = self.run_cli("https://open.spotify.com/album/x")
        self.assertEqual(code, 1)
        self.assertIn("isn't a playlist", err)
        self.sync.assert_not_called()

    def test_music_option(self):
        other = self.music / "other"
        self.run_cli(A, "--music", str(other))
        self.assertEqual(self.sync.call_args.args, (A, other))

    def test_push_takes_a_dragged_path(self):
        (self.music / "Mix A").mkdir()
        code, out, _ = self.run_cli("push", f"{self.music / 'Mix A'}/")
        self.assertEqual(code, 0)
        self.push.assert_called_once_with(self.music / "Mix A")
        self.assertIn('"Mix A" is in your Yoto library', out)

    def test_push_takes_a_name_or_a_link(self):
        self.fake_sync(A, self.music)
        self.run_cli("push", "Mix A")
        self.run_cli("push", A + "?si=1")
        self.assertEqual([c.args[0] for c in self.push.call_args_list], [self.music / "Mix A"] * 2)

    def test_push_link_never_synced(self):
        code, _, err = self.run_cli("push", B)
        self.assertEqual(code, 1)
        self.assertIn("Sync it first", err)
        self.push.assert_not_called()

    def test_push_failure_is_reported(self):
        (self.music / "Nope").mkdir()
        self.push.side_effect = push.PushError('No folder "Nope"')
        code, _, err = self.run_cli("push", "Nope")
        self.assertEqual(code, 1)
        self.assertIn("Nope", err)

    def test_fix_records_and_resyncs(self):
        folder = self.fake_sync(A, self.music).folder
        data = state.load(folder)
        data["songs"][TRACK] = {"file": "01 - x.m4a", "base": "x.m4a", "position": 1, "match": None}
        state.save(folder, data)
        self.sync.reset_mock()
        code, out, _ = self.run_cli("fix", TRACK + "?si=z", "https://www.youtube.com/watch?v=abc123&t=4")
        self.assertEqual(code, 0)
        self.assertEqual(state.load(folder)["fixes"], {TRACK: "https://music.youtube.com/watch?v=abc123"})
        self.assertEqual(self.sync.call_args.args, (A, self.music))
        self.assertIn("Mix A: 2 songs", out)

    def test_fix_takes_short_links(self):
        folder = self.fake_sync(A, self.music).folder
        data = state.load(folder)
        data["songs"][TRACK] = {"file": None, "base": None, "position": 1, "match": None}
        state.save(folder, data)
        self.run_cli("fix", TRACK, "https://youtu.be/xyz_-9")
        self.assertEqual(state.load(folder)["fixes"][TRACK], "https://music.youtube.com/watch?v=xyz_-9")

    def add_track(self, url):
        folder = self.fake_sync(url, self.music).folder
        data = state.load(folder)
        data["songs"][TRACK] = {"file": None, "base": None, "position": 1, "match": None}
        state.save(folder, data)
        return folder

    def test_fix_reaches_every_playlist_with_the_song(self):
        a, b = self.add_track(A), self.add_track(B)
        self.sync.reset_mock()
        code, out, _ = self.run_cli("fix", TRACK, "https://youtu.be/abc")
        self.assertEqual(code, 0)
        for folder in (a, b):
            self.assertEqual(state.load(folder)["fixes"], {TRACK: "https://music.youtube.com/watch?v=abc"})
        self.assertEqual([c.args[0] for c in self.sync.call_args_list], [A, B])
        self.assertIn("Mix B: 2 songs", out)

    def test_fix_with_a_dead_video_says_so_and_saves_nothing(self):
        folder = self.add_track(A)
        self.sync.reset_mock()
        self.describe.side_effect = AudioProviderError("YT-DLP download error - https://music.youtube.com/watch?v=x")
        code, _, err = self.run_cli("fix", TRACK, "https://youtu.be/x")
        self.assertEqual(code, 1)
        self.assertIn("YouTube", err)
        self.assertEqual(state.load(folder)["fixes"], {})
        self.sync.assert_not_called()

    def test_file_error_in_one_playlist_does_not_stop_the_rest(self):
        def locked_file(url, music):
            if url == A:
                raise PermissionError(13, "The process cannot access the file", "01 - x.m4a")
            return self.fake_sync(url, music)
        self.sync.side_effect = locked_file
        code, out, err = self.run_cli(A, B)
        self.assertEqual(code, 1)
        self.assertIn("cannot access", err)
        self.assertIn("Mix B: 2 songs", out)

    def test_tools_download_failing_says_so(self):
        download.ensure_tools.side_effect = ConnectionError("no network")
        code, _, err = self.run_cli(A)
        self.assertEqual(code, 1)
        self.assertIn("no network", err)
        self.sync.assert_not_called()

    def test_fix_refuses_a_non_youtube_link(self):
        code, _, err = self.run_cli("fix", TRACK, "https://vimeo.com/123")
        self.assertEqual(code, 1)
        self.assertIn("YouTube", err)
        self.sync.assert_not_called()

    def test_fix_song_in_no_playlist(self):
        code, _, err = self.run_cli("fix", TRACK, "https://youtu.be/abc")
        self.assertEqual(code, 1)
        self.assertIn("isn't in any playlist", err)

    def test_settings_saves_and_hides_the_secret(self):
        code, _, _ = self.run_cli("settings", "--yoto-client-id", "yid", "--spotify-client-secret", "shh")
        self.assertEqual(code, 0)
        self.assertEqual(self.saved["yoto_client_id"], "yid")
        self.assertEqual(self.saved["spotify_client_secret"], "shh")
        code, out, _ = self.run_cli("settings")
        self.assertIn("yid", out)
        self.assertNotIn("shh", out)
        self.assertIn("(set)", out)
        self.assertIn(str(self.music), out)

    def synced(self, url, report, **extra):
        folder = self.fake_sync(url, self.music).folder
        data = state.load(folder)
        data.update(report=report, synced="2026-11-17 15:10", length=2, **extra)
        state.save(folder, data)
        return folder

    def test_status_lists_every_playlist(self):
        self.synced(A, "Mix A: 2 songs, all fine")
        self.synced(B, "Mix B: 2 songs, 1 fine, 1 to look at\n  02 Missing: x", yoto="card")
        (self.music / "Not a playlist").mkdir()
        code, out, _ = self.run_cli("status")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), [
            'Mix A: 2 songs, all fine | not on Yoto yet: spotify-to-yoto push "Mix A"',
            "Mix B: 2 songs, 1 fine, 1 to look at | on Yoto; known to be up to date after its next push",
        ])
        self.sync.reset_mock()

    def test_status_of_one_playlist_prints_its_report(self):
        folder = self.synced(B, "Mix B: 2 songs, 1 fine, 1 to look at\n  02 Missing: x", yoto="card", pushed=[])
        data = state.load(folder)
        data["songs"]["t"] = {"file": "01 - x.m4a", "position": 1, "match": {"url": "yt"}}
        state.save(folder, data)
        self.sync.reset_mock()
        for arg in ["Mix B", B + "?si=1", str(folder)]:
            code, out, _ = self.run_cli("status", arg)
            self.assertEqual(code, 0)
            self.assertEqual(out.splitlines(), [
                "Mix B: 2 songs, 1 fine, 1 to look at",
                "  02 Missing: x",
                "Report from 2026-11-17 15:10. Run the sync again for a fresh one.",
                'On Yoto, but behind the folder: spotify-to-yoto push "Mix B"',
            ])
        self.sync.assert_not_called()
        spotify.connect.assert_not_called()

    def test_status_before_any_report(self):
        self.fake_sync(A, self.music)
        code, out, _ = self.run_cli("status", "Mix A")
        self.assertEqual(code, 0)
        self.assertIn(f"No report yet. Sync it: spotify-to-yoto {A}", out)

    def test_status_of_unknown_playlist(self):
        code, _, err = self.run_cli("status", "Nope")
        self.assertEqual(code, 1)
        self.assertIn("Nope", err)

    def test_status_with_no_playlists(self):
        code, out, _ = self.run_cli("status")
        self.assertEqual(code, 0)
        self.assertIn("No playlists", out)

    def test_no_links_shows_usage(self):
        code, _, err = self.run_cli()
        self.assertNotEqual(code, 0)
        self.assertIn("usage", err.lower())


if __name__ == "__main__":
    unittest.main()
