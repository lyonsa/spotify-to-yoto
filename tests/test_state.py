import tempfile
import unittest
from pathlib import Path

from spotify_to_yoto import state

A = "https://open.spotify.com/playlist/AAAAAAAAaaaa"
B = "https://open.spotify.com/playlist/BBBBBBBBbbbb"
SONG = "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC"


class StateTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.music = Path(tmp.name)

    def test_missing_state_is_empty(self):
        self.assertEqual(state.load(self.music / "Mix"),
                         {"spotify": None, "name": None, "cover": None, "yoto": None, "songs": {}, "fixes": {}})

    def test_save_load_keeps_non_english_titles(self):
        folder = self.music / "Mix"
        folder.mkdir()
        data = state.load(folder)
        data["songs"][SONG] = {"file": "01 - ヨルシカ - 春泥棒.m4a", "position": 1, "match": None}
        state.save(folder, data)
        self.assertEqual(state.load(folder)["songs"][SONG]["file"], "01 - ヨルシカ - 春泥棒.m4a")
        self.assertIn("春泥棒", (folder / state.STATE).read_text(encoding="utf-8"))

    def test_safe_name_on_unsafe_characters(self):
        self.assertEqual(state.safe_name('AC/DC: Hits? "Live".'), "AC_DC_ Hits_ _Live_")
        self.assertEqual(state.safe_name("..."), "Playlist")
        self.assertEqual(state.safe_name("Road Trip Mix"), "Road Trip Mix")

    def save_playlist(self, name, url):
        folder = self.music / name
        folder.mkdir()
        data = state.load(folder)
        data["spotify"] = url
        state.save(folder, data)
        return folder

    def test_same_name_different_playlist_gets_own_folder(self):
        self.save_playlist("Mix", A)
        self.assertEqual(state.folder_for(self.music, "Mix", B), self.music / "Mix (BBBBBBBBbbbb)")
        self.assertEqual(state.folder_for(self.music, "Mix", A), self.music / "Mix")

    def test_three_playlists_with_one_name_get_three_folders(self):
        # Spotify's own playlists all start 37i9dQZF1D…
        folders = []
        for c in "abc":
            folder = state.folder_for(self.music, "Mix", f"https://open.spotify.com/playlist/37i9dQZF1DX{c}")
            folder.mkdir()
            data = state.load(folder)
            data["spotify"] = f"https://open.spotify.com/playlist/37i9dQZF1DX{c}"
            state.save(folder, data)
            folders.append(folder)
        self.assertEqual(len(set(folders)), 3)

    def test_find_songs_in_every_playlist(self):
        a, b = self.save_playlist("Mix", A), self.save_playlist("Other", B)
        for folder in (a, b):
            data = state.load(folder)
            data["songs"][SONG] = {"file": None, "position": 1, "match": None}
            state.save(folder, data)
        self.assertEqual(state.find_songs(self.music, SONG), [a, b])

    def test_new_playlist_gets_its_spotify_name(self):
        self.assertEqual(state.folder_for(self.music, "Road: Trip", A), self.music / "Road_ Trip")

    def test_folder_found_by_link_after_rename(self):
        folder = self.save_playlist("Road Trip Mix", A)
        self.assertEqual(state.folder_for(self.music, "Road Trip", A), folder)
        self.assertEqual(state.find_folder(self.music, A), folder)
        self.assertIsNone(state.find_folder(self.music, B))

    def test_find_song(self):
        folder = self.save_playlist("Mix", A)
        data = state.load(folder)
        data["songs"][SONG] = {"file": "01 - x.m4a", "position": 1, "match": None}
        state.save(folder, data)
        self.assertEqual(state.find_songs(self.music, SONG), [folder])
        self.assertEqual(state.find_songs(self.music, "https://open.spotify.com/track/zzz"), [])

    def test_music_folder_missing(self):
        self.assertIsNone(state.find_folder(self.music / "nope", A))

    def test_yoto_status(self):
        data = state.load(self.music)
        data["songs"] = {"b": {"file": "02 - B.m4a", "position": 2, "match": {"url": "yt2"}},
                         "a": {"file": "01 - A.m4a", "position": 1, "match": {"url": "yt1"}},
                         "c": {"file": None, "position": 3, "match": None}}
        self.assertEqual(state.snapshot(data), [["01 - A.m4a", "yt1"], ["02 - B.m4a", "yt2"]])
        self.assertEqual(state.yoto_status(data), "not pushed")
        data["yoto"] = "card"
        self.assertEqual(state.yoto_status(data), "unknown")  # pushed before pushes were recorded
        data["pushed"] = state.snapshot(data)
        self.assertEqual(state.yoto_status(data), "up to date")
        data["songs"]["a"]["match"] = {"url": "fixed"}  # a fix keeps the file name but changes the upload
        self.assertEqual(state.yoto_status(data), "behind")

    def test_second_lock_is_refused(self):
        folder = self.music / "Mix"
        folder.mkdir()
        with state.locked(folder):
            with self.assertRaises(state.LockedError) as err:
                with state.locked(folder):
                    pass
        self.assertIn(state.LOCK, str(err.exception))
        with state.locked(folder):  # released after the first run ends
            pass


if __name__ == "__main__":
    unittest.main()
