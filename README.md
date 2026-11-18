# spotify-to-yoto

Turn a Spotify playlist into a Yoto playlist, ready to link to a Make Your Own card.

```text
Spotify playlist link  →  a folder of songs, in order  →  a playlist in your Yoto library
```

Give it a Spotify playlist link. It finds each song on YouTube Music and downloads it as an M4A file, numbered in the
playlist's order. It then lists any songs that may be the wrong upload, so you can check them before a child hears
them. When you're happy, one more command puts the playlist in your Yoto library, with the Spotify cover.

It's for personal use: put on your own child's player the music you'd play them anyway. It isn't affiliated with
Spotify, YouTube or Yoto.

## Install

You need [uv](https://docs.astral.sh/uv/getting-started/installation/). Then:

```sh
uv tool install git+https://github.com/lyonsa/spotify-to-yoto
```

uv fetches a suitable Python for it. (Or use pipx with Python 3.11 to 3.15: `pipx install
git+https://github.com/lyonsa/spotify-to-yoto`.)

If your shell then says `spotify-to-yoto: command not found`, run `uv tool update-shell` once and open a new
terminal: uv puts the command in a folder (`~/.local/bin`) your shell may not look in yet.

The first run downloads ffmpeg and Deno, which the downloads need, into spotDL's own folder.

YouTube changes often, and downloads then start to fail. The fix is usually a newer yt-dlp:

```sh
uv tool upgrade spotify-to-yoto
```

## Set up Yoto

Once, make your own Yoto developer app:

1. Sign in at the [Yoto developer dashboard](https://dashboard.yoto.dev) and create an application.
2. Set **Application Type** to **Public Client**.
3. Under **Allowed Callback URLs**, enter `http://127.0.0.1:8787/callback` exactly.
4. Under **Scopes**, tick `family:library:view` and `user:content:manage`. The dashboard then shows
   `user:content:view` as included.
5. Copy the app's client ID and run:

```sh
spotify-to-yoto settings --yoto-client-id <your client ID>
```

(If you skip step 5, the first push asks for the client ID.)

The first push opens your browser to sign in to Yoto. The dashboard doesn't offer long-lived sign-ins to apps like
this, so when a sign-in runs out, a push opens the browser again.

## Download a playlist

```sh
spotify-to-yoto "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=…"
```

Put each link in quotes: links copied from Spotify and YouTube have a `?` in them, which the Mac's shell would
otherwise read as a file pattern ("no matches found"). On a Mac you can skip the quotes for `?` with this line in
`~/.zshrc`, though a link with `&` in it still needs them:

```sh
alias spotify-to-yoto="noglob spotify-to-yoto"
```

Give it one link, several, or a text file with one link a line (lines starting with `#` are skipped). The playlist
must be public on Spotify.

Each playlist gets a folder named after it, inside your music folder (`~/Music/spotify-to-yoto` unless you change
it). The songs are named `07 - Artist - Title.m4a`, numbered in the playlist's order, and a `<playlist>.m3u8` sits
beside the folder. Two songs with the same artist and title (say, one from the album and one from a single) get
their own files: the second is `… (2).m4a`.

Run it again with the same link to bring the folder up to date: it downloads new songs, deletes songs taken off the
playlist, and renumbers if the order changed. Songs it already has aren't downloaded again. You can rename a
playlist's folder, or move it to another music folder; it's still found, and the Yoto playlist takes your name.

Spotify sometimes leaves a song out of the list it sends, though the song is still in the playlist. When its list
is short of the playlist's song count, nothing is deleted that run, and the report says so.

To keep the music somewhere else:

```sh
spotify-to-yoto settings --music /Volumes/Music/Playlists   # from now on
spotify-to-yoto --music /Volumes/Music/Playlists <link>     # this time only
```

## YouTube Premium (optional)

Without Premium, songs come in at about 128 kbps. With a YouTube Premium account, YouTube Music gives 256 kbps.
Everything else works the same either way.

The first time you sync or fix in a terminal, it asks once whether you have Premium:

- **No**: it never asks again.
- **Yes**: pick the browser you're signed in to YouTube with. For a Chromium-based browser that isn't listed (Dia,
  Arc, Comet…), pick **Other** and type its name. If you're not signed in, it opens YouTube's sign-in page in that
  browser and waits for you. It then checks with YouTube that your account gets the 256 kbps stream.

From then on, each download reads your sign-in from that browser, so it stays current while you're signed in there.
Nothing of your sign-in is saved: only which browser to read it from. If a download still comes in at 128 kbps, the
report says so. Some uploads only come at 128 kbps, even with Premium: often a video you picked with `fix` rather
than a YouTube Music song. The report names those songs.

```sh
spotify-to-yoto settings --youtube-premium      # set it up again, or change browser
spotify-to-yoto settings --no-youtube-premium   # turn it off
spotify-to-yoto --redownload "<playlist link>"  # download a playlist's songs again, e.g. at 256 kbps
```

Good to know:

- On a Mac, the first read asks for your Keychain (to unlock the browser's saved sign-ins). Click **Always Allow**,
  or it asks on every run. Safari needs your terminal app to have **Full Disk Access** (System Settings → Privacy &
  Security).
- yt-dlp, the downloader underneath, warns that downloading with a signed-in account carries a small risk of YouTube
  limiting that account.
- Yoto converts every song when it's uploaded, so the player sounds the same either way: Premium is for the copies
  in your music folder.

## Read the report

After each playlist, it prints what to look at. A playlist with nothing to look at gets one line:

```text
Road Trip Mix: 41 songs, all fine
```

Otherwise each song with a problem gets a line, under the first problem it has:

```text
Road Trip Mix: 41 songs, 39 fine, 2 to look at
  07 Wrong artist: Aimer - Kataomoi (YouTube has it by Aimer Fan Channel)
     Listen: https://music.youtube.com/watch?v=…
     To replace it: spotify-to-yoto fix https://open.spotify.com/track/… "<YouTube link>"
  12 Missing: YOASOBI - Idol (no match on YouTube Music)
     To add it: find it on https://music.youtube.com, then spotify-to-yoto fix https://open.spotify.com/track/… "<YouTube link>"
```

| Line | What it means |
| --- | --- |
| Couldn't download | A file of your own on Spotify, or a song no longer on Spotify. Nothing to download. |
| Missing | YouTube Music has no matching song upload, or the download failed. A later run tries again. |
| Explicit in place of clean | The Spotify song is the clean version, and YouTube Music's is marked explicit. |
| Wrong version | YouTube's title has a word that neither Spotify's title nor its album has: live, remix, karaoke, instrumental, cover, sped up, slowed or acoustic. (A live song from a live album isn't flagged.) |
| Wrong artist | None of YouTube's artists match Spotify's. A name inside another counts as a match ("Joan Jett" for "Joan Jett & the Blackhearts"). |
| Same upload as another song | Two songs matched one upload, so one of them is wrong. |
| Cut-off file | The file is much shorter than the upload: the download broke off. |
| Length doesn't match Spotify's | More than 3 seconds longer or shorter than Spotify's song. |
| From a video, not an album track | The upload isn't from an album, so it may be a music video with extra sound. |

The explicit check only catches an explicit upload standing in for a clean song. A song Spotify itself marks
explicit is what the playlist asked for, so it isn't flagged: look over the playlist on Spotify if that matters.

Listen to the link. If it's wrong, find the right song on [YouTube Music](https://music.youtube.com) (or YouTube),
copy its link, and run the line the report gives, with the link inside the quotes:

```sh
spotify-to-yoto fix https://open.spotify.com/track/… "https://music.youtube.com/watch?v=…"
```

That downloads the new upload, keeps your choice for every later run, and prints the playlist's report again. If the
song is in several of your playlists, it's fixed in each. A link YouTube won't play (gone, private or blocked where
you are) is refused before anything changes.

You chose that upload by ear, so from then on the report only checks it for a broken download: it isn't flagged
for its title, artist, length or for being a video. A song with no match at all, such as a recording only on
Spotify, can be fixed the same way with any upload you're happy with.

## Check on your playlists

```sh
spotify-to-yoto status                        # every playlist, one line each
spotify-to-yoto status "Road Trip Mix"        # one playlist's last report
```

`status` reads what the last sync and push left in each folder, so it's instant and asks nothing of Spotify or
YouTube. For each playlist it says whether it's on Yoto and whether the Yoto copy is behind the folder, for example
after a fix. One playlist's status shows its last report and when it was made; run the sync again for a fresh one.

## Put it on Yoto

```sh
spotify-to-yoto push "Road Trip Mix"
```

Give the folder's name, the folder itself (drag it into the terminal), or the playlist's Spotify link; several at
once is fine. To download and push in one go, add `--push` to the download command; the report still prints first.

The first push makes a playlist with the Spotify playlist's name (or your name for its folder, if you renamed it),
the Spotify playlist's cover, and Yoto's default track icons. Its chapters are numbered 1, 2, 3… in order, with no
gaps for songs that couldn't be downloaded. Link it to a card in the Yoto app. Pushing again updates the same
playlist: it keeps whatever cover the playlist has by then, so a cover you set in the Yoto app stays. Yoto skips
songs it already has. After a fix or a sync that changed songs, `status` shows the playlist as behind until you push
again.

It never deletes anything on Yoto. It stops before uploading if a playlist is over Yoto's limits for a Make Your Own
card: 100 tracks; 100 MB and 60 minutes a track; 500 MB and 5 hours in all.

## Which playlists work

Any public playlist: yours, your friends', and Spotify's own (such as Today's Top Hits). With your own Spotify keys
(below), Spotify may refuse its own playlists to your app; when a playlist can't be read, it says so and goes on to
the next link.

## Your own Spotify keys

It reads Spotify through spotDL's shared keys. If Spotify starts refusing (too many requests), make an app at the
[Spotify developer dashboard](https://developer.spotify.com/dashboard) and give it your own:

```sh
spotify-to-yoto settings --spotify-client-id <id> --spotify-client-secret <secret>
```

## Where things are kept

| What | Where |
| --- | --- |
| The songs | Your music folder, one folder per playlist |
| What each playlist remembers (its link, matches, your fixes, its last report, its Yoto playlist and what was last pushed) | `.spotify-to-yoto.json` inside its folder |
| Settings (music folder, Yoto client ID, your own Spotify keys, which browser holds your YouTube Premium sign-in) | `settings.json`, readable only by you: `~/Library/Application Support/spotify-to-yoto/` on a Mac, `~/.config/spotify-to-yoto/` on Linux, `%LOCALAPPDATA%\spotify-to-yoto\spotify-to-yoto\` on Windows. `spotify-to-yoto settings` shows them. |
| The Yoto sign-in | Your system's keyring (Keychain, Credential Manager or Secret Service), or a private file beside the settings where there's none or it refuses |

## When something goes wrong

| You see | What to do |
| --- | --- |
| `no matches found` (Mac) | Put the link in quotes. |
| `command not found: spotify-to-yoto` | Run `uv tool update-shell` and open a new terminal. |
| Downloads failing, `YT-DLP download error` on many songs | YouTube changed something: `uv tool upgrade spotify-to-yoto`. A few failures are normal; the next run tries them again. |
| `Failed to fetch secrets … Falling back to default secret` | Harmless while it carries on. The Spotify reader fetches a key from a volunteer's site, which was slow; reads take longer until it's back. |
| `Couldn't read … from Spotify … The playlist must be public` | Make the playlist public, or check the link. If it keeps happening on every playlist, try again later, or set your own Spotify keys. |
| `Another run is using …` | Wait for the other run. If none is running (one was stopped hard), delete the `.spotify-to-yoto.lock` folder it names. |
| `YouTube Premium is on, but … came in at 128 kbps` | Sign in to YouTube again in the browser you chose, then `spotify-to-yoto --redownload "<playlist link>"`. |
| `At 128 kbps: YouTube has no Premium stream for this upload` | Nothing is wrong with your sign-in. For 256 kbps, find the song on YouTube Music and `fix` the song with that link. |
| `Couldn't read the browser's sign-in` | On a Mac, allow the Keychain prompt (or give your terminal Full Disk Access for Safari), then `spotify-to-yoto settings --youtube-premium`. |
| The browser opens to sign in to Yoto again | Expected: Yoto's sign-in for apps like this runs out, and there's no long-lived one. |
| `Over Yoto's limits` | Split the playlist on Spotify, or remove songs: 100 tracks; 100 MB and 60 minutes a track; 500 MB and 5 hours in all. |

## Credits

- [spotDL](https://github.com/spotDL/spotify-downloader) (MIT) reads Spotify and downloads from YouTube Music.
- The Yoto calls follow [yoto-library](https://github.com/steverice/yoto-library) by Steve Rice (MIT).

## Licence

MIT. See [LICENSE](LICENSE).
