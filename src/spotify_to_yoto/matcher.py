"""Picks each song's YouTube Music upload with spotDL's own ranking, and keeps what YouTube Music says about it."""
import collections
import re
import threading
import unicodedata

from spotdl.providers.audio.ytmusic import YouTubeMusic

Match = collections.namedtuple("Match", "url title artists channel album duration explicit")
SLACK = 3  # seconds: the same recording on YouTube Music and Spotify


def plain(text):
    """A name to compare: same width and case, no punctuation, no " - Topic" on YouTube's artist channels."""
    text = unicodedata.normalize("NFKC", text or "").casefold().strip()
    text = re.sub(r"\s+-\s+topic$", "", text)
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


def same_artist(ours, theirs):
    """True when a name on one side equals, or contains, a name on the other ("Joan Jett" in "Joan Jett & the
    Blackhearts"), or when the other side names no one."""
    theirs = [n for n in map(plain, theirs) if n]
    if not theirs:
        return True
    ours = [n for n in map(plain, ours) if n]
    return any(a == b or a in b or b in a for a in ours for b in theirs)


def as_dict(match):
    return match._asdict() if match else None


def from_dict(data):
    return Match(**data) if data else None


class _Recording(YouTubeMusic):
    """spotDL's search returns only the chosen link; this keeps every result it saw, to look the choice up."""

    def get_results(self, search_term, **kwargs):
        results = super().get_results(search_term, **kwargs)
        for r in results:
            self.seen[r.url] = r
        return results


class Matcher:
    def __init__(self):
        self._local = threading.local()  # searches run eight at a time; each thread keeps its own provider

    def _provider(self):
        if not hasattr(self._local, "provider"):
            self._local.provider = _Recording(output_format="m4a")
        self._local.provider.seen = {}
        return self._local.provider

    def find(self, song):
        """The best verified YouTube Music song for a spotDL Song, or None."""
        provider = self._provider()
        url = provider.search(song, only_verified=True)
        if url:
            r = provider.seen.get(url)
            if r is None:
                return Match(url, None, [], None, None, None, None)
        else:
            # Without an ISRC (spotDL's shared keys give none), spotDL's ranking turns down the right song when
            # YouTube Music names the artist a little differently. Take a verified song with the same title and
            # length, and an artist that matches.
            r = next((r for r in provider.seen.values() if r.verified and plain(r.name) == plain(song.name)
                      and r.duration and abs(r.duration - song.duration) <= SLACK
                      and same_artist(song.artists, r.artists or (r.author,))), None)
            if r is None:
                return None
        return Match(r.url, r.name, list(r.artists or (r.author,)), None, r.album, r.duration, r.explicit)

    def describe(self, url):
        """What YouTube says about a link the user chose (a fix). YouTube doesn't say if it's explicit."""
        info = self._provider().get_download_metadata(url)
        artists = info.get("artists") or ([info["artist"]] if info.get("artist") else [])
        return Match(url, info.get("track") or info.get("title"), list(artists),
                     info.get("channel") or info.get("uploader"), info.get("album"),
                     float(info["duration"]) if info.get("duration") else None, None)
