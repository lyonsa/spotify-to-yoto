"""Reads a Spotify playlist through spotDL: its name, cover, and songs in order."""
import collections

from spotdl.types.playlist import Playlist as SpotdlPlaylist
from spotdl.utils.config import DEFAULT_CONFIG
from spotdl.utils.spotify import SpotifyClient

SongInfo = collections.namedtuple("SongInfo", "url name artists duration explicit position song")
# length is Spotify's count of the playlist's items, so a position with no song is one spotDL can't read: a file of
# the user's own, or a song gone from Spotify.
Playlist = collections.namedtuple("Playlist", "url name cover length songs")


class SpotifyFailure(Exception):
    pass


def connect(values):
    """spotDL's shared keys by default; the user's own Spotify app, through the official API, when set."""
    own = values.get("spotify_client_id") and values.get("spotify_client_secret")
    # Never use_cache_file: it moves spotDL to the official API under its shared key, which Spotify rate-limits
    # for a day at a time.
    SpotifyClient.init(
        client_id=values["spotify_client_id"] if own else DEFAULT_CONFIG["client_id"],
        client_secret=values["spotify_client_secret"] if own else DEFAULT_CONFIG["client_secret"],
        no_cache=True, use_official_api=bool(own))


def _length(raw, songs):
    raw = raw or {}
    total = (raw.get("content") or {}).get("totalCount") or (raw.get("tracks") or {}).get("total")
    return total or max((s.list_position or 0 for s in songs), default=0)


def fetch(url):
    try:
        raw = SpotifyClient().playlist(url)
        # fetch_songs=False: the playlist's own listing has all we need, without a lookup per song.
        listing = SpotdlPlaylist.from_url(url, fetch_songs=False)
    except Exception as exc:  # spotDL and the Spotify client raise many kinds
        raise SpotifyFailure(f"Couldn't read {url} from Spotify: {exc or type(exc).__name__}. "
                             "The playlist must be public.") from None
    songs = [SongInfo(s.url, s.name, list(s.artists), s.duration, s.explicit, s.list_position, s)
             for s in listing.songs]
    return Playlist(url, listing.name, listing.cover_url or None, _length(raw, listing.songs), songs)
