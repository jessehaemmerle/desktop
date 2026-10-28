"""Personalization > Fonts: installed font families, installing and removing user fonts."""

import os
import shutil
import subprocess

FONT_EXTENSIONS = (".ttf", ".otf", ".ttc", ".otc", ".woff", ".woff2", ".pfb")


def user_font_dir():
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(data_home, "fonts")


def families():
    """Sorted font family names (via Pango)."""
    import gi
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import PangoCairo
    names = {f.get_name() for f in PangoCairo.FontMap.get_default().list_families()}
    return sorted(names, key=str.casefold)


def filter_families(names, query):
    q = query.casefold().strip()
    return [n for n in names if q in n.casefold()] if q else list(names)


def is_font_file(path):
    return path.lower().endswith(FONT_EXTENSIONS)


def install(files, target=None):
    """Copy font files into the user's font folder. Returns (installed, errors)."""
    target = target or user_font_dir()
    os.makedirs(target, exist_ok=True)
    installed, errors = [], []
    for path in files:
        if not is_font_file(path):
            errors.append(os.path.basename(path))
            continue
        try:
            shutil.copy2(path, os.path.join(target, os.path.basename(path)))
            installed.append(os.path.basename(path))
        except OSError:
            errors.append(os.path.basename(path))
    if installed:
        refresh_cache(target)
    return installed, errors


def user_fonts(target=None):
    target = target or user_font_dir()
    try:
        return sorted(f for f in os.listdir(target) if is_font_file(f))
    except OSError:
        return []


def remove(name, target=None):
    target = target or user_font_dir()
    path = os.path.join(target, os.path.basename(name))
    try:
        os.unlink(path)
    except OSError:
        return False
    refresh_cache(target)
    return True


def refresh_cache(target):
    if shutil.which("fc-cache"):
        subprocess.Popen(["fc-cache", "-f", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
