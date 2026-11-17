"""Brings one playlist's folder in line with Spotify: downloads what's new or fixed, deletes what's gone, numbers
the songs in Spotify's order, writes the .m3u8, and reports songs that may be wrong.
"""
import collections
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from spotify_to_yoto import checks, download, spotify, state
from spotify_to_yoto.matcher import Matcher, as_dict, from_dict
from spotify_to_yoto.yoto import push

Result = collections.namedtuple("Result", "folder report")
SEARCHES_AT_ONCE = 8
TEMPORARY = re.compile(r"^\.(renaming|download)-\d+\.m4a$")


def _sweep(data, folder):
    """Temporary files a stopped run left behind, that the state doesn't point at."""
    kept = {e.get("file") for e in data["songs"].values()}
    for path in folder.iterdir():
        if TEMPORARY.match(path.name) and path.name not in kept:
            path.unlink()


def _find(matcher, song):
    try:
        return matcher.find(song.song)
    except Exception:  # a YouTube Music error on one song: report it missing, and try again next run
        return None


def _plan(playlist, data, folder, matcher, notes):
    """Spotify link -> Match for every song to download now; songs whose file is up to date are left out."""
    todo, search = {}, []
    for song in playlist.songs:
        entry = data["songs"].get(song.url) or {}
        have = entry.get("file") and (folder / entry["file"]).exists()
        current = from_dict(entry.get("match"))
        wanted = data["fixes"].get(song.url)
        if wanted:
            if not (have and current and current.url == wanted):
                try:
                    todo[song.url] = matcher.describe(wanted)
                except Exception as exc:  # a video gone, private or blocked here
                    notes.append(f"  Couldn't use the fix for {', '.join(song.artists)} - {song.name}: {wanted} "
                                 f"({exc}). Fix it again with another link.")
                    if not have:
                        search.append(song)
        elif not (have and current):
            search.append(song)
    with ThreadPoolExecutor(max_workers=SEARCHES_AT_ONCE) as pool:
        for song, found in zip(search, pool.map(lambda s: _find(matcher, s), search)):
            todo[song.url] = found
    return todo


def _batches(songs):
    """Songs split so no two in one batch share a file name: spotDL names files "Artist - Title", and two at one
    path overwrite each other. Case is ignored, as Mac and Windows folders ignore it."""
    batches, seen = [], collections.Counter()
    for song in songs:
        key = (", ".join(song.artists).casefold(), song.name.casefold())
        if seen[key] == len(batches):
            batches.append([])
        batches[seen[key]].append(song)
        seen[key] += 1
    return batches


def _unique(name, data, url):
    taken = {e["base"].casefold() for u, e in data["songs"].items() if u != url and e.get("base")}
    stem, suffix, n = Path(name).stem, Path(name).suffix, 2
    base = name
    while base.casefold() in taken:
        base, n = f"{stem} ({n}){suffix}", n + 1
    return base


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
            ready.append(song)
    for batch in _batches(ready):
        for url, path in fetcher(folder).get([s.song for s in batch]).items():
            # Out of spotDL's way at once, so the next batch's song of the same name can't overwrite it.
            temp = folder / f".download-{by_url[url].position}.m4a"
            path.replace(temp)
            data["songs"][url].update(file=temp.name, base=_unique(path.name, data, url))


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
        (folder / entry["file"]).replace(folder / temp)
        entry["file"] = temp
    state.save(folder, data)  # if the run stops now, the next one finds the files under their temporary names
    _place(folder, moves)


def _place(folder, moves):
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


def _remove_gone(playlist, data, folder, notes):
    wanted = {s.url for s in playlist.songs}
    gone = [u for u in data["songs"] if u not in wanted]
    if gone and len(playlist.songs) < playlist.length:
        # Spotify's listing can leave out a song it can't read; that song may still be in the playlist.
        notes.append(f"  Spotify listed {len(playlist.songs)} of {playlist.length} songs, so nothing was deleted "
                     "this time.")
        return
    for url in gone:
        if data["songs"][url].get("file"):
            (folder / data["songs"][url]["file"]).unlink(missing_ok=True)
        del data["songs"][url]


def sync(url, music, fetch=spotify.fetch, matcher=None, fetcher=download.Fetcher):
    playlist = fetch(url)
    if not playlist.songs:
        raise spotify.SpotifyFailure(f"Spotify listed no songs for {url}, so nothing was changed.")
    folder = state.folder_for(music, playlist.name, url)
    folder.mkdir(parents=True, exist_ok=True)
    notes = []
    with state.locked(folder):
        data = state.load(folder)
        data.update(spotify=url, name=playlist.name, cover=playlist.cover)
        _sweep(data, folder)
        _remove_gone(playlist, data, folder, notes)
        todo = _plan(playlist, data, folder, matcher or Matcher(), notes)
        _download(playlist, data, folder, todo, fetcher)
        state.save(folder, data)  # what's downloaded is kept, even if the run stops before the end
        _number(playlist, data, folder)
        state.save(folder, data)
        lengths = _lengths(data, folder)
        _write_m3u8(playlist, data, folder, lengths)
        matches = {u: from_dict(e.get("match")) for u, e in data["songs"].items()}
        tracks = [push.Track(e["position"], folder / e["file"], e["file"], lengths[u],
                             (folder / e["file"]).stat().st_size) for u, e in data["songs"].items() if u in lengths]
        albums = {u: push.read_album(folder / data["songs"][u]["file"]) for u in lengths}
        fixed = {u for u, link in data["fixes"].items() if matches.get(u) and matches[u].url == link}
        problems = checks.find(playlist, matches, lengths, albums, fixed)
        report = "\n".join([checks.report(state.title(folder, data), playlist, problems, push.check_limits(tracks))]
                           + notes)
        # Kept for "status", which shows it without asking Spotify again.
        data.update(report=report, synced=datetime.now().strftime("%Y-%m-%d %H:%M"), length=playlist.length)
        state.save(folder, data)
    return Result(folder, report)
