"""Pushes one playlist folder to the user's Yoto library, as a playlist to link to a Make Your Own card.

The first push makes a Yoto playlist with the Spotify playlist's cover; later pushes update the same one (the
folder's state remembers which), keeping whatever cover it has by then. Nothing is ever deleted on Yoto.
The Yoto calls follow yoto-library 0.4.0 by Steve Rice (MIT): https://github.com/steverice/yoto-library
"""
import collections
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.request import urlopen

import mutagen
from mutagen.mp4 import MP4

from spotify_to_yoto import state
from spotify_to_yoto.yoto.api import YotoError, get_card, save_card, upload, upload_cover
from spotify_to_yoto.yoto.auth import AuthError

UPLOADS_AT_ONCE = 4
NUMBERED = re.compile(r"^(\d+) - (.+)\.m4a$")
MB = 1_000_000
# Yoto's limits for a Make Your Own playlist (support.yotoplay.com, "How much audio fits on a Make Your Own Card").
MAX_TRACKS = 100
MAX_TRACK_BYTES = 100 * MB
MAX_TRACK_SECONDS = 60 * 60
MAX_TOTAL_BYTES = 500 * MB
MAX_TOTAL_SECONDS = 5 * 60 * 60

Track = collections.namedtuple("Track", "number path title seconds size")


class PushError(Exception):
    pass


def read_tags(path):
    """The song's title tag (or None) and its length in seconds."""
    try:
        song = MP4(path)
    except mutagen.MutagenError as exc:
        raise PushError(f"Couldn't read the tags of {path.name}.") from exc
    title = (song.tags or {}).get("\xa9nam")
    return (title[0] if title else None), float(song.info.length)


def read_album(path):
    """The album spotDL wrote from Spotify, or None: it only sharpens the report, so a bad file isn't an error."""
    try:
        album = (MP4(path).tags or {}).get("\xa9alb")
    except mutagen.MutagenError:
        return None
    return album[0] if album else None


def read_tracks(folder):
    """The folder's numbered songs in order, and the numbers missing between them (songs that didn't download)."""
    tracks = []
    for path in Path(folder).iterdir():
        m = NUMBERED.match(path.name)
        if not m:
            continue
        title, seconds = read_tags(path)
        tracks.append(Track(int(m.group(1)), path, title or m.group(2), seconds, path.stat().st_size))
    tracks.sort(key=lambda t: t.number)
    have = {t.number for t in tracks}
    missing = [n for n in range(1, max(have, default=0) + 1) if n not in have]
    return tracks, missing


def check_limits(tracks):
    problems = []
    if len(tracks) > MAX_TRACKS:
        problems.append(f"{len(tracks)} songs: Yoto takes up to {MAX_TRACKS} tracks.")
    for t in tracks:
        if t.size > MAX_TRACK_BYTES:
            problems.append(f"{t.path.name} is {t.size / MB:.0f} MB: Yoto takes up to 100 MB a track.")
        if t.seconds > MAX_TRACK_SECONDS:
            problems.append(f"{t.path.name} runs {t.seconds / 60:.0f} minutes: Yoto takes up to 60 minutes a track.")
    size = sum(t.size for t in tracks)
    if size > MAX_TOTAL_BYTES:
        problems.append(f"The songs come to {size / MB:.0f} MB: Yoto takes up to 500 MB a playlist.")
    seconds = sum(t.seconds for t in tracks)
    if seconds > MAX_TOTAL_SECONDS:
        problems.append(f"The songs run {seconds / 3600:.1f} hours: Yoto takes up to 5 hours a playlist.")
    return problems


def chapters(tracks, uploads):
    """One chapter a song, numbered by place in the list, so a song missing from the folder leaves no hole."""
    out = []
    for i, (track, up) in enumerate(zip(tracks, uploads), 1):
        audio = {"key": "01", "title": track.title, "overlayLabel": str(i), "type": "audio",
                 "trackUrl": f"yoto:#{up['sha']}", "format": up["format"], "channels": up["channels"],
                 "duration": up["duration"]}
        out.append({"key": f"{i:02d}", "title": track.title, "overlayLabel": str(i), "tracks": [audio]})
    return out


def upload_all(tracks):
    """Uploads every song, a few at a time; any failure stops the push before anything is saved."""
    results = [None] * len(tracks)
    pool = ThreadPoolExecutor(max_workers=UPLOADS_AT_ONCE)
    try:
        jobs = {pool.submit(upload, t.path): i for i, t in enumerate(tracks)}
        for done, job in enumerate(as_completed(jobs), 1):
            i = jobs[job]
            try:
                results[i] = job.result()
            except AuthError:
                raise
            except Exception as exc:  # a Yoto refusal or a dropped connection: name the song either way
                raise PushError(f"{tracks[i].path.name}: {exc} Nothing was saved to Yoto.") from None
            print(f"Uploaded {done}/{len(tracks)}: {tracks[i].title}", flush=True)
    finally:
        pool.shutdown(cancel_futures=True)
    return results


def spotify_cover(url):
    """The Spotify playlist's cover, uploaded to Yoto; None if either step fails, which doesn't stop the push."""
    try:
        with urlopen(url, timeout=30) as r:
            data, kind = r.read(), r.headers.get("Content-Type") or "image/jpeg"
        return upload_cover(data, kind)
    except (OSError, YotoError) as exc:
        print(f"Couldn't add the Spotify cover ({exc}). Add one in the Yoto app.", flush=True)
        return None


def push(folder):
    """Pushes the folder's numbered songs; returns the Yoto playlist's card id."""
    folder = Path(folder)
    if not folder.is_dir():
        there = ", ".join(sorted(p.name for p in folder.parent.iterdir() if p.is_dir())) \
            if folder.parent.is_dir() else "none"
        raise PushError(f'No folder "{folder.name}" in {folder.parent}. Folders there: {there}')
    tracks, missing = read_tracks(folder)
    if missing:
        print(f"Not in the folder (they didn't download): {', '.join(map(str, missing))}. Pushing the rest.")
    if not tracks:
        raise PushError(f'"{folder.name}" has no numbered songs. Sync the playlist first.')
    problems = check_limits(tracks)
    if problems:
        raise PushError("Over Yoto's limits, so nothing was uploaded:\n" + "\n".join(problems))
    uploads = upload_all(tracks)
    data = state.load(folder)
    payload = {"title": state.title(folder, data), "content": {"chapters": chapters(tracks, uploads)}}
    card = get_card(data["yoto"]) if data["yoto"] else None
    if card:
        payload["cardId"] = data["yoto"]
        if card.get("metadata"):
            payload["metadata"] = card["metadata"]  # keeps the cover the playlist has now, set in the app or not
    elif data["cover"]:
        cover = spotify_cover(data["cover"])
        if cover:
            payload["metadata"] = {"cover": {"imageL": cover}}
    data["yoto"] = save_card(payload)
    state.save(folder, data)
    return data["yoto"]
