"""Laden, Zusammenführen und Speichern der Prisma-Konfiguration (JSON)."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

# Ein Pin darf mehrere Alternativen enthalten ("a|b|c") – die erste installierte gewinnt.
DEFAULT_CONFIG: dict = {
    "facets": [
        {
            "id": "arbeit",
            "name": "Arbeit",
            "icon": "x-office-document-symbolic",
            "color": "#4f8cff",
            "notifications": "important",
            "wallpaper": None,
            "pinned": [
                "firefox_firefox|firefox|org.mozilla.firefox|chromium_chromium|chromium",
                "org.gnome.Nautilus|nemo|thunar|pcmanfm-qt|pcmanfm",
                "thunderbird_thunderbird|thunderbird|org.gnome.Evolution",
                "libreoffice-writer|libreoffice-startcenter",
                "org.gnome.TextEditor|org.gnome.gedit|mousepad|org.xfce.mousepad",
                "org.gnome.Terminal|org.gnome.Ptyxis|org.gnome.Console|org.codeberg.dnkl.foot|foot|kitty|Alacritty|xfce4-terminal",
            ],
        },
        {
            "id": "kreativ",
            "name": "Kreativ",
            "icon": "applications-graphics-symbolic",
            "color": "#b26bff",
            "notifications": "all",
            "wallpaper": None,
            "pinned": [
                "org.gimp.GIMP|gimp",
                "org.inkscape.Inkscape|inkscape",
                "org.kde.kdenlive|kdenlive",
                "org.gnome.Nautilus|nemo|thunar|pcmanfm",
                "org.gnome.Terminal|org.gnome.Ptyxis|org.gnome.Console|org.codeberg.dnkl.foot|foot|kitty",
            ],
        },
        {
            "id": "freizeit",
            "name": "Freizeit",
            "icon": "face-smile-symbolic",
            "color": "#ff8a4c",
            "notifications": "all",
            "wallpaper": None,
            "pinned": [
                "firefox_firefox|firefox|chromium_chromium|chromium",
                "spotify_spotify|spotify|org.gnome.Rhythmbox3|rhythmbox",
                "vlc|org.gnome.Totem|mpv",
                "steam|org.gnome.Shotwell|org.gnome.Loupe|eog",
            ],
        },
    ],
    "rules": [
        {"facet": "arbeit", "days": [0, 1, 2, 3, 4], "from": "08:00", "to": "17:00"},
    ],
    "auto_switch": False,
    "focus": {"work_minutes": 25, "break_minutes": 5, "allow_apps": []},
    "appearance": {
        "mode": "auto",  # auto | light | dark
        "light_from": "07:00",
        "dark_from": "19:00",
        "dock_icon_size": 44,
        "clock_seconds": False,
        "greeting": True,
        "follow_facet_color": True,
        "accent": "#4f8cff",
    },
    "kompass": {
        "web_search": "https://duckduckgo.com/?q={query}",
        "index_files": True,
    },
    "terminal": "",
    "user_name": "",
}

NOTIFICATION_POLICIES = ("all", "important", "silent")


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "prisma"


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(base) / "prisma"


def config_path() -> Path:
    return config_dir() / "config.json"


def deep_merge(base: dict, override: dict) -> dict:
    """Mischt ``override`` rekursiv in eine Kopie von ``base``.

    Listen werden vollständig ersetzt (z. B. Facetten), nicht zusammengeführt.
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def normalize(cfg: dict) -> dict:
    """Repariert ungültige Werte, damit die Shell nie an einer kaputten Datei scheitert."""
    facets = [f for f in cfg.get("facets") or [] if isinstance(f, dict)]
    if not facets:
        facets = copy.deepcopy(DEFAULT_CONFIG["facets"])
    seen: set[str] = set()
    for index, facet in enumerate(facets):
        fid = str(facet.get("id") or facet.get("name") or f"facette-{index + 1}").strip().lower()
        fid = "-".join(fid.split()) or f"facette-{index + 1}"
        while fid in seen:
            fid += "-2"
        seen.add(fid)
        facet["id"] = fid
        facet.setdefault("name", fid.capitalize())
        facet.setdefault("icon", "view-grid-symbolic")
        if not _is_hex_color(facet.get("color")):
            facet["color"] = "#4f8cff"
        if facet.get("notifications") not in NOTIFICATION_POLICIES:
            facet["notifications"] = "all"
        if not isinstance(facet.get("pinned"), list):
            facet["pinned"] = []
        facet.setdefault("wallpaper", None)
    cfg["facets"] = facets
    if not isinstance(cfg.get("rules"), list):
        cfg["rules"] = []
    app = cfg.setdefault("appearance", {})
    if app.get("mode") not in ("auto", "light", "dark"):
        app["mode"] = "auto"
    try:
        app["dock_icon_size"] = max(24, min(96, int(app.get("dock_icon_size", 44))))
    except (TypeError, ValueError):
        app["dock_icon_size"] = 44
    focus = cfg.setdefault("focus", {})
    for key, default in (("work_minutes", 25), ("break_minutes", 5)):
        try:
            focus[key] = max(1, min(240, int(focus.get(key, default))))
        except (TypeError, ValueError):
            focus[key] = default
    return cfg


def _is_hex_color(value) -> bool:
    if not isinstance(value, str) or not value.startswith("#") or len(value) not in (4, 7):
        return False
    try:
        int(value[1:], 16)
    except ValueError:
        return False
    return True


def load(path: Path | None = None) -> dict:
    path = path or config_path()
    user: dict = {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            user = data
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError) as exc:
        print(f"prisma: Konfiguration {path} ungültig ({exc}) – nutze Standardwerte")
    return normalize(deep_merge(DEFAULT_CONFIG, user))


def save(cfg: dict, path: Path | None = None) -> None:
    """Schreibt atomar, damit die Shell (die die Datei beobachtet) nie halbe Dateien liest."""
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def find_facet(cfg: dict, key: str | int) -> dict | None:
    """Sucht eine Facette per ID, Name (ohne Groß/Klein) oder 1-basiertem Index."""
    facets = cfg["facets"]
    if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
        index = int(key) - 1
        return facets[index] if 0 <= index < len(facets) else None
    needle = str(key).strip().lower()
    for facet in facets:
        if facet["id"] == needle or facet["name"].lower() == needle:
            return facet
    for facet in facets:
        if facet["name"].lower().startswith(needle) and needle:
            return facet
    return None
