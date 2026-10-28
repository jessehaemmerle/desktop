"""User settings shared by all Tenwin processes.

Settings live in ``~/.config/tenwin/settings.json`` as a flat dict with dotted
keys. Every process watches the file and emits ``changed`` with the set of keys
whose value differs, so the settings app only has to write the file.
"""

import json
import logging
import os
import tempfile

from tenwin import paths

log = logging.getLogger(__name__)

ACCENT_COLORS = [
    # The 48 accent colours of the Windows 10 colour picker (public hex values).
    "#FFB900", "#FF8C00", "#F7630C", "#CA5010", "#DA3B01", "#EF6950",
    "#D13438", "#FF4343", "#E74856", "#E81123", "#EA005E", "#C30052",
    "#E3008C", "#BF0077", "#C239B3", "#9A0089", "#0078D7", "#0063B1",
    "#8E8CD8", "#6B69D6", "#8764B8", "#744DA9", "#B146C2", "#881798",
    "#0099BC", "#2D7D9A", "#00B7C3", "#038387", "#00B294", "#018574",
    "#00CC6A", "#10893E", "#7A7574", "#5D5A58", "#68768A", "#515C6B",
    "#567C73", "#486860", "#498205", "#107C10", "#767676", "#4C4A48",
    "#69797E", "#4A5459", "#647C64", "#525E54", "#847545", "#7E735F",
]

DEFAULTS = {
    # Colours ("Farben")
    "appearance.shell_mode": "dark",      # Windows-Modus: dark | light
    "appearance.app_mode": "light",       # App-Modus: dark | light
    "appearance.accent": "#0078D7",
    "appearance.accent_auto": False,
    "appearance.accent_on_surfaces": False,  # Start, Taskleiste, Info-Center
    "appearance.accent_on_titlebars": False,  # Titelleisten und Fensterrahmen
    "appearance.transparency": True,
    "appearance.animations": True,
    "appearance.text_scale": 1.0,
    "appearance.cursor_size": 24,
    # Background
    "background.type": "picture",         # picture | color
    "background.picture": "",             # empty -> default wallpaper
    "background.fit": "fill",             # fill | fit | stretch | tile | center
    "background.color": "#0063B1",
    "lockscreen.picture": "",
    "lockscreen.show_background_on_signin": True,
    # Taskbar
    "taskbar.position": "bottom",         # bottom | top
    "taskbar.small_icons": False,
    "taskbar.search": "box",              # box | icon | hidden
    "taskbar.show_taskview": True,
    "taskbar.tray_show_all": False,
    "taskbar.pinned": [
        "org.tenwin.Explorer.desktop",
        "firefox_firefox.desktop",
        "firefox.desktop",
        "thunderbird.desktop",
    ],
    # Start
    "start.show_most_used": True,
    "start.show_recently_added": True,
    "start.folders": ["documents", "pictures", "settings"],
    "start.tiles": None,                  # None -> default layout
    # Desktop
    "desktop.show_icons": True,
    "desktop.icon_size": "medium",        # large | medium | small
    "desktop.sort": "name",               # name | size | type | modified
    "desktop.show_this_pc": False,
    "desktop.show_trash": True,
    "desktop.show_home": False,
    # Explorer
    "explorer.view": "details",           # xl | large | medium | small | list | details
    "explorer.show_hidden": False,
    "explorer.show_extensions": True,
    "explorer.ribbon_expanded": False,
    "explorer.nav_pane": True,
    "explorer.quick_access": [],
    "explorer.open_this_pc": False,       # False -> open Schnellzugriff
    # Notifications & quick actions
    "notifications.enabled": True,
    "notifications.sounds": True,
    "notifications.focus_assist": False,  # Ruhezeiten
    "nightlight.enabled": False,
    "nightlight.temperature": 4500,
    "quickactions.expanded": False,
    # Power
    "power.lock_after_min": 10,           # 0 = never
    "power.suspend_after_min": 30,        # 0 = never
    "power.lock_on_suspend": True,
    # Input (written to labwc rc.xml / environment)
    "input.keyboard_layouts": "de",
    "input.keyboard_variant": "",
    "input.repeat_rate": 25,
    "input.repeat_delay": 600,
    "input.pointer_speed": 0.0,
    "input.natural_scroll": False,
    "input.tap_to_click": True,
    "input.left_handed": False,
    "input.numlock": True,
    # Region
    "region.language": "auto",            # auto | de | en
    "region.clock_24h": True,
    "region.clock_seconds": False,
    # Desktops
    "desktops.count": 4,
    # Displays: {output name: {"width", "height", "scale", "transform"}}
    "display.outputs": {},
    # Session
    "session.first_run_done": False,
}


def _coerce(key, value):
    """Return ``value`` adjusted to the type of the default, or the default."""
    default = DEFAULTS.get(key)
    if default is None or value is None:
        return value
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        if isinstance(value, str) and value.lower() in ("true", "false", "1", "0", "yes", "no"):
            return value.lower() in ("true", "1", "yes")
        return default
    if isinstance(default, int) and not isinstance(default, bool):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    if isinstance(default, float):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    if isinstance(default, str):
        return value if isinstance(value, str) else default
    if isinstance(default, list):
        return value if isinstance(value, list) else list(default)
    if isinstance(default, dict):
        return value if isinstance(value, dict) else dict(default)
    return value


def load_file(path=None):
    """Read the settings file and merge it over the defaults."""
    path = path or paths.SETTINGS_FILE
    data = dict(DEFAULTS)
    try:
        with open(path, encoding="utf-8") as fh:
            stored = json.load(fh)
        if isinstance(stored, dict):
            for key, value in stored.items():
                data[key] = _coerce(key, value)
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        log.warning("Cannot read %s: %s", path, exc)
    return data


def save_file(data, path=None):
    """Atomically write only the values that differ from the defaults."""
    path = path or paths.SETTINGS_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    diff = {k: v for k, v in data.items() if DEFAULTS.get(k, object()) != v}
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".settings-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(diff, fh, indent=2, sort_keys=True, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class _SettingsBase:
    def __init__(self, path=None):
        self._path = str(path or paths.SETTINGS_FILE)
        self._data = load_file(self._path)

    def __getitem__(self, key):
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self.update({key: value})

    def update(self, values):
        changed = set()
        for key, value in values.items():
            value = _coerce(key, value)
            if self._data.get(key) != value:
                self._data[key] = value
                changed.add(key)
        if changed:
            save_file(self._data, self._path)
            self._emit(changed)
        return changed

    def reset(self, key):
        self.set(key, DEFAULTS[key])

    def reload(self):
        new = load_file(self._path)
        changed = {k for k in set(new) | set(self._data) if new.get(k) != self._data.get(k)}
        self._data = new
        if changed:
            self._emit(changed)
        return changed

    def _emit(self, changed):
        pass


try:
    from gi.repository import Gio, GLib, GObject

    class Settings(_SettingsBase, GObject.Object):
        """Settings with a file monitor and a ``changed(keys)`` signal."""

        __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, (object,))}

        def __init__(self, path=None):
            GObject.Object.__init__(self)
            _SettingsBase.__init__(self, path)
            self._reload_id = 0
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            gfile = Gio.File.new_for_path(self._path)
            self._monitor = gfile.monitor_file(Gio.FileMonitorFlags.WATCH_MOVES, None)
            self._monitor.connect("changed", self._on_file_changed)

        def _on_file_changed(self, *_args):
            # Debounce: editors and os.replace() produce several events.
            if self._reload_id:
                GLib.source_remove(self._reload_id)
            self._reload_id = GLib.timeout_add(120, self._do_reload)

        def _do_reload(self):
            self._reload_id = 0
            self.reload()
            return GLib.SOURCE_REMOVE

        def _emit(self, changed):
            self.emit("changed", frozenset(changed))

except ImportError:  # pragma: no cover - only for environments without PyGObject
    Settings = _SettingsBase


_instance = None


def get_settings():
    """Process-wide shared Settings instance."""
    global _instance
    if _instance is None:
        _instance = Settings()
    return _instance


class State:
    """Small persistent store for non-setting data (usage counts, known apps).

    Several processes (shell, settings) share the file, so every change is a
    read-modify-write of a single key via :meth:`modify`.
    """

    def __init__(self, path=None):
        self._path = str(path or paths.STATE_FILE)
        self.data = self._read()

    def _read(self):
        try:
            with open(self._path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def modify(self, key, func, default=None):
        """Re-read the file, set ``key`` to ``func(old value)`` and save."""
        self.data = self._read()
        self.data[key] = func(self.data.get(key, default))
        try:
            self._write()
        except OSError as exc:
            log.warning("cannot save %s: %s", self._path, exc)
        return self.data[key]

    def _write(self):
        directory = os.path.dirname(self._path)
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".state-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False)
            os.replace(tmp, self._path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
