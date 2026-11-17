"""The spotify-to-yoto command: sync playlists (and push them with --push), push, fix a match, and settings."""
import argparse
import re
import sys
from pathlib import Path

from spotdl.download.downloader import DownloaderError
from spotdl.providers.audio.base import AudioProviderError

from spotify_to_yoto import download, links, matcher, settings, spotify, state, sync
from spotify_to_yoto.yoto import push
from spotify_to_yoto.yoto.api import YotoError
from spotify_to_yoto.yoto.auth import AuthError

PROG = "spotify-to-yoto"
# One playlist failing for any of these is told and skipped; the rest still run. OSError covers the network
# (requests' errors are OSErrors) and files a player or virus scanner holds open on Windows.
FAILURES = (links.LinkError, spotify.SpotifyFailure, state.LockedError, push.PushError, YotoError, AuthError,
            DownloaderError, AudioProviderError, OSError)
YOUTUBE = re.compile(r"^https?://(?:(?:www|m|music)\.)?(?:youtube\.com/watch\?(?:.*&)?v=|youtu\.be/)([\w-]+)")


def _fail(exc):
    print(exc, file=sys.stderr, flush=True)


def _push(folder):
    with state.locked(folder):
        push.push(folder)
    print(f'"{state.title(folder, state.load(folder))}" is in your Yoto library. Link it to a card in the Yoto app.',
          flush=True)


def _start():
    """Everything a sync needs before its first playlist."""
    download.ensure_tools()
    spotify.connect(settings.load())


def cmd_sync(argv):
    parser = argparse.ArgumentParser(
        prog=PROG, description="Download Spotify playlists from YouTube Music, check the matches, and put them on "
                               "Yoto. Other commands: push, fix, settings (add --help to any).")
    parser.add_argument("links", nargs="+", help="Spotify playlist links, or text files with one link a line")
    parser.add_argument("--push", action="store_true", help="put each playlist on Yoto straight after its download")
    parser.add_argument("--music", help="the folder that holds one folder per playlist, for this run")
    args = parser.parse_args(argv)
    music = settings.music(args.music)
    try:
        urls = links.expand(args.links)
    except links.LinkError as exc:
        _fail(exc)
        return 1
    try:
        _start()
    except FAILURES as exc:
        _fail(exc)
        return 1
    failed, done = False, []
    for url in urls:
        try:
            result = sync.sync(url, music)
            print(result.report + "\n", flush=True)
            if args.push:
                _push(result.folder)
            done.append(result.folder)
        except FAILURES as exc:
            _fail(exc)
            failed = True
    if done and not args.push:
        names = " ".join(f'"{f.name}"' for f in done)
        print(f"To put them on Yoto: {PROG} push {names}")
    return 1 if failed else 0


def _folder(arg, music):
    """A playlist folder from a Spotify link, a folder name, or a folder dragged in (its full path)."""
    if arg.strip().lower().startswith(("http", "spotify:")):
        url = links.playlist_url(arg)
        found = state.find_folder(music, url)
        if not found:
            raise push.PushError(f"No folder in {music} holds {url}. Sync it first: {PROG} {url}")
        return found
    path = Path(arg).expanduser()
    return path if path.is_dir() and len(path.parts) > 1 else music / path.name


def cmd_push(argv):
    parser = argparse.ArgumentParser(prog=f"{PROG} push", description="Put playlists already downloaded on Yoto.")
    parser.add_argument("playlists", nargs="+", help="Spotify playlist links, or folder names or paths")
    parser.add_argument("--music", help="the folder that holds one folder per playlist, for this run")
    args = parser.parse_args(argv)
    music = settings.music(args.music)
    failed = False
    for arg in args.playlists:
        try:
            _push(_folder(arg, music))
        except FAILURES as exc:
            _fail(exc)
            failed = True
    return 1 if failed else 0


def cmd_fix(argv):
    parser = argparse.ArgumentParser(prog=f"{PROG} fix",
                                     description="Use another YouTube upload for one song, now and in later syncs.")
    parser.add_argument("song", help="the song's Spotify link, as the report shows it")
    parser.add_argument("youtube", help="the YouTube or YouTube Music link to use instead")
    parser.add_argument("--music", help="the folder that holds one folder per playlist, for this run")
    args = parser.parse_args(argv)
    music = settings.music(args.music)
    m = YOUTUBE.match(args.youtube.strip())
    if not m:
        _fail(f"{args.youtube} isn't a YouTube link. Use one like https://music.youtube.com/watch?v=…")
        return 1
    try:
        track = links.track_url(args.song)
    except links.LinkError as exc:
        _fail(exc)
        return 1
    folders = state.find_songs(music, track)
    if not folders:
        _fail(f"{track} isn't in any playlist in {music}.")
        return 1
    link = f"https://music.youtube.com/watch?v={m.group(1)}"
    try:
        _start()
        matcher.Matcher().describe(link)  # a dead or private video is refused now, not on every later sync
    except AudioProviderError as exc:
        _fail(f"YouTube couldn't give {link}: {exc}. Try another link.")
        return 1
    except FAILURES as exc:
        _fail(exc)
        return 1
    failed = False
    for folder in folders:  # the song may be in several playlists: fix it in each
        try:
            with state.locked(folder):
                data = state.load(folder)
                data["fixes"][track] = link
                state.save(folder, data)
            print(sync.sync(data["spotify"], music).report + "\n", flush=True)
        except FAILURES as exc:
            _fail(exc)
            failed = True
    return 1 if failed else 0


def cmd_settings(argv):
    parser = argparse.ArgumentParser(prog=f"{PROG} settings", description="Show or change the settings.")
    parser.add_argument("--music", help="the folder that holds one folder per playlist")
    parser.add_argument("--yoto-client-id", help="your Yoto developer app's client ID")
    parser.add_argument("--spotify-client-id", help="your own Spotify app's client ID (optional)")
    parser.add_argument("--spotify-client-secret", help="your own Spotify app's client secret (optional)")
    args = parser.parse_args(argv)
    given = {k: v for k, v in vars(args).items() if v is not None}
    if given:
        if "music" in given:
            given["music"] = str(Path(given["music"]).expanduser().resolve())
        settings.save({**settings.load(), **given})
        print("Saved.")
        return 0
    values = settings.load()
    print(f"Music folder:          {settings.music()}")
    print(f"Yoto client ID:        {values.get('yoto_client_id') or '(not set)'}")
    print(f"Spotify client ID:     {values.get('spotify_client_id') or '(not set: spotDL shared keys)'}")
    print(f"Spotify client secret: {'(set)' if values.get('spotify_client_secret') else '(not set)'}")
    return 0


COMMANDS = {"push": cmd_push, "fix": cmd_fix, "settings": cmd_settings}


def main(argv):
    try:
        if argv and argv[0] in COMMANDS:
            return COMMANDS[argv[0]](argv[1:])
        return cmd_sync(argv)
    except SystemExit as exc:  # argparse: --help, or a usage error
        return exc.code if isinstance(exc.code, int) else 2


def run():
    try:
        code = main(sys.argv[1:])
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        code = 130
    sys.exit(code)
