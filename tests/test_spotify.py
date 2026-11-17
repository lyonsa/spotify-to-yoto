import types
import unittest
from unittest import mock

from spotify_to_yoto import spotify

URL = "https://open.spotify.com/playlist/1A2b3C4d5E6f7G8h9I0jKl"


def spotdl_song(position, url, name="One", explicit=False):
    return types.SimpleNamespace(url=url, name=name, artists=["A", "B"], duration=200, explicit=explicit,
                                 list_position=position)


class FetchTest(unittest.TestCase):
    def setUp(self):
        self.client = mock.Mock()
        self.client.playlist.return_value = {"content": {"totalCount": 3}}
        patcher = mock.patch.object(spotify, "SpotifyClient", return_value=self.client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_fetch_maps_songs(self):
        songs = [spotdl_song(1, "https://open.spotify.com/track/a"),
                 spotdl_song(3, "https://open.spotify.com/track/c", "Three", True)]
        listing = types.SimpleNamespace(name="Road Trip", cover_url="https://mosaic/x", songs=songs)
        with mock.patch.object(spotify.SpotdlPlaylist, "from_url", return_value=listing) as from_url:
            got = spotify.fetch(URL)
        from_url.assert_called_once_with(URL, fetch_songs=False)
        self.assertEqual((got.url, got.name, got.cover, got.length), (URL, "Road Trip", "https://mosaic/x", 3))
        self.assertEqual([s.position for s in got.songs], [1, 3])
        self.assertEqual(got.songs[1], spotify.SongInfo("https://open.spotify.com/track/c", "Three", ["A", "B"], 200,
                                                        True, 3, songs[1]))

    def test_length_from_the_official_api(self):
        self.client.playlist.return_value = {"tracks": {"total": 5}}
        listing = types.SimpleNamespace(name="x", cover_url="", songs=[spotdl_song(1, "u")])
        with mock.patch.object(spotify.SpotdlPlaylist, "from_url", return_value=listing):
            self.assertEqual(spotify.fetch(URL).length, 5)

    def test_length_falls_back_to_last_position(self):
        self.client.playlist.return_value = {}
        listing = types.SimpleNamespace(name="x", cover_url="", songs=[spotdl_song(4, "u")])
        with mock.patch.object(spotify.SpotdlPlaylist, "from_url", return_value=listing):
            got = spotify.fetch(URL)
        self.assertEqual(got.length, 4)
        self.assertIsNone(got.cover)

    def test_fetch_wraps_errors(self):
        with mock.patch.object(spotify.SpotdlPlaylist, "from_url", side_effect=KeyError("content")):
            with self.assertRaises(spotify.SpotifyFailure) as err:
                spotify.fetch(URL)
        self.assertIn(URL, str(err.exception))
        self.assertIn("must be public", str(err.exception))


class ConnectTest(unittest.TestCase):
    def test_connect_uses_spotdls_shared_keys(self):
        with mock.patch.object(spotify.SpotifyClient, "init") as init:
            spotify.connect({})
        kwargs = init.call_args.kwargs
        self.assertEqual(kwargs["client_id"], spotify.DEFAULT_CONFIG["client_id"])
        self.assertFalse(kwargs["use_official_api"])
        self.assertFalse(kwargs.get("use_cache_file", False))
        self.assertTrue(kwargs["no_cache"])

    def test_connect_uses_own_credentials_when_set(self):
        with mock.patch.object(spotify.SpotifyClient, "init") as init:
            spotify.connect({"spotify_client_id": "mine", "spotify_client_secret": "secret"})
        kwargs = init.call_args.kwargs
        self.assertEqual((kwargs["client_id"], kwargs["client_secret"]), ("mine", "secret"))
        self.assertTrue(kwargs["use_official_api"])


if __name__ == "__main__":
    unittest.main()
