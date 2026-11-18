"""What each playlist folder remembers, in a hidden file inside it: its Spotify link, each song's file and YouTube
match, the user's fixes, and its Yoto playlist. Keeping it in the folder means a moved or renamed folder keeps it.
"""
import contextlib
import json
import os
import re
from pathlib import Path

STATE = ".spotify-to-yoto.json"
LOCK = ".spotify-to-yoto.lock"
UNSAFE = re.compile(r'[/\\:*?"<>|\x00-\x1f]')


class LockedError(Exception):
    pass


def empty():
    return {"spotify": None, "name": None, "cover": None, "yoto": None, "songs": {}, "fixes": {}}


def load(folder):
    path = Path(folder) / STATE
    if not path.exists():
        return empty()
    return {**empty(), **json.loads(path.read_text(encoding="utf-8"))}


def save(folder, data):
    path = Path(folder) / STATE
    temp = path.with_name(STATE + ".new")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temp, path)  # never half a file, even if the run is stopped mid-write


def safe_name(name):
    """A folder name every system accepts: Windows refuses these characters, and a trailing dot or space."""
    return UNSAFE.sub("_", name).rstrip(". ") or "Playlist"


def title(folder, data):
    """The playlist's name for people: Spotify's when the folder only lost characters a folder can't take, else
    the folder's, since a folder the user renamed keeps their name."""
    name = data.get("name")
    return name if name and safe_name(name) == Path(folder).name else Path(folder).name


def _folders(music):
    music = Path(music)
    if not music.is_dir():
        return []
    return sorted(p for p in music.iterdir() if p.is_dir() and (p / STATE).exists())


def playlists(music):
    """Every playlist folder in the music folder."""
    return _folders(music)


def snapshot(data):
    """What a push sends, to tell later whether Yoto is behind: each file in order and the upload it came from
    (a fix keeps the file's name but changes the upload)."""
    entries = sorted((e for e in data["songs"].values() if e.get("file")), key=lambda e: e["position"])
    return [[e["file"], (e.get("match") or {}).get("url")] for e in entries]


def yoto_status(data):
    """"not pushed", "unknown" (pushed before pushes were recorded), "up to date" or "behind"."""
    if not data.get("yoto"):
        return "not pushed"
    if data.get("pushed") is None:
        return "unknown"
    return "up to date" if data["pushed"] == snapshot(data) else "behind"


def find_folder(music, playlist_url):
    for folder in _folders(music):
        if load(folder)["spotify"] == playlist_url:
            return folder
    return None


def folder_for(music, name, playlist_url):
    """The playlist's folder: where it already is, else one named after it on Spotify."""
    found = find_folder(music, playlist_url)
    if found:
        return found
    folder = Path(music) / safe_name(name)
    if folder.exists() and any(folder.iterdir()):
        # Another playlist with the same name, or the user's own folder: never share it. The whole id, since
        # Spotify's own playlists all start alike.
        folder = folder.with_name(f"{folder.name} ({playlist_url.rstrip('/').rsplit('/', 1)[-1]})")
    return folder


def find_songs(music, track_url):
    """Every playlist folder that has the song."""
    return [folder for folder in _folders(music) if track_url in load(folder)["songs"]]


@contextlib.contextmanager
def locked(folder):
    """One run at a time in a folder: two would fight over the same files."""
    lock = Path(folder) / LOCK
    try:
        lock.mkdir(parents=True)
    except FileExistsError:
        raise LockedError(f"Another run is using {folder}. If none is, delete {lock} and try again.") from None
    try:
        yield
    finally:
        lock.rmdir()
