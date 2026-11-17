import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spotify_to_yoto import settings


class SettingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "config"
        patcher = mock.patch.object(settings, "config_dir", return_value=self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_empty_settings(self):
        self.assertEqual(settings.load(), {})

    def test_settings_round_trip(self):
        settings.save({"music": "/m", "yoto_client_id": "abc"})
        self.assertEqual(settings.load(), {"music": "/m", "yoto_client_id": "abc"})

    def test_music_defaults_beside_home(self):
        self.assertEqual(settings.music(), Path.home() / "Music" / "spotify-to-yoto")

    def test_music_from_settings_and_override(self):
        settings.save({"music": "/Volumes/Music"})
        self.assertEqual(settings.music(), Path("/Volumes/Music"))
        self.assertEqual(settings.music("/elsewhere"), Path("/elsewhere"))


if __name__ == "__main__":
    unittest.main()
