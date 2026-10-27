"""Installed applications: listing, matching windows to apps, launching."""

import locale
import logging
import os
import time
import unicodedata

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib, GObject

from tenwin.config import State, get_settings

log = logging.getLogger(__name__)

RECENT_SECONDS = 7 * 24 * 3600


def sort_key(text):
    try:
        return locale.strxfrm(text.casefold())
    except Exception:  # strxfrm fails for some locales/characters
        return text.casefold()


def first_letter(name):
    """Group letter for the Start menu: A-Z, or '#' for digits/symbols."""
    if not name:
        return "#"
    char = unicodedata.normalize("NFKD", name[0])[0].upper()
    return char if "A" <= char <= "Z" else "#"


def _strip(app_id):
    return app_id[:-8] if app_id.endswith(".desktop") else app_id


class AppRegistry(GObject.Object):
    """Keeps the list of visible desktop applications up to date."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        super().__init__()
        self.state = State()
        self.apps = []
        self._by_id = {}
        self._wmclass = {}
        self._match_cache = {}
        self._monitor = Gio.AppInfoMonitor.get()
        self._monitor.connect("changed", lambda *_: GLib.timeout_add(500, self._reload_once))
        self._reload_pending = False
        self.reload()

    def _reload_once(self):
        self.reload()
        self.emit("changed")
        return GLib.SOURCE_REMOVE

    def reload(self):
        apps = []
        for info in Gio.AppInfo.get_all():
            if isinstance(info, Gio.DesktopAppInfo) and info.should_show():
                apps.append(info)
        apps.sort(key=lambda a: sort_key(a.get_display_name() or ""))
        self.apps = apps
        self._by_id = {a.get_id(): a for a in apps}
        self._wmclass = {}
        for info in Gio.AppInfo.get_all():
            if isinstance(info, Gio.DesktopAppInfo):
                wmclass = info.get_startup_wm_class()
                if wmclass:
                    self._wmclass.setdefault(wmclass.casefold(), info)
        self._match_cache = {}
        self._update_known()

    def _update_known(self):
        known = self.state.data.setdefault("known_apps", {})
        now = int(time.time())
        first_run = not known
        changed = False
        for app in self.apps:
            if app.get_id() not in known:
                known[app.get_id()] = 0 if first_run else now
                changed = True
        if changed:
            try:
                self.state.save()
            except OSError as exc:
                log.warning("cannot save state: %s", exc)

    # -- lookup ----------------------------------------------------------

    def get(self, app_id):
        if not app_id:
            return None
        info = self._by_id.get(app_id)
        if info is None:
            try:
                info = Gio.DesktopAppInfo.new(app_id)
            except TypeError:
                info = None
        return info

    def for_window(self, app_id):
        """Best desktop entry for a window's app_id (Wayland) or WM_CLASS."""
        if not app_id:
            return None
        if app_id in self._match_cache:
            return self._match_cache[app_id]
        info = self._match(app_id)
        self._match_cache[app_id] = info
        return info

    def _match(self, app_id):
        candidates = [app_id, app_id.casefold()]
        if "." in app_id:
            candidates.append(app_id.rsplit(".", 1)[-1].casefold())
        candidates.append(app_id.replace(" ", "-").casefold())
        for cand in candidates:
            info = self.get(cand + ".desktop")
            if info is not None:
                return info
        info = self._wmclass.get(app_id.casefold())
        if info is not None:
            return info
        # Snap packages: firefox -> firefox_firefox.desktop
        info = self.get("%s_%s.desktop" % (app_id.casefold(), app_id.casefold()))
        if info is not None:
            return info
        for app in self.apps:
            executable = os.path.basename(app.get_executable() or "")
            if executable and executable.casefold() == app_id.casefold():
                return app
        try:
            results = Gio.DesktopAppInfo.search(app_id)
        except Exception:
            results = []
        for group in results:
            for desktop_id in group:
                info = self.get(desktop_id)
                if info is not None and info.should_show():
                    return info
        return None

    # -- usage -------------------------------------------------------------

    def recently_added(self, limit=3):
        known = self.state.data.get("known_apps", {})
        now = time.time()
        recent = [(known.get(a.get_id(), 0), a) for a in self.apps]
        recent = [(t, a) for t, a in recent if t and now - t < RECENT_SECONDS]
        recent.sort(key=lambda item: -item[0])
        return [a for _t, a in recent[:limit]]

    def most_used(self, limit=6):
        usage = self.state.data.get("usage", {})
        ranked = sorted(((n, i) for i, n in usage.items() if i in self._by_id), reverse=True)
        return [self._by_id[i] for _n, i in ranked[:limit]]

    def record_use(self, info):
        usage = self.state.data.setdefault("usage", {})
        usage[info.get_id()] = usage.get(info.get_id(), 0) + 1
        try:
            self.state.save()
        except OSError:
            pass

    def launch(self, info, uris=None, action=None):
        if info is None:
            return False
        try:
            from gi.repository import Gdk
            display = Gdk.Display.get_default()
            ctx = display.get_app_launch_context() if display else None
        except Exception:
            ctx = None
        try:
            if action:
                info.launch_action(action, ctx)
            elif uris:
                info.launch_uris(uris, ctx)
            else:
                info.launch([], ctx)
        except GLib.Error as exc:
            log.warning("cannot launch %s: %s", info.get_id(), exc)
            return False
        self.record_use(info)
        return True

    # -- pinning -------------------------------------------------------------

    def pinned_taskbar(self):
        result = []
        seen = set()
        for desktop_id in get_settings()["taskbar.pinned"]:
            info = self.get(desktop_id)
            if info is not None and info.get_id() not in seen:
                seen.add(info.get_id())
                result.append(info)
        return result

    def is_pinned(self, info):
        return info is not None and info.get_id() in get_settings()["taskbar.pinned"]

    def set_pinned(self, info, pinned):
        settings = get_settings()
        current = [p for p in settings["taskbar.pinned"] if self.get(p) is not None or p == info.get_id()]
        if pinned and info.get_id() not in current:
            current.append(info.get_id())
        elif not pinned:
            current = [p for p in current if p != info.get_id()]
        settings.set("taskbar.pinned", current)


_registry = None


def get_registry():
    global _registry
    if _registry is None:
        _registry = AppRegistry()
    return _registry
