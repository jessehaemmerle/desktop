"""Index der installierten Anwendungen (.desktop) inkl. Start und Zuordnung zu Fenstern."""

from __future__ import annotations

from gi.repository import Gdk, Gio, GObject

from ..core.appmatch import AppRecord, match_app, resolve_pin


def _strip(desktop_id: str) -> str:
    return desktop_id[:-8] if desktop_id.endswith(".desktop") else desktop_id


class App:
    def __init__(self, info: Gio.DesktopAppInfo):
        self.info = info
        self.id = _strip(info.get_id() or "")
        self.name = info.get_display_name() or info.get_name() or self.id
        self.generic = info.get_generic_name() or ""
        self.description = info.get_description() or ""
        self.keywords = list(info.get_keywords() or [])
        self.executable = info.get_executable() or ""
        self.wm_class = info.get_startup_wm_class() or ""
        self.icon = info.get_icon()
        self.record = AppRecord(self.id, self.name, self.executable, self.wm_class, self.keywords)

    def launch(self, uris: list[str] | None = None) -> bool:
        ctx = Gdk.Display.get_default().get_app_launch_context()
        try:
            if uris:
                return self.info.launch_uris(uris, ctx)
            return self.info.launch([], ctx)
        except Exception as exc:  # GLib.Error u. a.
            print(f"prisma: Start von {self.id} fehlgeschlagen: {exc}")
            return False

    def actions(self) -> list[tuple[str, str]]:
        return [(a, self.info.get_action_name(a)) for a in self.info.list_actions()]

    def launch_action(self, action: str) -> None:
        self.info.launch_action(action, Gdk.Display.get_default().get_app_launch_context())


class AppIndex(GObject.Object):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        super().__init__()
        self.apps: dict[str, App] = {}
        self._match_cache: dict[str, App | None] = {}
        self._monitor = Gio.AppInfoMonitor.get()
        self._monitor.connect("changed", lambda *_: self.reload())
        self.reload()

    def reload(self) -> None:
        apps = {}
        for info in Gio.AppInfo.get_all():
            if not isinstance(info, Gio.DesktopAppInfo) or not info.get_id():
                continue
            if info.get_nodisplay() or info.get_is_hidden():
                continue
            app = App(info)
            apps[app.id.lower()] = app
        self.apps = apps
        self._match_cache.clear()
        self.emit("changed")

    def get(self, desktop_id: str) -> App | None:
        app = self.apps.get(_strip(desktop_id).lower())
        if app is None:
            # NoDisplay-Einträge (z. B. Einstellungsdialoge) trotzdem auflösbar machen
            try:
                info = Gio.DesktopAppInfo.new(_strip(desktop_id) + ".desktop")
            except TypeError:
                info = None
            if info is not None:
                app = App(info)
        return app

    def resolve_pin(self, pin: str) -> App | None:
        found = resolve_pin(pin, set(self.apps))
        return self.apps.get(found) if found else None

    def for_app_id(self, app_id: str) -> App | None:
        if app_id in self._match_cache:
            return self._match_cache[app_id]
        record = match_app(app_id, [a.record for a in self.apps.values()])
        app = self.apps.get(record.desktop_id.lower()) if record else None
        self._match_cache[app_id] = app
        return app
