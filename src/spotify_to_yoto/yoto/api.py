"""The Yoto calls a push needs: upload a song and wait for Yoto to convert it, read a playlist, save a playlist.

Follows yoto-library 0.4.0's api.py (Steve Rice, MIT: https://github.com/steverice/yoto-library), with the
standard library in place of httpx.
"""
import hashlib
import json
import time
import urllib.error
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from spotify_to_yoto.yoto.auth import access_token

API = "https://api.yotoplay.com"
CONVERT_WAIT = 180  # seconds; yoto-library reports 15-60 s a song, and its own 15 s limit is too short
CONVERT_CHECK = 2  # seconds between checks


class YotoError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def call(method, path, params=None, body=None, raw=None, content_type=None):
    url = f"{API}{path}" + (f"?{urlencode(params)}" if params else "")
    headers = {"Authorization": f"Bearer {access_token()}"}
    data = None
    if raw is not None:
        data = raw
        headers["Content-Type"] = content_type
    elif body is not None:
        data = json.dumps(body, ensure_ascii=False).encode()
        headers["Content-Type"] = "application/json"
    try:
        with urlopen(Request(url, data=data, headers=headers, method=method), timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise YotoError(f"Yoto answered {exc.code} to {method} {path}: {detail}", exc.code) from None
    except OSError as exc:  # URLError, timeouts, dropped connections
        raise YotoError(f"Couldn't reach Yoto for {method} {path}: {getattr(exc, 'reason', exc)}") from None


def get_card(card_id):
    """The playlist as Yoto has it, or None when it's gone (deleted in the app)."""
    try:
        data = call("GET", f"/content/{card_id}")
    except YotoError as exc:
        if exc.status == 404:
            return None
        raise
    return data.get("card", data)


def save_card(payload):
    """Creates the playlist, or updates it when the payload has a cardId; returns its card id."""
    data = call("POST", "/content", body=payload)
    # yoto-library looks in all three places, so Yoto's reply shape seems to vary.
    card_id = data.get("card", {}).get("cardId") or data.get("cardId") or data.get("content", {}).get("cardId")
    if not card_id:
        raise YotoError("Yoto saved the playlist but didn't return its id. Find it in the Yoto app and delete the "
                        "copy if a push makes a second one.")
    return card_id


def upload_cover(data, content_type):
    """Uploads a cover picture; returns the address to put in the playlist's metadata."""
    answer = call("POST", "/media/coverImage/user/me/upload", {"autoconvert": "true"}, raw=data,
                  content_type=content_type)
    image = answer.get("coverImage", answer)
    url = image.get("mediaUrl") or image.get("url") or answer.get("coverUrl")
    if not url:
        raise YotoError("Yoto took the cover but didn't say where it is.")
    return url


def upload(path):
    """Uploads one song (unless Yoto has it already) and waits for Yoto to convert it."""
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    answer = call("GET", "/media/transcode/audio/uploadUrl", {"sha256": sha, "filename": path.name})
    slot = answer.get("upload", answer)
    if slot.get("uploadUrl"):
        # A signed address: it takes the file as it is, with no Yoto sign-in.
        put = Request(slot["uploadUrl"], data=data, headers={"Content-Type": "audio/mp4"}, method="PUT")
        try:
            with urlopen(put, timeout=300):
                pass
        except urllib.error.HTTPError as exc:
            raise YotoError(f"Uploading {path.name} failed: {exc.code}", exc.code) from None
        except OSError as exc:
            raise YotoError(f"Uploading {path.name} failed: {getattr(exc, 'reason', exc)}") from None
    deadline = time.monotonic() + CONVERT_WAIT
    while time.monotonic() < deadline:
        answer = call("GET", f"/media/upload/{slot['uploadId']}/transcoded", {"loudnorm": "false"})
        done = answer.get("transcode", answer)
        if done.get("transcodedSha256"):
            info = done.get("transcodedInfo", {})
            return {"sha": done["transcodedSha256"], "format": info.get("format"), "channels": info.get("channels"),
                    "duration": info.get("duration")}
        time.sleep(CONVERT_CHECK)
    raise YotoError(f"Yoto didn't finish converting {path.name} within {CONVERT_WAIT} seconds.")
