"""Brings one playlist's folder in line with Spotify: downloads what's new or fixed, deletes what's gone, numbers
the songs in Spotify's order, writes the .m3u8, and reports songs that may be wrong.
"""
import collections
import re
from concurrent.futures import ThreadPoolExecutor

from spotify_to_yoto import checks, download, spotify, state
from spotify_to_yoto.matcher import Matcher, as_dict, from_dict
from spotify_to_yoto.yoto import push

Result = collections.namedtuple("Result", "folder report")
SEARCHES_AT_ONCE = 8


def _plan(playlist, data, folder, matcher):
    """Spotify link -> Match for every song to download now; songs whose file is up to date are left out."""
    todo, search = {}, []
    for song in playlist.songs:
        entry = data["songs"].get(song.url) or {}
        have = entry.get("file") and (folder / entry["file"]).exists()
        current = from_dict(entry.get("match"))
        wanted = data["fixes"].get(song.url)
        if wanted:
            if not (have and current and current.url == wanted):
                todo[song.url] = matcher.describe(wanted)
        elif not (have and current):
            search.append(song)
    with ThreadPoolExecutor(max_workers=SEARCHES_AT_ONCE) as pool:
        for song, found in zip(search, pool.map(lambda s: matcher.find(s.song), search)):
            todo[song.url] = found
    return todo


def _download(playlist, data, folder, todo, fetcher):
    by_url = {s.url: s for s in playlist.songs}
    ready = []
    for url, found in todo.items():
        song = by_url[url]
        old = (data["songs"].get(url) or {}).get("file")
        if old:
            (folder / old).unlink(missing_ok=True)
        data["songs"][url] = {"file": None, "base": None, "position": song.position, "match": as_dict(found)}
        if found:
            song.song.download_url = found.url
            ready.append(song.song)
    for url, path in fetcher(folder).get(ready).items():
        data["songs"][url].update(file=path.name, base=path.name)


def _number(playlist, data, folder):
    """Files named "07 - Artist - Title.m4a" by Spotify position, renamed in two steps so swaps never collide."""
    width = max(2, len(str(playlist.length)))
    moves = []
    for song in playlist.songs:
        entry = data["songs"].get(song.url)
        if not entry or not entry.get("file"):
            continue
        entry["position"] = song.position
        base = entry.get("base") or re.sub(r"^\d+ - ", "", entry["file"])  # a file numbered before "base" was kept
        entry["base"] = base
        target = f"{song.position:0{width}d} - {base}"
        if entry["file"] != target:
            moves.append((entry, target))
    for i, (entry, target) in enumerate(moves):
        temp = f".renaming-{i}.m4a"
        (folder / entry["file"]).rename(folder / temp)
        entry["file"] = temp
    for entry, target in moves:
        (folder / entry["file"]).rename(folder / target)
        entry["file"] = target


def _lengths(data, folder):
    lengths = {}
    for url, entry in data["songs"].items():
        if entry.get("file") and (folder / entry["file"]).exists():
            try:
                lengths[url] = push.read_tags(folder / entry["file"])[1]
            except push.PushError:
                pass  # an unreadable file reports as missing
    return lengths


def _write_m3u8(playlist, data, folder, lengths):
    lines = ["#EXTM3U"]
    for song in sorted(playlist.songs, key=lambda s: s.position):
        entry = data["songs"].get(song.url) or {}
        if song.url in lengths:
            lines += [f"#EXTINF:{round(lengths[song.url])},{', '.join(song.artists)} - {song.name}",
                      f"{folder.name}/{entry['file']}"]
    (folder.parent / f"{folder.name}.m3u8").write_text("\n".join(lines) + "\n", encoding="utf-8")


def sync(url, music, fetch=spotify.fetch, matcher=None, fetcher=download.Fetcher):
    playlist = fetch(url)
    folder = state.folder_for(music, playlist.name, url)
    folder.mkdir(parents=True, exist_ok=True)
    with state.locked(folder):
        data = state.load(folder)
        data.update(spotify=url, name=playlist.name, cover=playlist.cover)
        wanted = {s.url for s in playlist.songs}
        for gone in [u for u in data["songs"] if u not in wanted]:
            if data["songs"][gone].get("file"):
                (folder / data["songs"][gone]["file"]).unlink(missing_ok=True)
            del data["songs"][gone]
        todo = _plan(playlist, data, folder, matcher or Matcher())
        _download(playlist, data, folder, todo, fetcher)
        state.save(folder, data)  # what's downloaded is kept, even if the run stops before the end
        _number(playlist, data, folder)
        state.save(folder, data)
        lengths = _lengths(data, folder)
        _write_m3u8(playlist, data, folder, lengths)
        matches = {u: from_dict(e.get("match")) for u, e in data["songs"].items()}
        tracks = [push.Track(e["position"], folder / e["file"], e["file"], lengths[u],
                             (folder / e["file"]).stat().st_size) for u, e in data["songs"].items() if u in lengths]
        report = checks.report(state.title(folder, data), playlist, checks.find(playlist, matches, lengths),
                               push.check_limits(tracks))
    return Result(folder, report)
