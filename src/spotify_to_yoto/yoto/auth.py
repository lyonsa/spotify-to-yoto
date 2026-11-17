"""Signs in to Yoto in the browser (OAuth PKCE, loopback redirect) and keeps the sign-in in the macOS Keychain.

Follows yoto-library 0.4.0's auth.py (Steve Rice, MIT: https://github.com/steverice/yoto-library), with the
standard library in place of httpx. The sign-in is kept in the system's keyring, or in a private file where there's
none.
"""
import base64
import hashlib
import json
import secrets
import os
import sys
import threading
import time
import urllib.error
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

import keyring

from spotify_to_yoto import settings

LOGIN = "https://login.yotoplay.com"
AUDIENCE = "https://api.yotoplay.com"
# Every scope by name: Yoto's tokens carry only what's asked for, and reading a playlist back needs
# user:content:view and family:library:view as well as user:content:manage (found by yoto-library).
# Not offline_access: the dashboard doesn't offer it for this app, so there's no refresh token, and an expired
# sign-in means signing in again in the browser.
SCOPES = "user:content:view user:content:manage family:library:view"
HOST, PORT, CALLBACK = "127.0.0.1", 8787, "/callback"
REDIRECT = f"http://{HOST}:{PORT}{CALLBACK}"
KEYRING = ("spotify-to-yoto", "yoto")
TOKEN_FILE = "yoto-sign-in.json"
SIGN_IN_WAIT = 300  # seconds
REFRESH_MARGIN = 30  # seconds
# The upload workers all ask for a token at once: one of them signs in or refreshes, the rest wait for it.
_lock = threading.Lock()
_cached = None


class AuthError(Exception):
    pass


SET_UP = f"""To use Yoto, make your own Yoto developer app (once):
  1. Sign in at https://dashboard.yoto.dev and create an application.
  2. Set Application Type to Public Client.
  3. Under Allowed Callback URLs, enter {REDIRECT}
  4. Under Scopes, tick family:library:view and user:content:manage.
Then copy the app's client ID."""


def client_id():
    """The user's Yoto app client ID: from the settings, or asked for once and saved."""
    values = settings.load()
    if values.get("yoto_client_id"):
        return values["yoto_client_id"]
    if not sys.stdin.isatty():
        raise AuthError("No Yoto client ID set. Follow \"Set up Yoto\" in the README, then run: "
                        "spotify-to-yoto settings --yoto-client-id <your client ID>")
    print(SET_UP)
    answer = input("Client ID: ").strip()
    if not answer:
        raise AuthError("No Yoto client ID given.")
    settings.save({**values, "yoto_client_id": answer})
    return answer


def pkce_pair():
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(client, challenge, state):
    return f"{LOGIN}/authorize?" + urlencode({
        "audience": AUDIENCE, "scope": SCOPES, "response_type": "code", "client_id": client,
        "code_challenge": challenge, "code_challenge_method": "S256", "redirect_uri": REDIRECT, "state": state})


def _token_file():
    return settings.config_dir() / TOKEN_FILE


def load_tokens():
    try:
        saved = keyring.get_password(*KEYRING)
    except Exception:  # keyring backends raise their own errors, not only KeyringError
        saved = None
    if saved is None and _token_file().exists():
        saved = _token_file().read_text(encoding="utf-8")
    if not saved:
        return None
    try:
        return json.loads(saved)
    except ValueError:
        return None


def save_tokens(tokens):
    text = json.dumps(tokens)
    try:
        keyring.set_password(*KEYRING, text)
        _token_file().unlink(missing_ok=True)
        return
    except Exception:
        # No keyring here, or one that refuses a token this long: Windows raises pywintypes.error, not a
        # KeyringError. Keep it in a private file, and clear any older entry, which load_tokens would read first.
        try:
            keyring.delete_password(*KEYRING)
        except Exception:
            pass
    path = _token_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def tokens_from(answer, old_refresh=None):
    # Without refresh-token rotation, a refresh answer has no refresh_token: keep the old one.
    return {"access_token": answer["access_token"], "refresh_token": answer.get("refresh_token") or old_refresh or "",
            "token_type": answer.get("token_type", "Bearer"), "expires_at": time.time() + answer["expires_in"]}


def post_token(body, as_json):
    data = json.dumps(body).encode() if as_json else urlencode(body).encode()
    kind = "application/json" if as_json else "application/x-www-form-urlencoded"
    req = Request(f"{LOGIN}/oauth/token", data=data, headers={"Content-Type": kind}, method="POST")
    try:
        with urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise AuthError(f"Yoto refused the sign-in ({exc.code}): {detail}") from None
    except OSError as exc:
        raise AuthError(f"Couldn't reach Yoto's sign-in: {getattr(exc, 'reason', exc)}") from None


def refresh(client, tokens):
    answer = post_token({"grant_type": "refresh_token", "client_id": client,
                         "refresh_token": tokens["refresh_token"]}, as_json=True)
    return tokens_from(answer, tokens["refresh_token"])


class _Callback(BaseHTTPRequestHandler):
    timeout = 5  # seconds; browsers open spare connections that send nothing, and one would stall the wait

    def do_GET(self):
        url = urlparse(self.path)
        if url.path != CALLBACK:
            self.send_response(404)
            self.end_headers()
            return
        self.server.params = {k: v[0] for k, v in parse_qs(url.query).items()}
        body = "Signed in to Yoto. You can close this tab." if "code" in self.server.params \
            else "Yoto sign-in failed. Check the terminal."
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):
        pass  # the code is in the request line; keep it off the terminal


def wait_for_code(server, state, timeout=SIGN_IN_WAIT):
    deadline = time.monotonic() + timeout
    while server.params is None:
        if time.monotonic() >= deadline:
            raise AuthError("Timed out waiting for the Yoto sign-in.")
        server.handle_request()
    params = server.params
    if "error" in params:
        raise AuthError(f"Yoto sign-in failed: {params.get('error_description') or params['error']}")
    if params.get("state") != state:
        raise AuthError("The sign-in reply didn't match this sign-in; refused it.")
    if "code" not in params:
        raise AuthError("The sign-in reply had no code.")
    return params["code"]


def browser_sign_in(client):
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    try:
        server = HTTPServer((HOST, PORT), _Callback)
    except OSError as exc:
        raise AuthError(f"Port {PORT} is busy, so the sign-in can't come back here: {exc}") from exc
    server.params, server.timeout = None, 1.0
    url = authorize_url(client, challenge, state)
    try:
        print(f"Sign in to Yoto in your browser. If it doesn't open, go to:\n{url}")
        webbrowser.open(url)
        code = wait_for_code(server, state)
    finally:
        server.server_close()
    answer = post_token({"grant_type": "authorization_code", "client_id": client, "code_verifier": verifier,
                         "code": code, "redirect_uri": REDIRECT}, as_json=False)
    return tokens_from(answer)


def access_token():
    """A token good for at least another 30 seconds: kept, saved, refreshed, or from a new browser sign-in."""
    global _cached
    with _lock:
        if _cached and _cached["expires_at"] - REFRESH_MARGIN > time.time():
            return _cached["access_token"]
        client = client_id()
        tokens = _cached or load_tokens()
        if not (tokens and tokens["expires_at"] - REFRESH_MARGIN > time.time()):
            fresh = None
            if tokens and tokens.get("refresh_token"):
                try:
                    fresh = refresh(client, tokens)
                except AuthError:
                    pass  # refresh token expired or revoked: sign in again
            tokens = fresh or browser_sign_in(client)
            save_tokens(tokens)
        _cached = tokens
        return tokens["access_token"]
