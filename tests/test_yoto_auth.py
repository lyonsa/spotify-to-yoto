import base64
import hashlib
import io
import json
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error

import keyring.errors
from concurrent.futures import ThreadPoolExecutor
from http.server import HTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from spotify_to_yoto.yoto import auth as yoto_auth


def completed(stdout="", code=0):
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=stdout, stderr="")


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class PkceTest(unittest.TestCase):
    def test_pkce_pair(self):
        verifier, challenge = yoto_auth.pkce_pair()
        self.assertTrue(43 <= len(verifier) <= 128, len(verifier))
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(challenge, expected)

    def test_authorize_url(self):
        url = urlparse(yoto_auth.authorize_url("cid", "chal", "st8"))
        self.assertEqual(f"{url.scheme}://{url.netloc}{url.path}", "https://login.yotoplay.com/authorize")
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.assertEqual(q["audience"], "https://api.yotoplay.com")
        # No offline_access: Allen's dashboard doesn't offer it, so asking for it could fail the sign-in.
        self.assertEqual(q["scope"], "user:content:view user:content:manage family:library:view")
        self.assertEqual(q["response_type"], "code")
        self.assertEqual(q["client_id"], "cid")
        self.assertEqual(q["code_challenge"], "chal")
        self.assertEqual(q["code_challenge_method"], "S256")
        self.assertEqual(q["redirect_uri"], "http://127.0.0.1:8787/callback")
        self.assertEqual(q["state"], "st8")


class ClientIdTest(unittest.TestCase):
    def test_client_id_from_settings(self):
        with mock.patch.object(yoto_auth.settings, "load", return_value={"yoto_client_id": "abc123"}):
            self.assertEqual(yoto_auth.client_id(), "abc123")

    def test_client_id_without_terminal_points_to_readme(self):
        with mock.patch.object(yoto_auth.settings, "load", return_value={}), \
                mock.patch.object(yoto_auth.sys.stdin, "isatty", return_value=False), \
                mock.patch("builtins.input") as ask:
            with self.assertRaises(yoto_auth.AuthError) as err:
                yoto_auth.client_id()
        ask.assert_not_called()
        self.assertIn("README", str(err.exception))
        self.assertIn("--yoto-client-id", str(err.exception))

    def test_client_id_asked_and_saved(self):
        with mock.patch.object(yoto_auth.settings, "load", return_value={"music": "/m"}), \
                mock.patch.object(yoto_auth.settings, "save") as save, \
                mock.patch.object(yoto_auth.sys.stdin, "isatty", return_value=True), \
                mock.patch("builtins.input", return_value=" abc "), \
                mock.patch("builtins.print") as shown:
            self.assertEqual(yoto_auth.client_id(), "abc")
        save.assert_called_once_with({"music": "/m", "yoto_client_id": "abc"})
        printed = " ".join(str(c) for c in shown.call_args_list)
        self.assertIn("http://127.0.0.1:8787/callback", printed)


class TokenStoreTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        patcher = mock.patch.object(yoto_auth.settings, "config_dir", return_value=self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    tokens = {"access_token": "a", "refresh_token": "r", "token_type": "Bearer", "expires_at": 5.0}

    def test_tokens_round_trip_through_keyring(self):
        kept = {}
        with mock.patch.object(yoto_auth.keyring, "set_password",
                               side_effect=lambda s, u, p: kept.update({(s, u): p})), \
                mock.patch.object(yoto_auth.keyring, "get_password", side_effect=lambda s, u: kept.get((s, u))):
            yoto_auth.save_tokens(self.tokens)
            self.assertEqual(list(kept), [("spotify-to-yoto", "yoto")])
            self.assertEqual(yoto_auth.load_tokens(), self.tokens)
        self.assertFalse((self.dir / "yoto-sign-in.json").exists())

    def test_keyring_refusal_falls_back_to_file(self):
        # Windows Credential Manager refuses a long token; the sign-in must still be kept.
        refused = keyring.errors.PasswordSetError("blob too large")
        with mock.patch.object(yoto_auth.keyring, "set_password", side_effect=refused), \
                mock.patch.object(yoto_auth.keyring, "get_password", return_value=None):
            yoto_auth.save_tokens(self.tokens)
            self.assertEqual(yoto_auth.load_tokens(), self.tokens)
        self.assertTrue((self.dir / "yoto-sign-in.json").exists())

    def test_no_keyring_reads_file(self):
        (self.dir / "yoto-sign-in.json").write_text(json.dumps(self.tokens))
        with mock.patch.object(yoto_auth.keyring, "get_password", side_effect=keyring.errors.NoKeyringError()):
            self.assertEqual(yoto_auth.load_tokens(), self.tokens)

    def test_no_tokens_yet(self):
        with mock.patch.object(yoto_auth.keyring, "get_password", return_value=None):
            self.assertIsNone(yoto_auth.load_tokens())


class RefreshTest(unittest.TestCase):
    def test_refresh_keeps_old_refresh_token(self):
        answer = {"access_token": "new", "token_type": "Bearer", "expires_in": 3600}
        with mock.patch.object(yoto_auth, "urlopen", return_value=FakeResponse(json.dumps(answer).encode())) as op:
            tokens = yoto_auth.refresh("cid", {"refresh_token": "old-r"})
        self.assertEqual(tokens["access_token"], "new")
        self.assertEqual(tokens["refresh_token"], "old-r")
        self.assertGreater(tokens["expires_at"], time.time() + 3500)
        sent = json.loads(op.call_args[0][0].data)
        self.assertEqual(sent, {"grant_type": "refresh_token", "client_id": "cid", "refresh_token": "old-r"})

    def setUp(self):
        yoto_auth._cached = None  # each test starts as a fresh run of the script

    def test_revoked_refresh_falls_back_to_browser(self):
        stale = {"access_token": "a", "refresh_token": "r", "token_type": "Bearer", "expires_at": 0.0}
        fresh = {"access_token": "b", "refresh_token": "r2", "token_type": "Bearer", "expires_at": time.time() + 3600}
        denied = yoto_auth.AuthError("Yoto refused the sign-in (403): {}")
        with mock.patch.object(yoto_auth, "client_id", return_value="cid"), \
                mock.patch.object(yoto_auth, "load_tokens", return_value=stale), \
                mock.patch.object(yoto_auth, "refresh", side_effect=denied), \
                mock.patch.object(yoto_auth, "browser_sign_in", return_value=fresh) as browser, \
                mock.patch.object(yoto_auth, "save_tokens") as save:
            self.assertEqual(yoto_auth.access_token(), "b")
        browser.assert_called_once_with("cid")
        save.assert_called_once_with(fresh)

    def test_parallel_callers_sign_in_once(self):
        # The upload workers all ask for a token at once on the first run: one browser sign-in, not four.
        fresh = {"access_token": "b", "refresh_token": "r", "token_type": "Bearer", "expires_at": time.time() + 3600}

        def slow_sign_in(client):
            time.sleep(0.2)
            return fresh

        with mock.patch.object(yoto_auth, "client_id", return_value="cid"), \
                mock.patch.object(yoto_auth, "load_tokens", return_value=None), \
                mock.patch.object(yoto_auth, "browser_sign_in", side_effect=slow_sign_in) as browser, \
                mock.patch.object(yoto_auth, "save_tokens"):
            with ThreadPoolExecutor(max_workers=4) as pool:
                tokens = list(pool.map(lambda _: yoto_auth.access_token(), range(4)))
        self.assertEqual(tokens, ["b"] * 4)
        browser.assert_called_once()

    def test_token_kept_in_memory(self):
        fresh = {"access_token": "b", "refresh_token": "r", "token_type": "Bearer", "expires_at": time.time() + 3600}
        with mock.patch.object(yoto_auth, "client_id", return_value="cid"), \
                mock.patch.object(yoto_auth, "load_tokens", return_value=fresh) as load:
            yoto_auth.access_token()
            yoto_auth.access_token()
        load.assert_called_once()

    def test_refused_exchange_says_why(self):
        refused = urllib.error.HTTPError("u", 401, "Unauthorized", {}, io.BytesIO(b'{"error":"unauthorized_client"}'))
        with mock.patch.object(yoto_auth, "urlopen", side_effect=refused):
            with self.assertRaises(yoto_auth.AuthError) as err:
                yoto_auth.post_token({"grant_type": "authorization_code"}, as_json=False)
        self.assertIn("401", str(err.exception))
        self.assertIn("unauthorized_client", str(err.exception))

    def test_fresh_tokens_are_used_as_they_are(self):
        fresh = {"access_token": "b", "refresh_token": "r", "token_type": "Bearer", "expires_at": time.time() + 3600}
        with mock.patch.object(yoto_auth, "client_id", return_value="cid"), \
                mock.patch.object(yoto_auth, "load_tokens", return_value=fresh), \
                mock.patch.object(yoto_auth, "refresh") as refresh:
            self.assertEqual(yoto_auth.access_token(), "b")
        refresh.assert_not_called()


class CallbackTest(unittest.TestCase):
    def server(self, params):
        return mock.Mock(params=params)

    def test_callback_returns_code(self):
        self.assertEqual(yoto_auth.wait_for_code(self.server({"code": "c", "state": "s"}), "s"), "c")

    def test_callback_rejects_wrong_state(self):
        with self.assertRaises(yoto_auth.AuthError):
            yoto_auth.wait_for_code(self.server({"code": "c", "state": "other"}), "s")

    def test_idle_connection_does_not_stall_sign_in(self):
        # Browsers open spare connections that send nothing; the wait must still end on time.
        server = HTTPServer(("127.0.0.1", 0), yoto_auth._Callback)
        server.params, server.timeout = None, 0.1
        idle = socket.create_connection(server.server_address)
        self.addCleanup(idle.close)
        self.addCleanup(server.server_close)
        start = time.monotonic()
        with self.assertRaises(yoto_auth.AuthError):
            yoto_auth.wait_for_code(server, "s", timeout=0.5)
        self.assertLess(time.monotonic() - start, 8)  # the handler gives up on a silent connection after 5 s

    def test_callback_reports_refusal(self):
        with self.assertRaises(yoto_auth.AuthError) as err:
            yoto_auth.wait_for_code(self.server({"error": "access_denied", "state": "s"}), "s")
        self.assertIn("access_denied", str(err.exception))


if __name__ == "__main__":
    unittest.main()
