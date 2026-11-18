"""The user's settings: where the music goes, and the Yoto and Spotify app ids. Kept in settings.json."""
import json
import os
from pathlib import Path

import platformdirs

APP = "spotify-to-yoto"


def config_dir():
    return platformdirs.user_config_path(APP)


def load():
    path = config_dir() / "settings.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save(values):
    folder = config_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "settings.json"
    path.write_text(json.dumps(values, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        os.chmod(path, 0o600)  # it can hold a Spotify app secret
    except OSError:
        pass


def music(override=None):
    """The folder that holds one folder per playlist."""
    if override:
        return Path(override).expanduser()
    chosen = load().get("music")
    return Path(chosen).expanduser() if chosen else Path.home() / "Music" / APP
