import unittest
from unittest import mock

from spotdl.providers.audio.ytmusic import YouTubeMusic
from spotdl.types.result import Result
from spotdl.types.song import Song

from spotify_to_yoto import matcher


def song(**extra):
    values = {"name": "Kataomoi", "artists": ["Aimer"], "artist": "Aimer", "duration": 266, "explicit": False,
              "url": "https://open.spotify.com/track/abc", "song_id": "abc", "album_name": "Daydream"}
    values.update(extra)
    return Song.from_missing_data(**values)


def result(**extra):
    values = {"source": "youtube-music", "url": "https://music.youtube.com/watch?v=v1", "verified": True,
              "name": "Kataomoi", "duration": 266.0, "author": "Aimer", "result_id": "v1", "artists": ("Aimer",),
              "explicit": True, "album": "Daydream"}
    values.update(extra)
    return Result(**values)


class MatcherTest(unittest.TestCase):
    def setUp(self):
        # Keep spotDL's own selection logic, but not its network calls.
        for name, value in [("_create_client", mock.Mock(return_value=None))]:
            patcher = mock.patch.object(YouTubeMusic, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def results(self, found):
        patcher = mock.patch.object(YouTubeMusic, "get_results", side_effect=lambda term, **kw: list(found))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_find_captures_chosen_result(self):
        self.results([result()])
        found = matcher.Matcher().find(song(isrc="JPU901500001"))
        self.assertEqual(found, matcher.Match("https://music.youtube.com/watch?v=v1", "Kataomoi", ["Aimer"], None,
                                              "Daydream", 266.0, True))

    def test_find_without_isrc_uses_spotdls_ranking(self):
        self.results([result()])
        self.assertEqual(matcher.Matcher().find(song()).url, "https://music.youtube.com/watch?v=v1")

    def test_find_returns_none_without_verified_result(self):
        self.results([result(verified=False)])
        self.assertIsNone(matcher.Matcher().find(song()))

    def test_describe_maps_yt_dlp_fields(self):
        info = {"title": "Kataomoi (Official Video)", "track": "Kataomoi", "artists": ["Aimer"], "channel": "Aimer",
                "album": None, "duration": 270}
        with mock.patch.object(YouTubeMusic, "get_download_metadata", return_value=info):
            found = matcher.Matcher().describe("https://music.youtube.com/watch?v=v2")
        self.assertEqual(found, matcher.Match("https://music.youtube.com/watch?v=v2", "Kataomoi", ["Aimer"], "Aimer",
                                              None, 270.0, None))

    def test_describe_without_track_or_artists(self):
        info = {"title": "Fan upload", "uploader": "someone", "duration": 100}
        with mock.patch.object(YouTubeMusic, "get_download_metadata", return_value=info):
            found = matcher.Matcher().describe("https://youtu.be/x")
        self.assertEqual((found.title, found.artists, found.channel), ("Fan upload", [], "someone"))

    def test_match_round_trips_through_dict(self):
        found = matcher.Match("u", "t", ["a"], "c", "al", 1.0, None)
        self.assertEqual(matcher.from_dict(matcher.as_dict(found)), found)
        self.assertIsNone(matcher.from_dict(None))


if __name__ == "__main__":
    unittest.main()
