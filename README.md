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
spotify-to-yoto "https://open.spotify.com/playlist/1A2b3C4d5E6f7G8h9I0jKl?si=…"
```

Put each link in quotes: links copied from Spotify and YouTube have a `?` in them, which the Mac's shell would
otherwise read as a file pattern ("no matches found").

Give it one link, several, or a text file with one link a line (lines starting with `#` are skipped). The playlist
must be public on Spotify.

Each playlist gets a folder named after it, inside your music folder (`~/Music/spotify-to-yoto` unless you change
it). The songs are named `07 - Artist - Title.m4a`, numbered in the playlist's order, and a `<playlist>.m3u8` sits
beside the folder.

Run it again with the same link to bring the folder up to date: it downloads new songs, deletes songs taken off the
playlist, and renumbers if the order changed. Songs it already has aren't downloaded again. You can rename a
playlist's folder; it's still found, and the Yoto playlist takes your name.

To keep the music somewhere else:

```sh
spotify-to-yoto settings --music /Volumes/Music/Playlists   # from now on
spotify-to-yoto --music /Volumes/Music/Playlists <link>     # this time only
```

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
| Wrong version | YouTube's title has a word Spotify's doesn't: live, remix, karaoke, instrumental, cover, sped up, slowed or acoustic. |
| Wrong artist | None of YouTube's artists match Spotify's. |
| Same upload as another song | Two songs matched one upload, so one of them is wrong. |
| Cut-off file | The file is much shorter than the upload: the download broke off. |
| Length doesn't match Spotify's | More than 3 seconds longer or shorter than Spotify's song. |
| From a video, not an album track | The upload isn't from an album, so it may be a music video with extra sound. |

Listen to the link. If it's wrong, find the right song on [YouTube Music](https://music.youtube.com) (or YouTube),
copy its link, and run the line the report gives, with the link inside the quotes:

```sh
spotify-to-yoto fix https://open.spotify.com/track/… "https://music.youtube.com/watch?v=…"
```

That downloads the new upload, keeps your choice for every later run, and prints the playlist's report again.

## Put it on Yoto

```sh
spotify-to-yoto push "Road Trip Mix"
```

Give the folder's name, the folder itself (drag it into the terminal), or the playlist's Spotify link; several at
once is fine. To download and push in one go, add `--push` to the download command; the report still prints first.

The first push makes a playlist named after the folder, with the Spotify playlist's cover and Yoto's default track
icons. Link it to a card in the Yoto app. Pushing again updates the same playlist: it keeps whatever cover the
playlist has by then, so a cover you set in the Yoto app stays. Yoto skips songs it already has.

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
| What each playlist remembers (its link, matches, your fixes, its Yoto playlist) | `.spotify-to-yoto.json` inside its folder |
| Settings | `spotify-to-yoto settings` with no options shows them; the file is `settings.json` in your user settings folder |
| The Yoto sign-in | Your system's keyring (Keychain, Credential Manager or Secret Service), or a private file beside the settings where there's none |

## Credits

- [spotDL](https://github.com/spotDL/spotify-downloader) (MIT) reads Spotify and downloads from YouTube Music.
- The Yoto calls follow [yoto-library](https://github.com/steverice/yoto-library) by Steve Rice (MIT).

## Licence

MIT. See [LICENSE](LICENSE).
