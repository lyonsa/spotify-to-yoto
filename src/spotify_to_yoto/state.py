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


def _folders(music):
    music = Path(music)
    if not music.is_dir():
        return []
    return sorted(p for p in music.iterdir() if p.is_dir() and (p / STATE).exists())


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
        # Another playlist with the same name, or the user's own folder: never share it.
        folder = folder.with_name(f"{folder.name} ({playlist_url.rstrip('/').rsplit('/', 1)[-1][:6]})")
    return folder


def find_song(music, track_url):
    for folder in _folders(music):
        if track_url in load(folder)["songs"]:
            return folder
    return None


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
