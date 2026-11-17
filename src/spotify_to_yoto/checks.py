"""The report after a sync: songs that may be the wrong upload, each under the first problem it has."""
import collections
import re

from spotify_to_yoto.matcher import same_artist

Problem = collections.namedtuple("Problem", "kind position song match detail")

KINDS = {
    "unreadable": "Couldn't download",
    "missing": "Missing",
    "explicit": "Explicit in place of clean",
    "version": "Wrong version",
    "artist": "Wrong artist",
    "same": "Same upload as another song",
    "cut": "Cut-off file",
    "length": "Length doesn't match Spotify's",
    "video": "From a video, not an album track",
}
VERSION_WORDS = ("live", "remix", "karaoke", "instrumental", "cover", "sped up", "slowed", "acoustic")
SLACK = 3  # seconds a download may differ from Spotify's length
CUT_OFF = 10  # seconds short of YouTube's own length that mean the download broke off
FIX = 'spotify-to-yoto fix {track} "<YouTube link>"'  # quoted: zsh reads the ? in a YouTube link as a pattern


def _same_artist(song, match):
    return same_artist(song.artists, list(match.artists) + [match.channel])


def _version_word(song, match):
    ours = (song.name or "").casefold()
    theirs = (match.title or "").casefold()
    for word in VERSION_WORDS:
        pattern = r"\b" + r"\s+".join(word.split()) + r"\b"
        if re.search(pattern, theirs) and not re.search(pattern, ours):
            return word
    return None


def _problem(song, match, length, seen):
    """The first problem the song has, as (kind, detail), or None."""
    if match is None:
        return "missing", "no match on YouTube Music"
    if length is None:
        return "missing", "matched, but the download failed"
    if match.explicit is True and song.explicit is False:
        return "explicit", "YouTube Music's is marked explicit"
    if _version_word(song, match):
        return "version", f'YouTube has "{match.title}"'
    if not _same_artist(song, match):
        return "artist", f"YouTube has it by {', '.join(match.artists or [match.channel])}"
    if match.url in seen:
        return "same", f"same upload as song {seen[match.url]}"
    if match.duration and length < match.duration - CUT_OFF:
        return "cut", f"the file runs {length:.0f} s, YouTube's upload {match.duration:.0f} s"
    if abs(length - song.duration) > SLACK:
        return "length", f"{length - song.duration:+.0f} s against Spotify"
    if not match.album:
        return "video", f'YouTube has "{match.title}", not from an album'
    return None


def find(playlist, matches, lengths):
    """matches: Spotify link -> Match or None; lengths: Spotify link -> the file's seconds, for files on disk."""
    problems = []
    have = {s.position for s in playlist.songs}
    for position in range(1, playlist.length + 1):
        if position not in have:
            problems.append(Problem("unreadable", position, None, None, ""))
    seen = {}
    for song in sorted(playlist.songs, key=lambda s: s.position):
        match = matches.get(song.url)
        found = _problem(song, match, lengths.get(song.url), seen)
        if match and match.url not in seen:
            seen[match.url] = song.position
        if found:
            problems.append(Problem(found[0], song.position, song, match, found[1]))
    return sorted(problems, key=lambda p: p.position)


def report(name, playlist, problems, limit_lines):
    if not problems and not limit_lines:
        return f"{name}: {playlist.length} songs, all fine"
    width = max(2, len(str(playlist.length)))
    lines = [f"{name}: {playlist.length} songs, {playlist.length - len(problems)} fine, {len(problems)} to look at"]
    lines += [f"  Over Yoto's limits: {line}" for line in limit_lines]
    for p in problems:
        head = f"  {p.position:0{width}d} {KINDS[p.kind]}:"
        if p.kind == "unreadable":
            lines.append(f"{head} a file of your own on Spotify, or a song no longer on Spotify")
            continue
        lines.append(f"{head} {', '.join(p.song.artists)} - {p.song.name} ({p.detail})")
        pad = " " * (width + 3)
        if p.kind == "missing":
            lines.append(f"{pad}To add it: find it on https://music.youtube.com, then {FIX.format(track=p.song.url)}")
        else:
            lines.append(f"{pad}Listen: {p.match.url}")
            lines.append(f"{pad}To replace it: {FIX.format(track=p.song.url)}")
    return "\n".join(lines)
