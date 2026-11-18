"""YouTube Premium, optional: downloads read the user's YouTube sign-in from their browser, which gets YouTube
Music's 256 kbps stream in place of 128 kbps. Nothing of the sign-in is saved; only which browser to read it from.

yt-dlp reads sign-ins from browsers it knows by name. A Chromium-based browser it doesn't know (Dia, Arc, Comet…)
keeps its data the same way, so it's registered with yt-dlp at run time: its data folder and its Keychain name.
"""
import os
import re
import subprocess
import sys
import webbrowser
from pathlib import Path

import yt_dlp
import yt_dlp.cookies
from spotdl.utils.deno import get_local_deno_yt_dlp_options

KNOWN = {"chrome": "Chrome", "edge": "Edge", "brave": "Brave", "vivaldi": "Vivaldi", "opera": "Opera",
         "chromium": "Chromium", "whale": "Whale", "firefox": "Firefox", "safari": "Safari"}
MAC_APPS = {"chrome": "Google Chrome", "edge": "Microsoft Edge", "brave": "Brave Browser"}
SIGN_IN_COOKIES = {"SAPISID", "__Secure-1PAPISID", "__Secure-3PAPISID"}
SIGN_IN_PAGE = "https://accounts.google.com/ServiceLogin?service=youtube&continue=https://music.youtube.com/"
PROBE = "https://music.youtube.com/watch?v=ftdZ363R9kQ"  # Stevie Wonder, Superstition: on YouTube Music for years
PREMIUM_KBPS = 200  # free streams top out near 130 kbps, Premium's near 256
AGAIN = "Premium stays off for now; run spotify-to-yoto settings --youtube-premium to try again."

_others = {}
_real_settings = None


class SignInError(Exception):
    pass


def register(config):
    """Teaches yt-dlp a Chromium-based browser it doesn't know by name. Known browsers need nothing."""
    global _real_settings
    if not config or not config.get("dir"):
        return
    cookies = yt_dlp.cookies
    if _real_settings is None:
        if not hasattr(cookies, "_get_chromium_based_browser_settings"):
            raise SignInError("This version of yt-dlp can't read other browsers' sign-ins.")
        _real_settings = cookies._get_chromium_based_browser_settings

        def settings(name):
            if name in _others:
                folder, keyring = _others[name]
                return {"browser_dir": folder, "keyring_name": keyring, "supports_profiles": True}
            return _real_settings(name)

        cookies._get_chromium_based_browser_settings = settings
    _others[config["browser"]] = (config["dir"], config["keyring"])
    # Added to, not replaced: yt-dlp's option checks hold their own reference to these sets.
    cookies.CHROMIUM_BASED_BROWSERS.add(config["browser"])
    cookies.SUPPORTED_BROWSERS.add(config["browser"])


def yt_dlp_args(config):
    """The yt-dlp option that makes downloads use the sign-in, or None when Premium is off."""
    return f"--cookies-from-browser {config['browser']}" if config else None


def _app_data():
    if sys.platform == "darwin":
        return [Path.home() / "Library" / "Application Support"]
    if sys.platform in ("win32", "cygwin"):
        return [Path(os.path.expandvars(v)) for v in ("%LOCALAPPDATA%", "%APPDATA%")]
    return [Path.home() / ".config"]


def find_other(name):
    """A Chromium-based browser's data folder, found by its name, or None."""
    for base in _app_data():
        for folder in (base / name / "User Data", base / name, base / name.lower()):
            if folder.is_dir() and (folder.name == "User Data" or (folder / "Local State").exists()):
                return folder
    return None


def installed():
    """(yt-dlp name, label) for each browser yt-dlp knows that's on this computer."""
    found = []
    for key, label in KNOWN.items():
        if key == "safari":
            present = sys.platform == "darwin"
        elif key == "firefox":
            present = any(Path(d).is_dir() for d in yt_dlp.cookies._firefox_browser_dirs())
        else:
            present = Path(yt_dlp.cookies._get_chromium_based_browser_settings(key)["browser_dir"]).is_dir()
        if present:
            found.append((key, label))
    return found


def signed_in(config):
    """Whether the browser holds a YouTube sign-in. SignInError when it can't be read (a Keychain prompt denied,
    or Safari without Full Disk Access)."""
    register(config)
    try:
        jar = yt_dlp.cookies.extract_cookies_from_browser(config["browser"])
    except Exception as exc:
        raise SignInError(f"Couldn't read the browser's sign-in: {exc}.") from None
    return any(k.domain.endswith("youtube.com") and k.name in SIGN_IN_COOKIES for k in jar)


def _formats(config):
    register(config)
    options = {"quiet": True, "no_warnings": True, "skip_download": True, "format": "bestaudio/best",
               "cookiesfrombrowser": (config["browser"], None, None, None), **get_local_deno_yt_dlp_options()}
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            return ydl.extract_info(PROBE, download=False).get("formats") or []
    except Exception as exc:
        raise SignInError(f"Couldn't check Premium with YouTube: {exc}.") from None


def has_premium(config):
    """Whether YouTube offers this sign-in its Premium audio stream."""
    return any(f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")
               and (f.get("abr") or 0) >= PREMIUM_KBPS for f in _formats(config))


def open_sign_in(config, label):
    """YouTube's sign-in page, in the browser the user chose where possible."""
    if sys.platform == "darwin":
        app = MAC_APPS.get(config["browser"], label)
        if subprocess.run(["open", "-a", app, SIGN_IN_PAGE], capture_output=True).returncode == 0:
            return
    webbrowser.open(SIGN_IN_PAGE)


def _choose(answer, count):
    while True:
        choice = answer("Number: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= count:
            return int(choice)
        print(f"Type a number from 1 to {count}.")


def ask(answer=input):
    """Asks once whether the user has YouTube Premium and sets it up. Returns the browser to read the sign-in
    from, False for no Premium, or None when it couldn't be set up (so it's asked again next time)."""
    reply = answer("Do you have YouTube Premium? It lets downloads come in at 256 kbps instead of 128. [y/N] ")
    if reply.strip().lower() not in ("y", "yes"):
        return False
    browsers = installed()
    print("Which browser are you signed in to YouTube with?")
    for i, (_, label) in enumerate(browsers, 1):
        print(f"  {i}. {label}")
    print(f"  {len(browsers) + 1}. Other (a Chromium-based browser, such as Dia or Arc)")
    n = _choose(answer, len(browsers) + 1)
    if n <= len(browsers):
        key, label = browsers[n - 1]
        config = {"browser": key}
    else:
        label = answer("Its name, as in your Applications: ").strip()
        folder = find_other(label)
        if folder is None:
            typed = answer(f'Couldn\'t find {label}\'s data. Paste the path of its "User Data" folder: ')
            folder = Path(typed.strip().strip("'\"")).expanduser()
            if not folder.is_dir():
                print(f"{folder} isn't a folder. {AGAIN}")
                return None
        config = {"browser": re.sub(r"[^a-z0-9]", "", label.lower()) or "other", "dir": str(folder),
                  "keyring": label}
    try:
        if not signed_in(config):
            open_sign_in(config, label)
            answer(f"Sign in to YouTube in {label}, then press Enter here. ")
            if not signed_in(config):
                print(f"Still not signed in to YouTube in {label}. {AGAIN}")
                return None
        premium = has_premium(config)
    except SignInError as exc:
        print(f"{exc} {AGAIN}")
        return None
    if not premium:
        print("You're signed in, but this account doesn't seem to have Premium, so downloads stay at 128 kbps.")
        return False
    print(f"YouTube Premium is on: downloads use your sign-in from {label}.")
    return config
