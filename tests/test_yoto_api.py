import hashlib
import io
import itertools
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from spotify_to_yoto.yoto import api as yoto_api


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeYoto:
    """Stands in for urlopen: records each request and answers from a route table."""

    def __init__(self, routes):
        self.routes = routes  # (method, path) -> (status, body dict) or a callable returning that
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        url = urlparse(req.full_url)
        answer = self.routes[(req.get_method(), url.path)]
        status, body = answer() if callable(answer) else answer
        data = json.dumps(body).encode()
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "error", {}, io.BytesIO(data))
        return FakeResponse(data)


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.song = Path(self.tmp.name) / "01 - A - One.m4a"
        self.song.write_bytes(b"song bytes")
        self.sha = hashlib.sha256(b"song bytes").hexdigest()
        patcher = mock.patch.object(yoto_api, "access_token", return_value="tok")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def fake(self, routes):
        yoto = FakeYoto(routes)
        patcher = mock.patch.object(yoto_api, "urlopen", yoto)
        patcher.start()
        self.addCleanup(patcher.stop)
        return yoto

    def converted(self):
        return 200, {"transcode": {"transcodedSha256": "t-sha",
                                   "transcodedInfo": {"format": "opus", "channels": "stereo", "duration": 268}}}

    def test_upload_skips_put_when_yoto_has_file(self):
        yoto = self.fake({
            ("GET", "/media/transcode/audio/uploadUrl"): (200, {"upload": {"uploadId": "u1", "uploadUrl": None}}),
            ("GET", "/media/upload/u1/transcoded"): self.converted(),
        })
        result = yoto_api.upload(self.song)
        self.assertEqual(result, {"sha": "t-sha", "format": "opus", "channels": "stereo", "duration": 268})
        self.assertNotIn("PUT", [r.get_method() for r in yoto.requests])
        q = parse_qs(urlparse(yoto.requests[0].full_url).query)
        self.assertEqual(q["sha256"], [self.sha])
        self.assertEqual(q["filename"], ["01 - A - One.m4a"])
        self.assertEqual(parse_qs(urlparse(yoto.requests[1].full_url).query)["loudnorm"], ["false"])

    def test_upload_puts_file_with_audio_mp4(self):
        signed = "https://upload.example/put-here"
        routes = {
            ("GET", "/media/transcode/audio/uploadUrl"): (200, {"upload": {"uploadId": "u1", "uploadUrl": signed}}),
            ("PUT", "/put-here"): (200, {}),
            ("GET", "/media/upload/u1/transcoded"): self.converted(),
        }
        yoto = self.fake(routes)
        yoto_api.upload(self.song)
        put = [r for r in yoto.requests if r.get_method() == "PUT"]
        self.assertEqual(len(put), 1)
        self.assertEqual(put[0].full_url, signed)
        self.assertEqual(put[0].data, b"song bytes")
        self.assertEqual(put[0].get_header("Content-type"), "audio/mp4")
        self.assertIsNone(put[0].get_header("Authorization"))

    def test_conversion_timeout(self):
        self.fake({
            ("GET", "/media/transcode/audio/uploadUrl"): (200, {"upload": {"uploadId": "u1", "uploadUrl": None}}),
            ("GET", "/media/upload/u1/transcoded"): (200, {"transcode": {}}),
        })
        with mock.patch.object(yoto_api.time, "sleep"), \
                mock.patch.object(yoto_api.time, "monotonic", side_effect=itertools.count(0, 10)):
            with self.assertRaises(yoto_api.YotoError) as err:
                yoto_api.upload(self.song)
        self.assertIn("01 - A - One.m4a", str(err.exception))

    def test_get_card_404_is_none(self):
        self.fake({("GET", "/content/c1"): (404, {"error": "not found"})})
        self.assertIsNone(yoto_api.get_card("c1"))

    def test_get_card_returns_card(self):
        self.fake({("GET", "/content/c1"): (200, {"card": {"cardId": "c1", "title": "T"}})})
        self.assertEqual(yoto_api.get_card("c1"), {"cardId": "c1", "title": "T"})

    def test_save_card_returns_id(self):
        yoto = self.fake({("POST", "/content"): (200, {"card": {"cardId": "new1"}})})
        self.assertEqual(yoto_api.save_card({"title": "T"}), "new1")
        self.assertEqual(json.loads(yoto.requests[0].data), {"title": "T"})
        self.assertEqual(yoto.requests[0].get_header("Content-type"), "application/json")

    def test_error_shows_yoto_message(self):
        self.fake({("POST", "/content"): (400, {"message": "chapters invalid"})})
        with self.assertRaises(yoto_api.YotoError) as err:
            yoto_api.save_card({"title": "T"})
        self.assertIn("chapters invalid", str(err.exception))
        self.assertNotIn("tok", str(err.exception))

    def test_save_card_finds_id_elsewhere(self):
        self.fake({("POST", "/content"): (200, {"cardId": "top"})})
        self.assertEqual(yoto_api.save_card({"title": "T"}), "top")

    def test_save_card_without_id_says_so(self):
        self.fake({("POST", "/content"): (200, {"card": {"title": "T"}})})
        with self.assertRaises(yoto_api.YotoError) as err:
            yoto_api.save_card({"title": "T"})
        self.assertIn("didn't return its id", str(err.exception))

    def test_unreachable_yoto_is_a_yoto_error(self):
        with mock.patch.object(yoto_api, "urlopen", side_effect=urllib.error.URLError("no route")):
            with self.assertRaises(yoto_api.YotoError) as err:
                yoto_api.get_card("c1")
        self.assertIn("no route", str(err.exception))

    def test_bearer_header(self):
        yoto = self.fake({("GET", "/content/c1"): (200, {"card": {}})})
        yoto_api.get_card("c1")
        self.assertEqual(yoto.requests[0].get_header("Authorization"), "Bearer tok")


    def test_upload_cover_returns_media_url(self):
        yoto = self.fake({("POST", "/media/coverImage/user/me/upload"):
                          (200, {"coverImage": {"mediaUrl": "https://media/cover.jpg"}})})
        self.assertEqual(yoto_api.upload_cover(b"jpg bytes", "image/jpeg"), "https://media/cover.jpg")
        req = yoto.requests[0]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.data, b"jpg bytes")
        self.assertEqual(req.get_header("Content-type"), "image/jpeg")
        self.assertEqual(parse_qs(urlparse(req.full_url).query), {"autoconvert": ["true"]})

    def test_upload_cover_without_url_says_so(self):
        self.fake({("POST", "/media/coverImage/user/me/upload"): (200, {"coverImage": {}})})
        with self.assertRaises(yoto_api.YotoError):
            yoto_api.upload_cover(b"jpg", "image/jpeg")

if __name__ == "__main__":
    unittest.main()
