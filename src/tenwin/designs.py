"""Personalization > Themes: background, colours and mouse cursor saved together."""

import glob
import os

from tenwin import paths
from tenwin.config import get_settings
from tenwin.i18n import N_, _

THEME_KEYS = [
    "background.type", "background.picture", "background.color", "background.fit",
    "appearance.accent", "appearance.accent_mode", "appearance.shell_mode", "appearance.app_mode",
    "appearance.transparency", "appearance.cursor_theme", "appearance.cursor_size",
]


def builtin():
    """The themes Tenwin ships (picture paths resolved at run time)."""
    wall = paths.WALLPAPER_DIR
    return [
        {"name": N_("Tenwin"), "builtin": True, "values": {
            "background.type": "picture", "background.picture": str(wall / "tenwin-hero.svg"),
            "appearance.accent_mode": "manual", "appearance.accent": "#0078D7",
            "appearance.shell_mode": "dark", "appearance.app_mode": "light"}},
        {"name": N_("Tenwin (dark)"), "builtin": True, "values": {
            "background.type": "picture", "background.picture": str(wall / "tenwin-dark.svg"),
            "appearance.accent_mode": "manual", "appearance.accent": "#0063B1",
            "appearance.shell_mode": "dark", "appearance.app_mode": "dark"}},
        {"name": N_("Dusk"), "builtin": True, "values": {
            "background.type": "picture", "background.picture": str(wall / "tenwin-dusk.svg"),
            "appearance.accent_mode": "wallpaper",
            "appearance.shell_mode": "dark", "appearance.app_mode": "light"}},
        {"name": N_("Lake"), "builtin": True, "values": {
            "background.type": "picture", "background.picture": str(wall / "tenwin-lake.svg"),
            "appearance.accent_mode": "wallpaper",
            "appearance.shell_mode": "light", "appearance.app_mode": "light"}},
    ]


def saved():
    return [t for t in get_settings()["appearance.themes"]
            if isinstance(t, dict) and t.get("name") and isinstance(t.get("values"), dict)]


def all_themes():
    return builtin() + saved()


def display_name(theme):
    return _(theme["name"]) if theme.get("builtin") else theme["name"]


def current_values(settings=None):
    settings = settings or get_settings()
    return {key: settings[key] for key in THEME_KEYS}


def _normalized(key, value):
    if key == "background.picture" and not value:
        return paths.default_wallpaper()
    return value


def is_current(theme, settings=None):
    settings = settings or get_settings()
    return all(_normalized(k, settings[k]) == _normalized(k, v)
               for k, v in theme["values"].items() if k in THEME_KEYS)


def apply(theme):
    values = {k: v for k, v in theme["values"].items() if k in THEME_KEYS}
    get_settings().update(values)


def save_current(name):
    name = name.strip()
    if not name:
        return False
    themes = [t for t in saved() if t["name"] != name]
    themes.append({"name": name, "values": current_values()})
    get_settings().set("appearance.themes", themes)
    return True


def delete(name):
    get_settings().set("appearance.themes", [t for t in saved() if t["name"] != name])


def cursor_themes():
    """Installed X cursor themes (directories with a ``cursors`` folder)."""
    roots = [os.path.expanduser("~/.icons"), os.path.expanduser("~/.local/share/icons"),
             "/usr/share/icons", "/usr/local/share/icons"]
    names = set()
    for root in roots:
        for path in glob.glob(os.path.join(root, "*", "cursors")):
            names.add(os.path.basename(os.path.dirname(path)))
    return sorted(names, key=str.casefold)
