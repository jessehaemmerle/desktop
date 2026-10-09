"""Die Insel – schwebendes Dock mit den Apps der aktiven Facette und einer Medien-Kapsel."""

from __future__ import annotations

from gi.repository import GLib, Gtk

from ..core import config as cfg
from . import util


class DockItem(Gtk.Box):
    def __init__(self, dock, key: str, app=None, window=None, size: int = 44):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.dock, self.key, self.app, self.window = dock, key, app, window
        self.button = Gtk.Button()
        util.add_class(self.button, "dock-item")
        icon = app.icon if app is not None else (window.app_id if window else None)
        self.image = util.icon_image(icon, size)
        self.button.add(self.image)
        self.indicator = Gtk.Box()
        self.indicator.set_halign(Gtk.Align.CENTER)
        util.add_class(self.indicator, "dock-indicator")
        self.pack_start(self.button, False, False, 0)
        self.pack_start(self.indicator, False, False, 0)
        self.button.connect("button-release-event", self._released)

    def set_state(self, windows: list) -> None:
        self.windows = windows
        util.toggle_class(self.indicator, "running", bool(windows))
        util.toggle_class(self.indicator, "active", any(w.activated for w in windows))
        name = self.app.name if self.app else (self.window.title if self.window else "")
        extra = f" · {len(windows)} Fenster" if len(windows) > 1 else ""
        hint = "" if windows else "\nRechtsklick: an Facette anheften/lösen" if self.app else ""
        self.button.set_tooltip_text(f"{name}{extra}{hint}")

    def _released(self, _button, event) -> bool:
        if event.button == 1:
            self.dock.primary(self)
        elif event.button == 2 and self.app is not None:
            self.dock.launch(self)
        elif event.button == 3:
            self.dock.toggle_pin(self)
        return True


class Dock:
    def __init__(self, app, hub, services):
        self.app, self.hub, self.services = app, hub, services
        self.window = util.layer_window(app, "dock", layer="top", anchors=("bottom",),
                                        margins={"bottom": 0}, exclusive="auto")
        outer = Gtk.Box()
        outer.set_margin_start(16)
        outer.set_margin_end(16)
        outer.set_margin_top(12)
        outer.set_margin_bottom(10)
        self.island = util.add_class(Gtk.Box(spacing=2), "island", "dock")
        outer.pack_start(self.island, False, False, 0)
        self.window.add(outer)

        size = hub.config["appearance"]["dock_icon_size"]
        self.kompass = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        button = Gtk.Button()
        util.add_class(button, "dock-item", "kompass-button")
        button.add(util.icon_image("system-search-symbolic", max(18, int(size * 0.5))))
        button.set_size_request(size + 8, size + 8)
        button.set_tooltip_text("Kompass – Apps, Dateien, Rechnen, Befehle (Super+Leertaste)")
        button.connect("clicked", lambda *_: app.activate_action("kompass", None))
        self.kompass.pack_start(button, False, False, 0)
        self.kompass.pack_start(util.add_class(Gtk.Box(), "dock-indicator"), False, False, 0)
        self.items_box = Gtk.Box(spacing=2)
        self.media_revealer = Gtk.Revealer()
        self.media_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_LEFT)
        self.media_revealer.set_transition_duration(260)
        self.media_revealer.add(self._build_media())
        self.island.pack_start(self.kompass, False, False, 2)
        self.island.pack_start(self.items_box, False, False, 0)
        self.island.pack_start(self.media_revealer, False, False, 0)

        self._signature: tuple = ()
        self._items: list[DockItem] = []
        self._pending = 0
        for source, signal in ((hub.windows, "changed"), (hub, "facet-changed"), (hub, "config-changed"),
                               (hub.apps, "changed")):
            source.connect(signal, lambda *_: self.queue_refresh())
        services.media.connect("changed", lambda *_: self.update_media())
        self.window.show_all()
        self.refresh()
        self.update_media()

    # ------------------------------------------------------------ Aufbau
    def _build_media(self) -> Gtk.Widget:
        box = util.add_class(Gtk.Box(spacing=8), "media-chip")
        box.set_margin_start(6)
        box.set_valign(Gtk.Align.CENTER)
        self.media_art = util.icon_image("audio-x-generic-symbolic", 32)
        box.pack_start(self.media_art, False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        text.set_valign(Gtk.Align.CENTER)
        self.media_title = util.label("", "media-title", ellipsize=True)
        self.media_artist = util.label("", "media-artist", ellipsize=True)
        self.media_title.set_max_width_chars(18)
        self.media_artist.set_max_width_chars(18)
        text.pack_start(self.media_title, False, False, 0)
        text.pack_start(self.media_artist, False, False, 0)
        box.pack_start(text, False, False, 0)
        for icon, callback in (("media-skip-backward-symbolic", lambda: self.services.media.previous()),
                               ("media-playback-start-symbolic", lambda: self.services.media.play_pause()),
                               ("media-skip-forward-symbolic", lambda: self.services.media.next())):
            button = Gtk.Button()
            button.add(util.icon_image(icon, 16))
            button.set_valign(Gtk.Align.CENTER)
            button.connect("clicked", lambda _b, cb=callback: cb())
            box.pack_start(button, False, False, 0)
            if "start" in icon:
                self.media_play = button
        return box

    def queue_refresh(self) -> None:
        if not self._pending:
            self._pending = GLib.timeout_add(60, self._do_refresh)

    def _do_refresh(self) -> bool:
        self._pending = 0
        self.refresh()
        return False

    def _entries(self) -> list[tuple[str, object, object]]:
        """(key, app, window) – erst angeheftete, dann laufende Apps der Facette."""
        entries, seen = [], set()
        for pin in self.hub.facet.get("pinned", []):
            app = self.hub.apps.resolve_pin(pin)
            if app is not None and app.id not in seen:
                seen.add(app.id)
                entries.append((f"app:{app.id}", app, None))
        running = []
        for window in self.hub.windows.in_facet():
            app = window.extra.get("app")
            if app is not None:
                app = self.hub.apps.get(app.id) or app
                if app.id not in seen:
                    seen.add(app.id)
                    running.append((f"app:{app.id}", app, None))
            elif window.parent == 0:
                running.append((f"win:{window.handle}", None, window))
        if running and entries:
            entries.append(("sep", None, None))
        return entries + running

    def refresh(self) -> None:
        entries = self._entries()
        signature = tuple(key for key, _a, _w in entries) + (self.hub.config["appearance"]["dock_icon_size"],)
        if signature != self._signature:
            self._signature = signature
            util.clear(self.items_box)
            self._items = []
            size = self.hub.config["appearance"]["dock_icon_size"]
            for key, app, window in entries:
                if key == "sep":
                    sep = util.add_class(Gtk.Box(), "dock-sep")
                    self.items_box.pack_start(sep, False, False, 0)
                    continue
                item = DockItem(self, key, app, window, size)
                self._items.append(item)
                self.items_box.pack_start(item, False, False, 0)
            self.items_box.show_all()
            self.window.resize(1, 1)
        for item in self._items:
            if item.app is not None:
                item.set_state(self.hub.windows.for_app(item.app))
            else:
                item.set_state([item.window])

    def update_media(self) -> None:
        info = self.services.media.info()
        self.media_revealer.set_reveal_child(info is not None)
        if info is None:
            GLib.timeout_add(300, lambda: self.window.resize(1, 1) and False)
            return
        self.media_title.set_text(info["title"])
        self.media_artist.set_text(info["artist"] or info["player"].capitalize())
        util.set_icon(self.media_art, info["art"] or "audio-x-generic-symbolic", 32, "audio-x-generic-symbolic")
        icon = "media-playback-pause-symbolic" if info["playing"] else "media-playback-start-symbolic"
        util.set_icon(self.media_play.get_child(), icon, 16)

    # ------------------------------------------------------------ Aktionen
    def primary(self, item: DockItem) -> None:
        windows = getattr(item, "windows", [])
        if not windows:
            self.launch(item)
            return
        active = next((i for i, w in enumerate(windows) if w.activated), None)
        if active is None:
            self.hub.windows.activate(windows[0])
        elif len(windows) == 1:
            self.hub.windows.minimize(windows[0])
        else:
            self.hub.windows.activate(windows[(active + 1) % len(windows)])

    def launch(self, item: DockItem) -> None:
        if item.app is None:
            return
        util.add_class(item.button, "launching")
        GLib.timeout_add(220, lambda: util.toggle_class(item.button, "launching", False) or False)
        if item.app.launch():
            self.hub.frecency.record(f"app:{item.app.id}")

    def toggle_pin(self, item: DockItem) -> None:
        if item.app is None:
            return
        facet = self.hub.facet
        pins = facet.setdefault("pinned", [])
        resolved = [p for p in pins if self.hub.apps.resolve_pin(p) is item.app]
        if resolved:
            for pin in resolved:
                pins.remove(pin)
            message = f"{item.app.name} von „{facet['name']}“ gelöst"
        else:
            pins.append(item.app.id)
            message = f"{item.app.name} an „{facet['name']}“ angeheftet"
        cfg.save(self.hub.config)
        self.hub.emit("toast", "view-pin-symbolic", message)
        self.queue_refresh()
