"""Downloads songs through spotDL, from the YouTube links already chosen for them."""
from spotdl.download.downloader import Downloader
from spotdl.utils.deno import download_deno, is_deno_installed
from spotdl.utils.ffmpeg import download_ffmpeg, is_ffmpeg_installed

from spotify_to_yoto import youtube

_sign_in = None  # yt-dlp's option to read the YouTube sign-in, when YouTube Premium is on


def use_sign_in(config):
    """Downloads from now on read the YouTube sign-in from this browser (a youtube.ask() answer); False or None
    for none."""
    global _sign_in
    youtube.register(config)
    _sign_in = youtube.yt_dlp_args(config)


def premium():
    return _sign_in is not None


def ensure_tools():
    """spotDL needs ffmpeg, and yt-dlp needs Deno for YouTube; spotDL fetches both into its own folder."""
    if not is_ffmpeg_installed():
        print("Downloading ffmpeg (once)…", flush=True)
        download_ffmpeg()
    if not is_deno_installed():
        print("Downloading Deno, which YouTube downloads need (once)…", flush=True)
        download_deno()


class Fetcher:
    def __init__(self, folder):
        self.folder = folder

    def get(self, songs):
        """Spotify link -> downloaded file, for each spotDL Song whose download_url is set. Missing ones failed."""
        if not songs:
            return {}
        options = {
            "audio_providers": ["youtube-music"],
            "format": "m4a",
            "bitrate": "disable",  # keep YouTube Music's own AAC, no re-encode
            "output": str(self.folder / "{artists} - {title}.{output-ext}"),
            "threads": 8,
            "lyrics_providers": [],  # the lyrics sites all refuse spotDL now, and cost seconds a song
            "only_verified_results": True,
            "overwrite": "force",
            "scan_for_songs": False,
            "simple_tui": True,
        }
        if _sign_in:
            options["yt_dlp_args"] = _sign_in  # Premium: YouTube Music's 256 kbps stream
        downloader = Downloader(options)
        got = {}
        todo = list(songs)
        for _ in range(2):  # YouTube drops some downloads; a second try gets most of them
            failed = []
            for song, path in downloader.download_multiple_songs(todo):
                if path:
                    got[song.url] = path
                else:
                    failed.append(song)
            if not failed:
                break
            todo = failed
        return got
