"""Spotify links as people paste them, made into one plain form."""
import re
from pathlib import Path

LINK = re.compile(r"^https?://open\.spotify\.com/(?:intl-[\w-]+/)?(\w+)/([A-Za-z0-9]+)/?(?:\?.*)?$")
URI = re.compile(r"^spotify:(\w+):([A-Za-z0-9]+)$")


class LinkError(Exception):
    pass


def _parse(link):
    link = link.strip()
    m = LINK.match(link) or URI.match(link)
    if not m:
        raise LinkError(f"{link} isn't a Spotify link.")
    return m.group(1), m.group(2)


def playlist_url(link):
    kind, item = _parse(link)
    if kind != "playlist":
        raise LinkError(f"{link.strip()} isn't a playlist: it's a Spotify {kind}.")
    return f"https://open.spotify.com/playlist/{item}"


def track_url(link):
    kind, item = _parse(link)
    if kind != "track":
        raise LinkError(f"{link.strip()} isn't a song: it's a Spotify {kind}.")
    return f"https://open.spotify.com/track/{item}"


def expand(args):
    """Playlist links from the command line: each one a link, or a text file with one link a line."""
    found = []
    for arg in args:
        path = Path(arg).expanduser()
        if not arg.strip().lower().startswith(("http", "spotify:")) and path.is_file():
            lines = path.read_text(encoding="utf-8").splitlines()
            items = [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
        else:
            items = [arg]
        for item in items:
            url = playlist_url(item)
            if url not in found:
                found.append(url)
    return found
