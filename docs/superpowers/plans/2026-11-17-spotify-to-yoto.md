# spotify-to-yoto Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An installable command, `spotify-to-yoto`, that turns Spotify playlist links into numbered M4A folders from
YouTube Music, reports songs that may be wrong, and pushes a playlist to the user's Yoto library.

**Architecture:** A `src/` Python package that calls spotDL as a library: spotDL reads Spotify and downloads, while
this package picks and records each song's YouTube match, numbers files, runs the nine checks and talks to Yoto.
Everything a playlist remembers lives in a hidden JSON file in its own folder. The Yoto half is carried over from
`~/Docker/spotdl` (`yoto.py`, `yoto_auth.py`, `yoto_api.py` and their tests), with mutagen in place of Docker and
keyring in place of the `security` command.

**Tech Stack:** Python 3.11+, spotDL 4.6.0 (brings yt-dlp, ytmusicapi, mutagen, platformdirs), keyring, hatchling,
unittest-style tests run by pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-17-spotify-to-yoto-design.md`

## Global Constraints

- `requires-python = ">=3.11,<3.16"`. **Ruling:** the spec says 3.10, but spotDL 4.6.0 requires `>=3.11,<3.16`.
  The README leads with `uv tool install`, which fetches a matching Python, so Allen's 3.10 doesn't matter.
- Dependencies: `spotdl==4.6.0`, `keyring>=25`, `platformdirs>=4.3`, `mutagen>=1.47`. **Ruling:** yt-dlp is left
  to spotDL's own range (`>=2026.10.21,<2027`), not pinned, so `uv tool upgrade spotify-to-yoto` can pick up a
  yt-dlp fix when YouTube breaks it; the spec's "pins yt-dlp" would block that.
- Never pass spotDL `use_cache_file=True`.
- Yoto limits: 100 tracks; 100 MB and 60 minutes a track; 500 MB and 5 hours in all (`MB = 1_000_000`).
- Yoto sign-in: PKCE, redirect `http://127.0.0.1:8787/callback`, scopes
  `user:content:view user:content:manage family:library:view`, no `offline_access`.
- Nothing ever sends DELETE to Yoto. Nothing prints a token, an Authorization header or a client secret.
- Tests never touch the network, Spotify, YouTube, Yoto, the real keyring or the user's settings folder.
- Plain words in every message the user sees; short sentences; say what to do next.
- Lines up to 120 characters; f-strings; no type hints; short docstrings where the name doesn't say enough.
- Commit subjects: one plain sentence (optionally led by `Spec:`, `Plan:` or a module name), no `feat:`/`fix:`;
  end each message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Test command for every task: `uv run --extra test pytest -q`

## Review Focus

1. A playlist name with characters a file system refuses (`/ \ : * ? " < > |`, a trailing dot or space) still
   gets a folder, and the Yoto playlist keeps the name as Spotify has it. Test in Task 2.
2. A reordered playlist where songs swap places (01 ↔ 02) renumbers without overwriting either file. Test in Task 7.
3. Two different playlists with the same Spotify name get two folders, never one shared. Test in Task 2.
4. A first push with no Yoto client ID, run without a terminal to type into, stops with the README pointer
   instead of waiting forever for input. Test in Task 3.
5. A Windows Credential Manager that refuses the token (too long) falls back to the private file instead of
   failing the push. Test in Task 3.

---

### Task 1: Package, settings and links

**Files:**
- Create: `pyproject.toml`, `LICENSE`, `.gitignore`, `.github/workflows/tests.yml`
- Create: `src/spotify_to_yoto/__init__.py`, `src/spotify_to_yoto/__main__.py`
- Create: `src/spotify_to_yoto/settings.py`, `src/spotify_to_yoto/links.py`
- Test: `tests/__init__.py`, `tests/test_settings.py`, `tests/test_links.py`

**Interfaces:**
- Produces:
  - `settings.config_dir() -> Path`: `platformdirs.user_config_path("spotify-to-yoto")`; tests patch it.
  - `settings.load() -> dict` (keys `music`, `yoto_client_id`, `spotify_client_id`, `spotify_client_secret`; any
    may be missing); `settings.save(values: dict)` writes `settings.json` (mode 0600 where the OS supports it).
  - `settings.music(override=None) -> Path`: `override`, else `load()["music"]`, else `~/Music/spotify-to-yoto`.
  - `links.LinkError(Exception)`.
  - `links.playlist_url(link) -> str`: canonical `https://open.spotify.com/playlist/<id>`; accepts `?si=…`,
    `/intl-xx/` paths and `spotify:playlist:<id>`; raises `LinkError` naming the link otherwise (an album or
    track link says it isn't a playlist).
  - `links.track_url(link) -> str`: the same for `https://open.spotify.com/track/<id>`.
  - `links.expand(args) -> list[str]`: each arg is a playlist link, or a path to a text file of links (blank and
    `#` lines skipped); returns canonical playlist URLs, duplicates dropped, order kept.

- [ ] **Step 1: Write the failing tests**

```python
def test_playlist_url_strips_query(self):
    self.assertEqual(links.playlist_url("https://open.spotify.com/playlist/1A2b3C4d5E6f7G8h9I0jKl?si=abc"),
                     "https://open.spotify.com/playlist/1A2b3C4d5E6f7G8h9I0jKl")
def test_playlist_url_takes_uri_and_intl_path(self): ...   # spotify:playlist:ID and /intl-de/playlist/ID
def test_album_link_is_refused(self):
    with self.assertRaises(links.LinkError) as err:
        links.playlist_url("https://open.spotify.com/album/1A2B")
    self.assertIn("isn't a playlist", str(err.exception))
def test_expand_reads_a_file_of_links(self): ...   # tmp file with a comment, a blank line, two links, one repeated
def test_music_defaults_beside_home(self): ...      # empty settings → Path.home() / "Music" / "spotify-to-yoto"
def test_settings_round_trip(self): ...             # save then load in a patched config_dir
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --extra test pytest -q tests/test_links.py tests/test_settings.py`
Expected: FAIL (ModuleNotFoundError: spotify_to_yoto)

- [ ] **Step 3: Write `pyproject.toml` and the two modules**

`pyproject.toml`: hatchling build; `name = "spotify-to-yoto"`; version `0.1.0`; the Global Constraints'
`requires-python` and dependencies; `[project.optional-dependencies] test = ["pytest>=8"]`;
`[project.scripts] spotify-to-yoto = "spotify_to_yoto.cli:run"`; MIT licence. `__main__.py` calls `cli.run()`.
`LICENSE`: MIT, "Copyright (c) 2026 Allen Lyons". `.gitignore`: `__pycache__/`, `*.egg-info/`, `.venv/`,
`dist/`, `.superpowers/`. `tests.yml`: on push and pull_request; matrix `os: [ubuntu-latest, macos-latest,
windows-latest]`, `python: ["3.11", "3.13"]`; `astral-sh/setup-uv`, then `uv run --python ${{ matrix.python }}
--extra test pytest -q`.

- [ ] **Step 4: Run the tests**

Run: `uv run --extra test pytest -q`
Expected: all pass

- [ ] **Step 5: Commit**

`git add -A && git commit -m "Package skeleton, settings and Spotify link parsing"`

---

### Task 2: What each playlist folder remembers

**Files:**
- Create: `src/spotify_to_yoto/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: `links.playlist_url`.
- Produces:
  - `STATE = ".spotify-to-yoto.json"`, `LOCK = ".spotify-to-yoto.lock"`.
  - `state.load(folder) -> dict`: the saved state, or `{"spotify": None, "name": None, "cover": None, "yoto": None,
    "songs": {}, "fixes": {}}`. `songs` maps a canonical Spotify track URL to
    `{"file": "<name on disk>", "position": int, "match": {Match fields, Task 5}}`; `fixes` maps a track URL to a
    YouTube URL.
  - `state.save(folder, data)`: write to a temp file then `os.replace`, UTF-8, `ensure_ascii=False`.
  - `state.safe_name(name) -> str`: replaces `/ \ : * ? " < > |` and control characters with `_`, strips trailing
    dots and spaces, `"Playlist"` if nothing is left.
  - `state.find_folder(music, playlist_url) -> Path | None`: the subfolder whose state has that `spotify` URL.
  - `state.folder_for(music, name, playlist_url) -> Path`: `find_folder`, else `music / safe_name(name)`; if that
    folder exists and holds anything other than this playlist's state, `music / f"{safe_name(name)} ({id[:6]})"`.
  - `state.find_song(music, track_url) -> Path | None`: the folder whose state lists that track.
  - `state.LockedError(Exception)`; `state.locked(folder)`: context manager that makes `LOCK` as a directory and
    removes it on exit; if it exists, raises `LockedError` saying another run is using the folder and to delete
    `<path>` if none is.

- [ ] **Step 1: Write the failing tests**

```python
def test_missing_state_is_empty(self): ...            # load(tmp) == the empty shape above
def test_save_load_keeps_non_english_titles(self): ... # a "file" of "01 - ヨルシカ - 春泥棒.m4a" round-trips
def test_safe_name_on_unsafe_characters(self):
    self.assertEqual(state.safe_name('AC/DC: Hits? "Live".'), "AC_DC_ Hits_ _Live_")
def test_same_name_different_playlist_gets_own_folder(self): ...  # folder "Mix" holds playlist A's state;
    # folder_for(music, "Mix", B) == music / "Mix (<B id[:6]>)"
def test_folder_found_by_link_after_rename(self): ...  # state saved in "Road Trip Mix"; folder_for with
    # Spotify name "Road Trip" returns the renamed folder
def test_second_lock_is_refused(self): ...             # nested locked() raises LockedError naming the lock path
```

- [ ] **Step 2: Run them to see them fail** — `uv run --extra test pytest -q tests/test_state.py`; Expected: FAIL
  (ImportError).
- [ ] **Step 3: Implement `state.py` as the Interfaces say.**
- [ ] **Step 4: Run the tests** — `uv run --extra test pytest -q`; Expected: all pass.
- [ ] **Step 5: Commit** — `"Each playlist folder keeps its Spotify link, songs, fixes and Yoto id in a hidden file"`

---

### Task 3: Yoto sign-in and calls, carried over

**Files:**
- Create: `src/spotify_to_yoto/yoto/__init__.py`, `yoto/auth.py`, `yoto/api.py`
- Test: `tests/test_yoto_auth.py`, `tests/test_yoto_api.py`
- Copy from: `~/Docker/spotdl/yoto_auth.py`, `yoto_api.py`, `tests/test_yoto_auth.py`, `tests/test_yoto_api.py`

**Interfaces:**
- Consumes: `settings.load`, `settings.save`, `settings.config_dir`.
- Produces (unchanged from `~/Docker/spotdl` unless noted):
  - `auth.AuthError`, `auth.access_token() -> str`, `auth.SCOPES`, `auth.REDIRECT`.
  - `auth.client_id() -> str` **changed**: `settings.load()["yoto_client_id"]`; if missing and `sys.stdin.isatty()`,
    prints the four set-up steps (Public Client, callback `http://127.0.0.1:8787/callback`, the two scopes to tick)
    and asks for it with `input()`, then saves it; if missing and no terminal, raises `AuthError` pointing to the
    README's "Set up Yoto" section.
  - `auth.load_tokens() -> dict | None` / `auth.save_tokens(tokens)` **changed**: `keyring` service
    `"spotify-to-yoto"`, user `"yoto"`. On any `keyring.errors.KeyringError` (including `NoKeyringError` and a
    Windows "blob too large"), use `config_dir() / "yoto-sign-in.json"`, mode 0600 where supported.
  - `api.YotoError`, `api.call`, `api.get_card`, `api.save_card`, `api.upload` as before.
  - `api.call(method, path, params=None, body=None, raw=None, content_type=None)` **changed**: `raw` bytes are sent
    as they are with `content_type`.
  - `api.upload_cover(data: bytes, content_type: str) -> str`: `POST /media/coverImage/user/me/upload` with
    `autoconvert=true`; returns `coverImage.mediaUrl` (or `url`, or top-level `coverUrl`, as yoto-library looks);
    `YotoError` if none.

- [ ] **Step 1: Copy the two test files over, fix their imports (`from spotify_to_yoto.yoto import auth, api`),
  and replace the Keychain tests with:**

```python
def test_tokens_round_trip_through_keyring(self): ...   # patch keyring.get_password/set_password; assert service
    # "spotify-to-yoto", user "yoto", JSON round trip
def test_keyring_refusal_falls_back_to_file(self): ...  # set_password raises keyring.errors.PasswordSetError;
    # tokens land in <patched config_dir>/yoto-sign-in.json and load_tokens() reads them back
def test_no_keyring_reads_file(self): ...                # get_password raises NoKeyringError → file is read
def test_client_id_without_terminal_points_to_readme(self): ...  # empty settings, isatty False → AuthError
    # containing "README"; input() never called
def test_client_id_asked_and_saved(self): ...           # isatty True, input returns " abc " → "abc", saved
def test_upload_cover_returns_media_url(self): ...       # FakeYoto answers {"coverImage": {"mediaUrl": "https://x"}};
    # the request is POST, Content-Type image/jpeg, query autoconvert=true, body the bytes
```

- [ ] **Step 2: Run them to see the new ones fail** — `uv run --extra test pytest -q tests/test_yoto_auth.py
  tests/test_yoto_api.py`; Expected: FAIL (ImportError).
- [ ] **Step 3: Copy the two modules in and make the changes the Interfaces mark.** Keep the docstring credit to
  yoto-library 0.4.0 (Steve Rice, MIT), the lock and in-memory token, `_Callback.timeout = 5` and `log_message`
  silenced.
- [ ] **Step 4: Run the tests** — `uv run --extra test pytest -q`; Expected: all pass, the carried-over ones
  included.
- [ ] **Step 5: Commit** — `"Yoto sign-in and calls, from the spotdl folder, with keyring and a cover upload"`

---

### Task 4: Pushing a folder to Yoto

**Files:**
- Create: `src/spotify_to_yoto/yoto/push.py`
- Test: `tests/test_push.py`
- Copy from: `~/Docker/spotdl/yoto.py`, `tests/test_yoto.py`

**Interfaces:**
- Consumes: `state.load/save`, `api.get_card/save_card/upload/upload_cover/YotoError`, `auth.AuthError`.
- Produces:
  - `push.PushError`, `push.Track`, `push.check_limits(tracks) -> list[str]`, `push.chapters(tracks, uploads)`,
    `push.upload_all(tracks)` as before.
  - `push.read_tags(path) -> (title | None, seconds)`: `mutagen.mp4.MP4`; title from `©nam`; length from
    `info.length`. Raises `PushError(f"Couldn't read the tags of {path.name}.")` on `mutagen.MutagenError`.
  - `push.read_tracks(folder) -> (tracks, missing)`: as before, with `read_tags` in place of Docker's probe.
  - `push.push(folder) -> str`: card id. Card id from `state["yoto"]` (not `yoto.json`); title is `state["name"]`
    or the folder name; saves the card id back into the folder's state. When a new playlist is made (no id, or
    `get_card` gives None), and `state["cover"]` is set, fetch it with `urlopen` (30 s timeout), `upload_cover`,
    and send `metadata: {"cover": {"imageL": url}}`. A cover that fails to fetch or upload prints one line and
    the push goes on without it. An existing playlist keeps its own `metadata`, cover included.

- [ ] **Step 1: Copy the tests over; drop the Docker probe tests; add:**

```python
def test_read_tags_uses_mutagen(self): ...         # patch push.MP4 → tags {"©nam": ["春泥棒"]}, info.length 245.3
def test_unreadable_file_stops_the_push(self): ... # MP4 raises MutagenError → PushError naming the file
def test_first_push_sets_spotify_cover(self): ...  # state cover "https://i.scdn.co/image/x"; fake urlopen gives
    # b"jpg"; upload_cover returns "https://yoto/cover"; saved payload metadata == {"cover": {"imageL": ...}}
def test_rerun_keeps_cover_from_app(self): ...      # get_card gives metadata with another cover; upload_cover never
    # called; payload metadata is the card's
def test_cover_failure_does_not_stop_push(self): ... # urlopen raises URLError; card still saved, no metadata
def test_card_id_kept_in_folder_state(self): ...    # after push, state.load(folder)["yoto"] == the new id
```

- [ ] **Step 2: Run them to see them fail** — `uv run --extra test pytest -q tests/test_push.py`; Expected: FAIL.
- [ ] **Step 3: Port `yoto.py` into `push.py` as the Interfaces say.** `MUSIC`, `STORE` and `main()` go; the
  command line comes in Task 8.
- [ ] **Step 4: Run the tests** — `uv run --extra test pytest -q`; Expected: all pass.
- [ ] **Step 5: Commit** — `"Push reads tags with mutagen, keeps the card id in the folder, and sets the Spotify
  cover on a new playlist"`

---

### Task 5: Spotify, matching and downloading through spotDL

**Files:**
- Create: `src/spotify_to_yoto/spotify.py`, `matcher.py`, `download.py`
- Test: `tests/test_spotify.py`, `tests/test_matcher.py`, `tests/test_download.py`

**Interfaces:**
- Consumes: `settings.load`, `links.track_url`.
- Produces:
  - `spotify.SongInfo = namedtuple("SongInfo", "url name artists duration explicit position song")`: `url` the
    canonical track URL, `song` spotDL's `Song` (tests pass None).
  - `spotify.Playlist = namedtuple("Playlist", "url name cover length songs")`: `length` is Spotify's track count,
    so positions missing from `songs` are songs spotDL couldn't read (your own files, gone from Spotify).
  - `spotify.SpotifyFailure(Exception)`; `spotify.connect(values: dict)`: `SpotifyClient.init` with spotDL's
    shared credentials, or the user's `spotify_client_id`/`spotify_client_secret` with `use_official_api=True`;
    `no_cache=True`; never `use_cache_file`.
  - `spotify.fetch(url) -> Playlist`: spotDL's `Playlist.from_url`; any exception becomes `SpotifyFailure`
    ("Couldn't read <url> from Spotify: <reason>. The playlist must be public.").
  - `matcher.Match = namedtuple("Match", "url title artists channel album duration explicit")`;
    `matcher.as_dict(match)` / `matcher.from_dict(d)` for the state file.
  - `matcher.Matcher()`; `.find(song) -> Match | None`: spotDL's `YouTubeMusic.search(song, only_verified=True)`,
    with the chosen `Result` captured by a subclass whose `get_results` records every result by URL (one provider
    per thread, `threading.local`). `.describe(url) -> Match` for a fix: `get_download_metadata(url)` mapped to a
    Match, `explicit=None`.
  - `download.ensure_tools()`: if `shutil.which("ffmpeg")` and spotDL's `get_ffmpeg_path()` are both None, print
    "Downloading ffmpeg (once)…" and call spotDL's `download_ffmpeg()`; the same for Deno with
    `is_deno_installed()` / `download_deno()`.
  - `download.Fetcher(folder)`; `.get(songs) -> dict[track_url, Path]`: each spotDL `Song` already has
    `download_url` set; spotDL `Downloader` settings `format="m4a"`, `bitrate="disable"`,
    `output=str(folder / "{artists} - {title}.{output-ext}")`, `threads=8`, `lyrics_providers=[]`,
    `only_verified_results=True`, `overwrite="force"`, `scan_for_songs=False`, `simple_tui=True`. Songs that come
    back with no path get one more try (the second pass for YouTube's dropped downloads); still none → left out.

- [ ] **Step 1: Write the failing tests** (spotDL's network calls are patched; its own selection logic runs)

```python
def test_find_captures_chosen_result(self): ...  # patch YouTubeMusic.get_results to return one verified Result
    # (isrc search) with explicit=True, album="Album", artists=("A",); song with isrc → Match.explicit is True,
    # Match.album == "Album", Match.url == the result's url
def test_find_returns_none_without_verified_result(self): ...
def test_describe_maps_yt_dlp_fields(self): ...  # get_download_metadata → {"title","artists"|"artist","channel",
    # "album","duration"}; explicit None
def test_match_round_trips_through_dict(self): ...
def test_fetch_wraps_errors(self): ...           # Playlist.from_url raises → SpotifyFailure with "must be public"
def test_fetch_maps_songs(self): ...             # fake spotDL playlist with 2 songs → SongInfo positions 1, 2;
    # Playlist.length from list_length; cover from cover_url
def test_connect_uses_own_credentials_when_set(self): ...  # use_official_api=True and the user's id
def test_fetcher_retries_dropped_downloads_once(self): ... # fake Downloader: first call one path None, second ok
def test_fetcher_settings(self): ...             # the Downloader got the settings listed above
```

- [ ] **Step 2: Run them to see them fail** — `uv run --extra test pytest -q tests/test_spotify.py
  tests/test_matcher.py tests/test_download.py`; Expected: FAIL.
- [ ] **Step 3: Implement the three modules as the Interfaces say.** Read spotDL 4.6.0's `providers/audio/base.py`,
  `ytmusic.py`, `types/playlist.py`, `utils/ffmpeg.py`, `utils/deno.py` in the installed package first; if
  `list_length` doesn't count local files, ledger a ruling and take the count from the playlist's metadata.
  Confirm spotDL's YouTube provider passes `get_local_deno_yt_dlp_options()` to yt-dlp; if it doesn't, pass it in
  the Downloader's `yt_dlp_args`.
- [ ] **Step 4: Run the tests** — `uv run --extra test pytest -q`; Expected: all pass.
- [ ] **Step 5: Commit** — `"Read Spotify, pick YouTube Music matches and download through spotDL as a library"`

---

### Task 6: The nine checks and the report

**Files:**
- Create: `src/spotify_to_yoto/checks.py`
- Test: `tests/test_checks.py`

**Interfaces:**
- Consumes: `spotify.Playlist/SongInfo`, `matcher.Match`, `push.check_limits`, `push.Track`.
- Produces:
  - `checks.Problem = namedtuple("Problem", "kind position song match detail")`; `song` is a SongInfo or None
    (for kind `unreadable`).
  - `checks.KINDS`, in this order, each with its label: `unreadable` "Couldn't download",
    `missing` "Missing", `explicit` "Explicit in place of clean", `version` "Wrong version",
    `artist` "Wrong artist", `same` "Same upload as another song", `cut` "Cut-off file",
    `length` "Length doesn't match Spotify's", `video` "From a video, not an album track".
  - `checks.VERSION_WORDS = ("live", "remix", "karaoke", "instrumental", "cover", "sped up", "slowed", "acoustic")`;
    `checks.SLACK = 3`; `checks.CUT_OFF = 10` (seconds).
  - `checks.find(playlist, matches: dict[url, Match | None], lengths: dict[url, float]) -> list[Problem]`: one
    problem per song at most, the first kind it hits, sorted by position. `unreadable`: each position in
    `1..playlist.length` with no song. `missing`: no match or no length (no file). `explicit`:
    `match.explicit is True and song.explicit is False`. `version`: a word from `VERSION_WORDS` (word-bounded,
    case-folded) in `match.title` but not in `song.name`. `artist`: after NFKC, case-folding, dropping a trailing
    " - Topic" and punctuation, no name in `match.artists + (match.channel,)` equals or contains, or is contained
    in, any of `song.artists`. `same`: another earlier song has the same `match.url`. `cut`:
    `length < match.duration - CUT_OFF`. `length`: `abs(length - song.duration) > SLACK`. `video`:
    `match.album` is falsy.
  - `checks.report(name, playlist, problems, limit_lines) -> str`.

The report's exact shape (width of the position follows the file numbering):

```
Road Trip Mix: 41 songs, 38 fine, 3 to look at
  Over Yoto's limits: 120 songs: Yoto takes up to 100 tracks.
  07 Wrong artist: Aimer - Kataomoi (YouTube has it by Aimer Fan Channel)
     Listen: https://music.youtube.com/watch?v=abc
     To replace it: spotify-to-yoto fix https://open.spotify.com/track/xyz <YouTube link>
  12 Missing: YOASOBI - Idol (no match on YouTube Music)
     To add it: find it on https://music.youtube.com, then spotify-to-yoto fix https://open.spotify.com/track/… <YouTube link>
  19 Couldn't download: a file of your own on Spotify, or a song no longer on Spotify
```

With no problems and no limit lines: `Road Trip Mix: 41 songs, all fine`.

- [ ] **Step 1: Write the failing tests** — one per kind (`test_unreadable_position`, `test_missing`,
  `test_explicit_in_place_of_clean`, `test_clean_matching_clean_is_fine`, `test_version_word`,
  `test_version_word_in_spotify_title_is_fine` ("Live Forever" by Oasis passes), `test_wrong_artist`,
  `test_artist_matches_through_topic_channel` ("Aimer - Topic" passes), `test_same_upload`, `test_cut_off`,
  `test_length_off`, `test_from_a_video`), plus `test_first_problem_wins` (explicit and wrong length → only
  explicit), `test_report_shape` (the block above, exactly) and `test_report_all_fine`.
- [ ] **Step 2: Run them to see them fail** — `uv run --extra test pytest -q tests/test_checks.py`; Expected: FAIL.
- [ ] **Step 3: Implement `checks.py` as the Interfaces say.**
- [ ] **Step 4: Run the tests** — `uv run --extra test pytest -q`; Expected: all pass.
- [ ] **Step 5: Commit** — `"The report: nine checks on each song, and Yoto's limits"`

---

### Task 7: Syncing a playlist

**Files:**
- Create: `src/spotify_to_yoto/sync.py`
- Test: `tests/test_sync.py`

**Interfaces:**
- Consumes: Tasks 2, 4 (`check_limits`, `read_tracks`' `Track`), 5 and 6.
- Produces:
  - `sync.Result = namedtuple("Result", "folder report")`.
  - `sync.sync(url, music, fetch=spotify.fetch, matcher=None, fetcher=download.Fetcher) -> Result`. In order,
    under `state.locked(folder)`:
    1. `playlist = fetch(url)`; `folder = state.folder_for(music, playlist.name, url)`; create it.
    2. Songs in the state but not in the playlist: delete their files, drop them.
    3. For each song: wanted URL = `fixes[url]`, else the state's match URL if its file exists, else
       `matcher.find(song.song)` (eight at a time). Songs whose wanted URL differs from their file's, or have no
       file, are downloaded: delete the old file, set `song.song.download_url`, `fetcher(folder).get(...)`.
       A fix's match comes from `matcher.describe(url)`.
    4. Number every file `f"{position:0{width}d} - {base}"`, `width = max(2, len(str(playlist.length)))`, `base`
       the name without any old number. Rename in two passes (each to a temporary name first) so swapped
       positions never overwrite each other.
    5. Write `music / f"{folder.name}.m3u8"`: `#EXTM3U`, then per file in order `#EXTINF:<seconds>,<artists> -
       <title>` and `<folder name>/<file>`.
    6. Save state (`spotify`, `name`, `cover`, songs with file, position and match). Keep `yoto` and `fixes`.
    7. Report: `checks.find` + `checks.report`. File lengths come from `push.read_tags`, and the limit lines from
       `push.check_limits(push.read_tracks(folder)[0])`; the tests patch `push.read_tags`.
  - Saves state after step 3 as well, so an interrupted run doesn't download again.

- [ ] **Step 1: Write the failing tests** (fake `fetch`, fake Matcher, a fake Fetcher that writes small files)

```python
def test_first_sync_downloads_numbers_and_writes_m3u8(self): ...
def test_second_sync_downloads_nothing(self): ...        # fake fetcher records zero songs asked for
def test_reorder_swaps_without_overwriting(self): ...     # positions 1↔2 swap: both files survive, contents follow
def test_removed_song_is_deleted(self): ...
def test_fix_replaces_the_match_and_file(self): ...       # fixes[url] set → old file gone, new one downloaded, the
    # state's match is describe()'s
def test_dropped_download_is_reported_missing(self): ...  # fetcher returns no path → report lists "Missing"
def test_state_saved_before_numbering(self): ...          # numbering raises → state already lists the download
```

- [ ] **Step 2: Run them to see them fail** — `uv run --extra test pytest -q tests/test_sync.py`; Expected: FAIL.
- [ ] **Step 3: Implement `sync.py` as the Interfaces say.**
- [ ] **Step 4: Run the tests** — `uv run --extra test pytest -q`; Expected: all pass.
- [ ] **Step 5: Commit** — `"Sync a playlist: download what's new, delete what's gone, number in Spotify's order"`

---

### Task 8: The command line

**Files:**
- Create: `src/spotify_to_yoto/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `cli.main(argv) -> int`, `cli.run()` (`sys.exit(main(sys.argv[1:]))`). The first word picks the
  command; anything else is the sync:
  - `spotify-to-yoto <link or file> ... [--push] [--music DIR]`: `ensure_tools()`, `spotify.connect`, then for each
    URL from `links.expand`: `sync.sync`, print the report; with `--push`, `push.push(folder)` straight after and
    print `"<name>" is in your Yoto library. Link it to a card in the Yoto app.` Without `--push`, end with
    `To put them on Yoto: spotify-to-yoto push "<folder>" ["<folder>" ...]`.
  - `spotify-to-yoto push <link or folder> ... [--music DIR]`: a link → `state.find_folder`; a name or path →
    `music / Path(arg).name` (a dragged-in path works).
  - `spotify-to-yoto fix <track link> <YouTube link> [--music DIR]`: `state.find_song`; refuses a YouTube link that
    isn't `youtube.com/watch?v=`, `music.youtube.com/watch?v=` or `youtu.be/`; records `fixes[track] = link`
    (canonical `https://music.youtube.com/watch?v=<id>`), then syncs that playlist and prints its report.
  - `spotify-to-yoto settings [--music DIR] [--yoto-client-id ID] [--spotify-client-id ID]
    [--spotify-client-secret SECRET]`: saves what's given; with none, prints the settings with the secret shown as
    `(set)`.
  - One playlist failing (`LinkError`, `SpotifyFailure`, `LockedError`, `PushError`, `YotoError`, `AuthError`)
    prints its message and the run goes on to the next; exit 1 if any failed, else 0. A song flagged in a report
    is not a failure. Ctrl-C prints "Stopped." and exits 130.

- [ ] **Step 1: Write the failing tests** (sync, push, connect and ensure_tools patched)

```python
def test_sync_then_prints_push_hint(self): ...
def test_push_flag_pushes_each_after_its_sync(self): ...
def test_one_bad_link_does_not_stop_the_rest(self): ...   # exit 1, second playlist still synced
def test_push_takes_a_dragged_path(self): ...
def test_fix_records_and_resyncs(self): ...
def test_fix_refuses_a_non_youtube_link(self): ...
def test_settings_hides_the_secret(self): ...
```

- [ ] **Step 2: Run them to see them fail** — `uv run --extra test pytest -q tests/test_cli.py`; Expected: FAIL.
- [ ] **Step 3: Implement `cli.py` with argparse, one parser per command.**
- [ ] **Step 4: Run the tests** — `uv run --extra test pytest -q`; Expected: all pass.
- [ ] **Step 5: Commit** — `"Command line: sync with --push, push, fix and settings"`

---

### Task 9: README

**Files:**
- Create: `README.md`

Sections, in plain words: what it does (one paragraph and the three-step picture: link → folder of songs → Yoto
playlist); "For personal use" and "Not affiliated with Spotify, YouTube or Yoto"; Install (`uv tool install
git+https://github.com/lyonsa/spotify-to-yoto`, with how to get uv; pipx with Python 3.11+ as the other way;
`uv tool upgrade spotify-to-yoto` when downloads start failing); Set up Yoto (the four steps from today's README,
`spotify-to-yoto settings --yoto-client-id`); Use it (one link, several, a file; `--music`; `settings --music`);
Reading the report (each of the nine lines and what to do; `fix`); Put it on Yoto (`push`, `--push`, covers: the
Spotify cover the first time, the app's after; reruns update the same playlist; never deletes on Yoto; limits);
Which playlists work (public ones; say plainly if Spotify's own playlists don't, per Task 10's live check); Your
own Spotify keys (when and how); Where things are kept (music folder, `.spotify-to-yoto.json`, settings folder,
sign-in in the system keyring); Credits (spotDL, MIT; yoto-library by Steve Rice, MIT); Licence.

- [ ] **Step 1: Write it.**
- [ ] **Step 2: Check every command in it against `spotify-to-yoto <command> --help`.**
- [ ] **Step 3: Commit** — `"README: install, Yoto set-up, the report and pushing"`

---

### Task 10: Live check, Allen's move, and publishing

Run on Allen's Mac. Steps 5 and 6 change things outside the repo: ask Allen before each.

- [ ] **Step 1: Install from the working tree** — `uv tool install --editable ~/Documents/spotify-to-yoto`;
  Expected: `spotify-to-yoto --help` works.
- [ ] **Step 2: A clean live run in the scratchpad** — `spotify-to-yoto --music <scratchpad>/music
  https://open.spotify.com/playlist/1A2b3C4d5E6f7G8h9I0jKl`. Expected: ffmpeg and Deno download once if missing;
  41 songs (or the playlist's current count) numbered in order; a report; compare its flags with the
  `check.py` run from 2026-11-16 and explain any new ones. Try one Spotify-made playlist link and record whether it
  reads, for the README. Delete the scratch music afterwards.
- [ ] **Step 3: Move Allen's settings** — `spotify-to-yoto settings --music
  /Volumes/Music/Playlists --yoto-client-id <from ~/Docker/spotdl/yoto.env, not printed>`.
- [ ] **Step 4: Write the state for Road Trip Mix** with a throwaway script in the scratchpad (not
  committed): `spotify` and Spotify's name from `~/Docker/spotdl/sync/1A2b3C4d5E6f7G8h9I0jKl.spotdl`; each song's
  file found by its Spotify link tag, its match from the record's `download_url` (album, artists, explicit and
  length left for the next sync to fill: run `matcher.describe` on each); `yoto`: its existing Yoto card id. Then run
  `spotify-to-yoto https://open.spotify.com/playlist/1A2b3C4d5E6f7G8h9I0jKl`. Expected: nothing downloads; the
  folder is still "Road Trip Mix"; a report.
- [ ] **Step 5: Push (ask Allen first)** — `spotify-to-yoto push "Road Trip Mix"`. Expected: its existing Yoto playlist
  updated, same chapter count, cover kept, one playlist of that name.
- [ ] **Step 6: Retire the old setup (ask Allen first)** — delete `~/Docker/spotdl`, the `spotdl-deno:local` image
  and the `yoto-push` Keychain entry; rewrite the memory note `spotdl-yoto-playlists.md` for the new tool.
- [ ] **Step 7: Publish (ask Allen first)** — `gh repo create lyonsa/spotify-to-yoto --public`, push `main` and
  the build branch, open a PR with What, How, Checked live, "Known, not fixed here" and Tests, linking the spec
  and this plan. Expected: CI green on all three systems.
