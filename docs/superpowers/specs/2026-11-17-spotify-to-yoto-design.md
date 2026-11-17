# spotify-to-yoto: design

## Intent

Today `~/Docker/spotdl` turns Allen's Spotify playlists into numbered M4A files from YouTube Music, and pushes a
finished playlist to his Yoto library for a Make Your Own card. It works, but only on his Mac: his drive, his
playlists and his Yoto app are written into it.

This project makes it a public GitHub repo that a stranger can install with one command and run with nothing but a
Spotify playlist link. Allen moves to it too, and retires `~/Docker/spotdl`.

Success: a parent who finds the repo installs it, makes their own Yoto developer app by following the README,
pastes a playlist link, reads a short report of songs that may be wrong, fixes or accepts them, and has the
playlist in their Yoto library with the Spotify cover, ready to link to a card.

## Goals

- One install command on Mac, Linux and Windows, with no Docker.
- Take one Spotify playlist link, several, or a text file with one link per line.
- For each playlist: download the songs from YouTube Music as M4A, number them in Spotify's order, write an
  `.m3u8`, and report songs that may be wrong.
- Stop after the report by default. `--push` goes on to Yoto without stopping.
- Push a playlist to the user's Yoto library: one chapter a song, in order, with the Spotify playlist's cover on the
  first push.
- Run again with the same link to bring the folder (and, with `--push`, the Yoto playlist) up to date.

## Non-goals

- Keeping Yoto in step with Spotify on a schedule. Every push is run by a person.
- Other sources (Apple Music, YouTube playlists) or other players.
- Custom track icons, AI icons or AI covers. Tracks keep Yoto's default icons.
- A graphical app.
- FLAC or other lossless formats. Songs stay as YouTube Music's own AAC in M4A, with no re-encode.

## Anti-goals: a failure even if it works

- Deleting anything on Yoto, or overwriting a cover the user set in the Yoto app.
- Uploading a playlist that's over Yoto's limits.
- A wrong song going to a child's card without the report having flagged it, when one of the checks below could
  have caught it.
- An explicit version going to a card when the Spotify playlist used the clean one, without a flag.
- A shared Yoto developer app: each user's sign-ins go through their own app, never Allen's.
- Printing or committing a token, a client ID from a user's settings, or anything personal of Allen's.

## Constraints

- Python 3.10 or newer (Allen's Mac has 3.10).
- Depends on spotDL as a Python package; pins the spotDL and yt-dlp versions it's tested with.
- YouTube needs a JavaScript runtime for yt-dlp: the `deno` package from PyPI, as today's Dockerfile installs it.
- spotDL downloads ffmpeg for the user (`spotdl --download-ffmpeg`); the tool tells the user to run it, or runs it,
  when ffmpeg is missing.
- Not `--use-cache-file`: it switches spotDL to Spotify's official API under spotDL's shared key, which Spotify
  rate-limits for a day at a time.
- Yoto's limits for a Make Your Own playlist: 100 tracks; 100 MB and 60 minutes a track; 500 MB and 5 hours in all.
- Yoto sign-in: OAuth PKCE with a loopback redirect to `http://127.0.0.1:8787/callback`; scopes
  `user:content:view user:content:manage family:library:view`. The developer dashboard doesn't offer
  `offline_access`, so an expired sign-in means signing in again in the browser.
- Tests never call Spotify, YouTube or Yoto.
- MIT licence. Credit yoto-library (Steve Rice, MIT), whose Yoto calls this follows, and spotDL (MIT).
- The README says it's for personal use, and that the project isn't affiliated with Spotify, YouTube or Yoto.

## Approaches considered

- **A. Today's split:** clone the repo, spotDL in Docker, Python scripts on the host. Closest to what exists, but
  every user needs Docker Desktop, and Docker's folder sharing is fiddly on Windows.
- **B. An installable Python app (chosen):** `pipx install` or `uv tool install` brings spotDL, yt-dlp and Deno
  along. No Docker, same on every system, and spotDL's song data (order, explicit mark, cover, length) comes
  straight from its Python objects. Costs: relying on spotDL's code from inside, which can change between versions;
  users run `pipx upgrade` when YouTube breaks yt-dlp.
- **C. Everything in one Docker image:** only Docker to install, but the Yoto sign-in comes back into a container,
  the user opens the link by hand, and Docker's weight stays.

Allen chose B: strangers expect a one-line install, and it removes Docker.

## What Allen decided

**Who it's for:** strangers who find it on GitHub. Nothing may assume Allen's Mac, drive or Yoto account.

**Input:** Spotify playlist links on the command line, one or several, or a text file of links (one a line; blank
lines and `#` lines skipped). Each playlist gets its own folder named after the playlist on Spotify. No names to
fill in by hand.

**The flow:** by default it downloads every playlist, prints one report per playlist, and ends by printing the
command that pushes to Yoto. `--push` skips the stop and pushes each playlist after its download.

**The report:** one block per playlist. A line about Yoto's limits goes at the top when the playlist is over them.
Then each song with a problem, under the first problem it hits, in this order:

1. **Couldn't download:** the song is one of the user's own files on Spotify, or no longer on Spotify.
2. **Missing:** no verified YouTube Music match (spotDL's `--only-verified-results` behaviour, kept).
3. **Explicit in place of clean:** YouTube Music marks the match explicit and Spotify marks the song not explicit.
4. **Wrong version:** the match's title has a word the Spotify title doesn't: live, remix, karaoke, instrumental,
   cover, sped up, slowed, acoustic.
5. **Wrong artist:** none of the match's artists, nor its channel, matches any of Spotify's artists. Compare
   artists, not titles: titles in other languages differ all the time between the two, artists rarely do.
6. **Same upload as another song:** two Spotify songs matched one YouTube upload.
7. **Cut-off file:** the file on disk is much shorter than YouTube's length for the upload.
8. **Length doesn't match Spotify's:** more than 3 seconds apart, as `check.py` does today.
9. **From a video, not an album track:** the upload has no album on YouTube Music.

Each line gives the YouTube link, so the reader can listen, and how to replace the match (below). A playlist with no
problems gets one line saying so.

**Covers:** the first push sets the Yoto playlist's cover to the Spotify playlist's cover. Later pushes keep whatever
cover the Yoto playlist has, so one set in the Yoto app stays.

**Yoto developer app:** each user makes their own Public Client app; the README walks them through it, as today's
README does. The tool asks for the client ID the first time it needs one and keeps it in the user's settings.

**Moving Allen over:** Allen switches to the public repo and retires `~/Docker/spotdl`. His 41 songs in
`/Volumes/Music/Playlists/Road Trip Mix` must not download again, and the push must
update its existing Yoto playlist, not make a second one.

## Carried over from ~/Docker/spotdl

Everything in today's Yoto push stays, with its tests, adapted to the new layout:

- PKCE sign-in with the in-memory token and lock, so parallel uploads sign in once; idle-connection timeout on the
  callback server; clear errors in place of tracebacks.
- Upload: `GET /media/transcode/audio/uploadUrl`, PUT to the signed URL, poll
  `/media/upload/{id}/transcoded?loudnorm=false`; four at a time; any failure stops the push before anything is
  saved, naming the song.
- `POST /content` with chapters keyed and labelled by list position; `cardId` and existing `metadata` kept on an
  update; a 404 on the stored card makes a new playlist.
- Limits checked before any upload.
- Titles from the files' tags, not file names.
- Numbering by Spotify's list position (`01 - Artist - Title.m4a`), and the `.m3u8` in playlist order.
- The second download pass when YouTube drops downloads (`AudioProviderError`).
- Eight downloads at once, bare `--lyrics` behaviour (no lyrics providers, which all refuse spotDL now).

## My calls (Allen can overrule)

- **Name:** repo, package and command all `spotify-to-yoto`. People search for those two words, and the name is
  free on PyPI. It names the services only to say what it works with; the README says it's not affiliated.
- **Where it lives:** `~/Documents/spotify-to-yoto`, a new git repo, pushed to `lyonsa/spotify-to-yoto` on GitHub
  when it's ready.
- **Install from GitHub first:** `pipx install git+https://github.com/lyonsa/spotify-to-yoto`. Publishing to PyPI
  (which makes it `pipx install spotify-to-yoto`) is a later step, taken only when Allen says.
- **Commands:**
  - `spotify-to-yoto <link or file> ... [--push]`: download, number, report, and push with `--push`.
  - `spotify-to-yoto push <link or folder> ...`: push playlists already downloaded.
  - `spotify-to-yoto fix <spotify song link> <youtube link>`: replace one song's match, download it, and keep the
    choice for later syncs. This replaces spotDL's `"YouTube link|Spotify link"` line, which strangers can't be
    expected to know.
- **Settings:** a small settings file in the user's settings folder (`platformdirs`): music folder and Yoto client
  ID. The music folder defaults to `~/Music/spotify-to-yoto`; `--music DIR` overrides it for one run.
- **What each playlist remembers** sits in a hidden file in its own folder (`.spotify-to-yoto.json`): the Spotify
  link, each song's match and file, the user's fixes, and the Yoto playlist id. Moving or copying the folder keeps
  it all, and nothing per playlist lives anywhere else. Only one run at a time touches a folder (a lock file, as
  `sync.sh` has).
- **Yoto sign-in storage:** the `keyring` package (macOS Keychain, Windows Credential Manager, Linux Secret
  Service, as yoto-library uses), falling back to a file readable only by the user where no keyring exists.
- **`--push` still prints the report** before each push, so a flagged song shows on screen even when nothing stops.
- **Spotify credentials:** spotDL's shared ones by default; the settings take the user's own Spotify app client ID
  and secret as an option, for anyone who hits Spotify's rate limit.
- **Songs removed from Spotify** are deleted from the folder on the next sync, as `sync.sh` does now; the next push
  leaves them out of the Yoto playlist. Nothing is deleted on Yoto.
- **Moving Allen over** is done by hand once, not by code in the public repo: write the state file for Road Trip
  Mix from `sync/1A2b3C4d5E6f7G8h9I0jKl.spotdl` and `sync/yoto.json`, point the settings at
  `/Volumes/Music/Playlists`, run a sync and confirm nothing downloads again, push and
  confirm its existing Yoto playlist is the one updated. Only then, with Allen's go-ahead, delete `~/Docker/spotdl`, the
  `spotdl-deno:local` image and the `yoto-push` Keychain entry, and update the memory note.
- **Tests:** `unittest`-style, as today, run by `pytest` in GitHub Actions on Mac, Linux and Windows.

## Left to the builder

- How to capture the YouTube Music result spotDL chose. spotDL's `Result` carries `explicit`, `artists`, `album`,
  `verified` and `duration`, but its search returns only the URL. Calling the provider's search and selection
  directly, or wrapping it, are both fine. If the explicit mark doesn't come back reliably, fall back to flagging
  every song Spotify marks explicit, and say so in the README.
- How to read a file's real length (spotDL already depends on `mutagen`).
- Whether the Spotify playlist cover comes from spotDL's playlist object or Spotify's page; the upload goes to
  `/media/coverImage/user/me/upload?autoconvert=true`, as yoto-library does.
- Whether the report is also saved in the playlist folder.
- Whether to read Spotify's own playlists (editorial and made-for-you). Spotify has limited what apps may read; if
  they can't be read, the tool says so plainly rather than failing with a traceback, and the README says which
  playlists work.
