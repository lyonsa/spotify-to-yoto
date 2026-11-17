import unittest

from spotify_to_yoto import checks
from spotify_to_yoto.matcher import Match
from spotify_to_yoto.spotify import Playlist, SongInfo

PL = "https://open.spotify.com/playlist/p"


def song(n, name="Kataomoi", artists=("Aimer",), duration=266, explicit=False):
    return SongInfo(f"https://open.spotify.com/track/t{n}", name, list(artists), duration, explicit, n, None)


def match(n, title="Kataomoi", artists=("Aimer",), channel=None, album="Daydream", duration=266.0, explicit=False):
    return Match(f"https://music.youtube.com/watch?v=v{n}", title, list(artists), channel, album, duration, explicit)


class FindTest(unittest.TestCase):
    def find(self, songs, matches=None, lengths=None, length=None):
        playlist = Playlist(PL, "Mix", None, length or len(songs), songs)
        matches = matches if matches is not None else {s.url: match(s.position) for s in songs}
        lengths = lengths if lengths is not None else {s.url: float(s.duration) for s in songs}
        return checks.find(playlist, matches, lengths)

    def kinds(self, *args, **kwargs):
        return [(p.position, p.kind) for p in self.find(*args, **kwargs)]

    def test_all_fine(self):
        self.assertEqual(self.find([song(1), song(2)]), [])

    def test_unreadable_position(self):
        self.assertEqual(self.kinds([song(1), song(3)], length=3), [(2, "unreadable")])

    def test_missing(self):
        s = song(1)
        self.assertEqual(self.kinds([s], matches={s.url: None}, lengths={}), [(1, "missing")])
        problem = self.find([s], matches={s.url: match(1)}, lengths={})[0]  # matched, but the download failed
        self.assertEqual(problem.kind, "missing")
        self.assertIn("download failed", problem.detail)

    def test_explicit_in_place_of_clean(self):
        s = song(1)
        self.assertEqual(self.kinds([s], matches={s.url: match(1, explicit=True)}), [(1, "explicit")])

    def test_clean_matching_clean_is_fine(self):
        s = song(1, explicit=True)
        self.assertEqual(self.kinds([s], matches={s.url: match(1, explicit=True)}), [])
        s = song(1)
        self.assertEqual(self.kinds([s], matches={s.url: match(1, explicit=None)}), [])

    def test_version_word(self):
        for title in ["Kataomoi (Live)", "Kataomoi - Sped Up", "Kataomoi (Karaoke Version)", "Kataomoi - slowed"]:
            s = song(1)
            self.assertEqual(self.kinds([s], matches={s.url: match(1, title=title)}), [(1, "version")], title)

    def test_version_word_in_spotify_title_is_fine(self):
        s = song(1, name="Live Forever", artists=("Oasis",))
        m = match(1, title="Live Forever (Remastered)", artists=("Oasis",))
        self.assertEqual(self.kinds([s], matches={s.url: m}), [])

    def test_version_word_in_spotify_album_is_fine(self):
        # Spotify's "Home to Me" is from the album "Live at Dorothy Major": the live upload is the right one.
        s = song(1, name="Home to Me")
        playlist = Playlist(PL, "Mix", None, 1, [s])
        matches = {s.url: match(1, title="Home to Me (Live)", album="Live at Dorothy Major")}
        self.assertEqual(checks.find(playlist, matches, {s.url: 266.0}, {s.url: "Live at Dorothy Major"}), [])
        self.assertEqual([p.kind for p in checks.find(playlist, matches, {s.url: 266.0}, {s.url: "Studio"})],
                         ["version"])

    def test_version_word_inside_another_word_is_fine(self):
        s = song(1, name="Delivery")
        self.assertEqual(self.kinds([s], matches={s.url: match(1, title="Delivery")}), [])

    def test_wrong_artist(self):
        s = song(1)
        problem = self.find([s], matches={s.url: match(1, artists=("Aimer Fan Channel Covers",),
                                                           channel="covers")})
        self.assertEqual(problem, [])  # the name contains Aimer: close enough
        problem = self.find([s], matches={s.url: match(1, artists=("Someone Else",))})[0]
        self.assertEqual(problem.kind, "artist")
        self.assertIn("Someone Else", problem.detail)

    def test_artist_matches_through_topic_channel(self):
        s = song(1)
        self.assertEqual(self.kinds([s], matches={s.url: match(1, artists=(), channel="Aimer - Topic")}), [])

    def test_artist_matches_across_width_and_case(self):
        s = song(1, artists=("ＹＯＡＳＯＢＩ",))
        self.assertEqual(self.kinds([s], matches={s.url: match(1, artists=("yoasobi",))}), [])

    def test_same_upload(self):
        a, b = song(1), song(2, name="Other")
        m = match(1)
        self.assertEqual(self.kinds([a, b], matches={a.url: m, b.url: m._replace(title="Other")}), [(2, "same")])

    def test_cut_off(self):
        s = song(1)
        self.assertEqual(self.kinds([s], lengths={s.url: 120.0}), [(1, "cut")])

    def test_length_off(self):
        s = song(1)
        m = match(1, duration=280.0)
        self.assertEqual(self.kinds([s], matches={s.url: m}, lengths={s.url: 280.0}), [(1, "length")])
        self.assertEqual(self.kinds([s], lengths={s.url: 268.5}), [])

    def test_from_a_video(self):
        s = song(1)
        self.assertEqual(self.kinds([s], matches={s.url: match(1, album=None)}), [(1, "video")])

    def test_a_song_you_fixed_is_trusted(self):
        # Spotify's "Wildflowers" is itself a Tom Petty cover; the user chose this upload with fix.
        s = song(1, name="Wildflowers - Recorded at Spotify Studios NYC", artists=("Miley Cyrus",), duration=185)
        m = match(1, title="Miley Cyrus - Wildflowers (Tom Petty Cover) [Audio]", artists=(), channel="Miley Cyrus",
                  album=None, duration=190.0, explicit=None)
        playlist = Playlist(PL, "Mix", None, 1, [s])
        self.assertEqual(checks.find(playlist, {s.url: m}, {s.url: 190.0}, fixed={s.url}), [])
        self.assertEqual([p.kind for p in checks.find(playlist, {s.url: m}, {s.url: 190.0})], ["version"])

    def test_a_song_you_fixed_still_reports_a_broken_download(self):
        s = song(1)
        playlist = Playlist(PL, "Mix", None, 1, [s])
        self.assertEqual([p.kind for p in checks.find(playlist, {s.url: match(1)}, {s.url: 100.0}, fixed={s.url})],
                         ["cut"])
        self.assertEqual([p.kind for p in checks.find(playlist, {s.url: match(1)}, {}, fixed={s.url})], ["missing"])

    def test_first_problem_wins(self):
        s = song(1)
        m = match(1, explicit=True, duration=300.0)
        self.assertEqual(self.kinds([s], matches={s.url: m}, lengths={s.url: 300.0}), [(1, "explicit")])


class ReportTest(unittest.TestCase):
    def test_report_shape(self):
        aimer = song(7, artists=("Aimer",))
        idol = song(12, name="Idol", artists=("YOASOBI",))
        songs = [song(n, name=f"S{n}") for n in range(1, 42) if n not in (7, 12, 19)]
        songs += [aimer, idol]
        playlist = Playlist(PL, "Road Trip Mix", None, 41, sorted(songs, key=lambda s: s.position))
        fan = Match("https://music.youtube.com/watch?v=abc", "Kataomoi", ["Aimer Fan Channel"], None, "x", 266.0, False)
        problems = [
            checks.Problem("artist", 7, aimer, fan, "YouTube has it by Aimer Fan Channel"),
            checks.Problem("missing", 12, idol, None, "no match on YouTube Music"),
            checks.Problem("unreadable", 19, None, None, ""),
        ]
        out = checks.report("Road Trip Mix", playlist, problems, ["120 songs: Yoto takes up to 100 tracks."])
        self.assertEqual(out, "\n".join([
            "Road Trip Mix: 41 songs, 38 fine, 3 to look at",
            "  Over Yoto's limits: 120 songs: Yoto takes up to 100 tracks.",
            "  07 Wrong artist: Aimer - Kataomoi (YouTube has it by Aimer Fan Channel)",
            "     Listen: https://music.youtube.com/watch?v=abc",
            f"     To replace it: spotify-to-yoto fix {aimer.url} \"<YouTube link>\"",
            "  12 Missing: YOASOBI - Idol (no match on YouTube Music)",
            f"     To add it: find it on https://music.youtube.com, then spotify-to-yoto fix {idol.url} "
            "\"<YouTube link>\"",
            "  19 Couldn't download: a file of your own on Spotify, or a song no longer on Spotify",
        ]))

    def test_report_all_fine(self):
        playlist = Playlist(PL, "Mix", None, 41, [song(n) for n in range(1, 42)])
        self.assertEqual(checks.report("Road Trip Mix", playlist, [], []),
                         "Road Trip Mix: 41 songs, all fine")

    def test_three_digit_positions(self):
        s = song(7)
        playlist = Playlist(PL, "Mix", None, 120, [s])
        out = checks.report("Mix", playlist, [checks.Problem("video", 7, s, match(7, album=None), "x")], [])
        self.assertIn("  007 From a video, not an album track:", out)


if __name__ == "__main__":
    unittest.main()
