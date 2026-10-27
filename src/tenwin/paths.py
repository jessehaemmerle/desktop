"""Locations of data files, helpers and per-user files.

Works both from the source tree (``src/tenwin`` next to ``data/``) and from an
installed system (``/usr/share/tenwin/lib/tenwin``).
"""

import os
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent
_SRC_ROOT = _PKG_DIR.parent.parent

if (_SRC_ROOT / "data" / "labwc").is_dir():
    # Running from a checkout.
    DEV_MODE = True
    DATA_DIR = _SRC_ROOT / "data"
    LIBEXEC_DIR = _SRC_ROOT / "build" / "helpers"
    LOCALE_DIR = _SRC_ROOT / "build" / "locale"
    ICON_DIR = DATA_DIR / "icons"
    WALLPAPER_DIR = DATA_DIR / "wallpapers"
    BIN_DIR = _SRC_ROOT / "bin"
else:
    DEV_MODE = False
    DATA_DIR = Path(os.environ.get("TENWIN_DATA_DIR", "/usr/share/tenwin"))
    LIBEXEC_DIR = Path(os.environ.get("TENWIN_LIBEXEC_DIR", "/usr/libexec/tenwin"))
    LOCALE_DIR = Path("/usr/share/locale")
    ICON_DIR = Path("/usr/share/icons")
    WALLPAPER_DIR = Path("/usr/share/backgrounds/tenwin")
    BIN_DIR = Path("/usr/bin")


def _xdg(var, fallback):
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / fallback


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "tenwin"
STATE_DIR = _xdg("XDG_STATE_HOME", ".local/state") / "tenwin"
CACHE_DIR = _xdg("XDG_CACHE_HOME", ".cache") / "tenwin"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
STATE_FILE = STATE_DIR / "state.json"
LABWC_CONFIG_DIR = CONFIG_DIR / "labwc"
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "tenwin"


def helper(name):
    """Path of a compiled helper binary (tenwin-toplevel, tenwin-lock)."""
    return str(LIBEXEC_DIR / name)


def binary(name):
    """Path of a tenwin-* launcher."""
    for directory in (BIN_DIR, LIBEXEC_DIR):
        path = directory / name
        if path.exists():
            return str(path)
    return name


def default_wallpaper():
    return str(WALLPAPER_DIR / "tenwin-hero.svg")


def xdg_user_dir(kind):
    """Resolve an XDG user directory such as DOCUMENTS or PICTURES."""
    from gi.repository import GLib

    mapping = {
        "DESKTOP": GLib.UserDirectory.DIRECTORY_DESKTOP,
        "DOCUMENTS": GLib.UserDirectory.DIRECTORY_DOCUMENTS,
        "DOWNLOAD": GLib.UserDirectory.DIRECTORY_DOWNLOAD,
        "MUSIC": GLib.UserDirectory.DIRECTORY_MUSIC,
        "PICTURES": GLib.UserDirectory.DIRECTORY_PICTURES,
        "VIDEOS": GLib.UserDirectory.DIRECTORY_VIDEOS,
    }
    path = GLib.get_user_special_dir(mapping[kind])
    if not path:
        fallback = {"DESKTOP": "Desktop", "DOCUMENTS": "Documents",
                    "DOWNLOAD": "Downloads", "MUSIC": "Music",
                    "PICTURES": "Pictures", "VIDEOS": "Videos"}[kind]
        path = str(Path.home() / fallback)
    return path
