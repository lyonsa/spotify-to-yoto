import tempfile
import unittest
from pathlib import Path

from spotify_to_yoto import links

PLAYLIST = "https://open.spotify.com/playlist/1A2b3C4d5E6f7G8h9I0jKl"


class PlaylistUrlTest(unittest.TestCase):
    def test_playlist_url_strips_query(self):
        self.assertEqual(links.playlist_url(PLAYLIST + "?si=abc123"), PLAYLIST)

    def test_playlist_url_takes_uri_and_intl_path(self):
        self.assertEqual(links.playlist_url("spotify:playlist:1A2b3C4d5E6f7G8h9I0jKl"), PLAYLIST)
        self.assertEqual(links.playlist_url("https://open.spotify.com/intl-de/playlist/1A2b3C4d5E6f7G8h9I0jKl/"),
                         PLAYLIST)

    def test_album_link_is_refused(self):
        with self.assertRaises(links.LinkError) as err:
            links.playlist_url("https://open.spotify.com/album/1A2B")
        self.assertIn("isn't a playlist", str(err.exception))

    def test_junk_is_refused(self):
        with self.assertRaises(links.LinkError) as err:
            links.playlist_url("hello")
        self.assertIn("hello", str(err.exception))

    def test_track_url(self):
        self.assertEqual(links.track_url("https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC?si=x"),
                         "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC")
        with self.assertRaises(links.LinkError):
            links.track_url(PLAYLIST)


class ExpandTest(unittest.TestCase):
    def test_expand_reads_a_file_of_links(self):
        other = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        with tempfile.TemporaryDirectory() as tmp:
            listing = Path(tmp) / "playlists.txt"
            listing.write_text(f"# Our lists\n\n{PLAYLIST}?si=1\n{other}\n{PLAYLIST}\n", encoding="utf-8")
            self.assertEqual(links.expand([str(listing)]), [PLAYLIST, other])

    def test_expand_mixes_links_and_files(self):
        other = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        with tempfile.TemporaryDirectory() as tmp:
            listing = Path(tmp) / "more.txt"
            listing.write_text(other + "\n", encoding="utf-8")
            self.assertEqual(links.expand([PLAYLIST, str(listing)]), [PLAYLIST, other])


if __name__ == "__main__":
    unittest.main()
