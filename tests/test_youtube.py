import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yt_dlp.cookies

from spotify_to_yoto import youtube


class Answers:
    """Stands in for input(): hands out the user's answers in order, and records the questions."""

    def __init__(self, *answers):
        self.answers, self.asked = list(answers), []

    def __call__(self, question=""):
        self.asked.append(question)
        return self.answers.pop(0)


class BrowserTest(unittest.TestCase):
    def test_registers_another_chromium_browser(self):
        youtube.register({"browser": "dia", "dir": "/x/Dia/User Data", "keyring": "Dia"})
        self.assertIn("dia", yt_dlp.cookies.SUPPORTED_BROWSERS)
        self.assertIn("dia", yt_dlp.cookies.CHROMIUM_BASED_BROWSERS)
        found = yt_dlp.cookies._get_chromium_based_browser_settings("dia")
        self.assertEqual((found["browser_dir"], found["keyring_name"]), ("/x/Dia/User Data", "Dia"))
        self.assertEqual(yt_dlp.cookies._get_chromium_based_browser_settings("chrome")["keyring_name"], "Chrome")

    def test_yt_dlp_args(self):
        self.assertEqual(youtube.yt_dlp_args({"browser": "chrome"}), "--cookies-from-browser chrome")
        self.assertEqual(youtube.yt_dlp_args({"browser": "dia", "dir": "/d", "keyring": "Dia"}),
                         "--cookies-from-browser dia")
        self.assertIsNone(youtube.yt_dlp_args(False))
        self.assertIsNone(youtube.yt_dlp_args(None))

    def test_find_other_browser_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "Dia" / "User Data").mkdir(parents=True)
            with mock.patch.object(youtube, "_app_data", return_value=[Path(tmp)]):
                self.assertEqual(youtube.find_other("Dia"), Path(tmp) / "Dia" / "User Data")
                self.assertIsNone(youtube.find_other("Nope"))


class AskTest(unittest.TestCase):
    def setUp(self):
        self.installed = self.patch("installed", mock.Mock(return_value=[("chrome", "Chrome"), ("safari", "Safari")]))
        self.signed_in = self.patch("signed_in", mock.Mock(return_value=True))
        self.premium = self.patch("has_premium", mock.Mock(return_value=True))
        self.open_sign_in = self.patch("open_sign_in", mock.Mock())
        self.printed = []
        self.patch("print", lambda *a, **k: self.printed.append(" ".join(map(str, a))))

    def patch(self, name, value):
        patcher = mock.patch.object(youtube, name, value, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def ask(self, *answers):
        self.answers = Answers(*answers)
        return youtube.ask(self.answers)

    def test_no_premium(self):
        self.assertIs(self.ask("n"), False)
        self.signed_in.assert_not_called()
        self.assertIn("YouTube Premium", self.answers.asked[0])

    def test_empty_answer_means_no(self):
        self.assertIs(self.ask(""), False)

    def test_known_browser(self):
        self.assertEqual(self.ask("y", "1"), {"browser": "chrome"})
        self.assertTrue(any("Other" in line for line in self.printed))

    def test_other_browser(self):
        with mock.patch.object(youtube, "find_other", return_value=Path("/A/Dia/User Data")):
            config = self.ask("yes", "3", "Dia")
        self.assertEqual(config, {"browser": "dia", "dir": str(Path("/A/Dia/User Data")), "keyring": "Dia"})

    def test_other_browser_not_found_asks_for_its_folder(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(youtube, "find_other", return_value=None):
            config = self.ask("y", "3", "Comet", tmp)
        self.assertEqual(config, {"browser": "comet", "dir": tmp, "keyring": "Comet"})

    def test_not_signed_in_opens_sign_in_and_checks_again(self):
        self.signed_in.side_effect = [False, True]
        self.assertEqual(self.ask("y", "2", ""), {"browser": "safari"})
        self.open_sign_in.assert_called_once_with({"browser": "safari"}, "Safari")

    def test_still_not_signed_in_saves_nothing(self):
        self.signed_in.return_value = False
        self.assertIsNone(self.ask("y", "1", ""))
        self.premium.assert_not_called()

    def test_signed_in_without_premium(self):
        self.premium.return_value = False
        self.assertIs(self.ask("y", "1"), False)
        self.assertTrue(any("doesn't seem to have Premium" in line for line in self.printed))

    def test_browser_that_cant_be_read_saves_nothing(self):
        # A Keychain prompt the user denied, or Safari without Full Disk Access.
        self.signed_in.side_effect = youtube.SignInError("Couldn't read Chrome's sign-in: denied.")
        self.assertIsNone(self.ask("y", "1"))
        self.assertTrue(any("denied" in line for line in self.printed))

    def test_unknown_choice_asks_again(self):
        self.assertEqual(self.ask("y", "9", "x", "1"), {"browser": "chrome"})


class PremiumCheckTest(unittest.TestCase):
    def test_has_premium_looks_for_the_256_kbps_stream(self):
        formats = [{"vcodec": "none", "acodec": "mp4a", "abr": 129.5}, {"vcodec": "none", "acodec": "mp4a", "abr": 258}]
        with mock.patch.object(youtube, "_formats", return_value=formats):
            self.assertTrue(youtube.has_premium({"browser": "chrome"}))
        with mock.patch.object(youtube, "_formats", return_value=formats[:1]):
            self.assertFalse(youtube.has_premium({"browser": "chrome"}))

    def test_signed_in_looks_for_a_youtube_sign_in_cookie(self):
        jar = [mock.Mock(domain=".youtube.com", name="x")]
        jar[0].name = "__Secure-3PAPISID"
        with mock.patch.object(youtube.yt_dlp.cookies, "extract_cookies_from_browser", return_value=jar):
            self.assertTrue(youtube.signed_in({"browser": "chrome"}))
        with mock.patch.object(youtube.yt_dlp.cookies, "extract_cookies_from_browser", return_value=[]):
            self.assertFalse(youtube.signed_in({"browser": "chrome"}))

    def test_unreadable_browser_is_a_sign_in_error(self):
        with mock.patch.object(youtube.yt_dlp.cookies, "extract_cookies_from_browser",
                               side_effect=Exception("cannot decrypt")):
            with self.assertRaises(youtube.SignInError) as err:
                youtube.signed_in({"browser": "chrome"})
        self.assertIn("cannot decrypt", str(err.exception))


if __name__ == "__main__":
    unittest.main()
