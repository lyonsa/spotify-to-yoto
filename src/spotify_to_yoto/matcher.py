"""Picks each song's YouTube Music upload with spotDL's own ranking, and keeps what YouTube Music says about it."""
import collections
import threading

from spotdl.providers.audio.ytmusic import YouTubeMusic

Match = collections.namedtuple("Match", "url title artists channel album duration explicit")


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
        if not url:
            return None
        r = provider.seen.get(url)
        if r is None:
            return Match(url, None, [], None, None, None, None)
        return Match(url, r.name, list(r.artists or (r.author,)), None, r.album, r.duration, r.explicit)

    def describe(self, url):
        """What YouTube says about a link the user chose (a fix). YouTube doesn't say if it's explicit."""
        info = self._provider().get_download_metadata(url)
        artists = info.get("artists") or ([info["artist"]] if info.get("artist") else [])
        return Match(url, info.get("track") or info.get("title"), list(artists),
                     info.get("channel") or info.get("uploader"), info.get("album"),
                     float(info["duration"]) if info.get("duration") else None, None)
