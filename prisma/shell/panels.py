"""Schnelleinstellungen (rechts) und Tagesüberblick (Mitte)."""

from __future__ import annotations

from datetime import datetime

from gi.repository import GLib, Gtk

from ..core import colors, schedule
from . import util
from .dates import long_date
from .notify_ui import NotificationCard
from .overlay import Overlay


class Tile(Gtk.Button):
    def __init__(self, icon: str, title: str, callback):
        super().__init__()
        util.add_class(self, "tile")
        box = Gtk.Box(spacing=10)
        self.image = util.icon_image(icon, 18)
        box.pack_start(self.image, False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        text.set_valign(Gtk.Align.CENTER)
        self.title = util.label(title, "tile-title", ellipsize=True)
        self.sub = util.label("", "tile-sub", ellipsize=True)
        text.pack_start(self.title, False, False, 0)
        text.pack_start(self.sub, False, False, 0)
        box.pack_start(text, True, True, 0)
        self.add(box)
        self.connect("clicked", lambda *_: callback())

    def update(self, on: bool, sub: str = "", icon: str | None = None) -> None:
        util.toggle_class(self, "on", on)
        self.sub.set_text(sub)
        if icon:
            util.set_icon(self.image, icon, 18)


class SliderRow(Gtk.Box):
    def __init__(self, icon: str, on_change, on_icon=None):
        super().__init__(spacing=8)
        self._updating = False
        self.button = Gtk.Button()
        util.add_class(self.button, "round-button")
        self.image = util.icon_image(icon, 16)
        self.button.add(self.image)
        if on_icon:
            self.button.connect("clicked", lambda *_: on_icon())
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.scale.set_draw_value(False)
        self.scale.connect("value-changed", lambda s: None if self._updating else on_change(s.get_value() / 100))
        self.value = util.label("", "osd-value", xalign=1.0)
        self.pack_start(self.button, False, False, 0)
        self.pack_start(self.scale, True, True, 0)
        self.pack_start(self.value, False, False, 0)

    def set(self, fraction: float, icon: str | None = None) -> None:
        self._updating = True
        self.scale.set_value(fraction * 100)
        self._updating = False
        self.value.set_text(f"{round(fraction * 100)} %")
        if icon:
            util.set_icon(self.image, icon, 16)


class QuickSettings(Overlay):
    def __init__(self, app, hub, services):
        super().__init__(app, "quicksettings", halign=Gtk.Align.END, valign=Gtk.Align.START,
                         margins={"end": 8, "top": 4})
        self.hub, self.services = hub, services
        util.add_class(self.card, "panel")
        card = self.card

        # Kopfzeile
        head = Gtk.Box(spacing=10)
        head.pack_start(util.icon_image("avatar-default-symbolic", 34), False, False, 0)
        who = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        who.set_valign(Gtk.Align.CENTER)
        who.pack_start(util.label(hub.user_name() or "Benutzer", "tile-title"), False, False, 0)
        self.facet_label = util.label("", "tile-sub")
        who.pack_start(self.facet_label, False, False, 0)
        head.pack_start(who, True, True, 0)
        for icon, tip, callback in (
            ("preferences-system-symbolic", "Prisma-Einstellungen", lambda: (self.hide(), util.spawn(util.prisma_command("prisma.settings.app")))),
            ("system-lock-screen-symbolic", "Sperren", lambda: (self.hide(), app.activate_action("lock", None))),
            ("system-shutdown-symbolic", "Ein/Aus", lambda: self.power.set_reveal_child(not self.power.get_reveal_child())),
        ):
            button = Gtk.Button()
            util.add_class(button, "round-button")
            button.set_tooltip_text(tip)
            button.add(util.icon_image(icon, 16))
            button.set_valign(Gtk.Align.CENTER)
            button.connect("clicked", lambda _b, cb=callback: cb())
            head.pack_start(button, False, False, 0)
        card.pack_start(head, False, False, 0)

        self.power = Gtk.Revealer()
        power_box = Gtk.Box(spacing=6, homogeneous=True)
        power_box.set_margin_top(10)
        for icon, title, action in (("system-log-out-symbolic", "Abmelden", "logout"),
                                    ("media-playback-pause-symbolic", "Bereitschaft", "suspend"),
                                    ("system-reboot-symbolic", "Neustart", "reboot"),
                                    ("system-shutdown-symbolic", "Aus", "poweroff")):
            button = Gtk.Button()
            util.add_class(button, "tile", "danger")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            inner.pack_start(util.icon_image(icon, 18), False, False, 0)
            inner.pack_start(util.label(title, "tile-sub", xalign=0.5), False, False, 0)
            button.add(inner)
            button.connect("clicked", lambda _b, a=action: (self.hide(), app.activate_action("power", GLib.Variant("s", a))))
            power_box.pack_start(button, True, True, 0)
        self.power.add(power_box)
        card.pack_start(self.power, False, False, 0)

        # Kacheln
        card.pack_start(util.label("SCHNELLZUGRIFF", "section-title"), False, False, 0)
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True)
        self.tiles = {
            "wifi": Tile("network-wireless-symbolic", "WLAN", services.network.toggle_wifi),
            "bluetooth": Tile("bluetooth-active-symbolic", "Bluetooth", services.bluetooth.toggle),
            "dnd": Tile("notifications-disabled-symbolic", "Nicht stören", lambda: hub.set_dnd(not hub.dnd)),
            "focus": Tile("alarm-symbolic", "Fokus", lambda: hub.toggle_focus()),
            "mode": Tile("weather-clear-night-symbolic", "Erscheinungsbild", hub.cycle_mode),
            "night": Tile("night-light-symbolic", "Nachtlicht", services.nightlight.toggle),
        }
        visible = [k for k in self.tiles if not (k == "night" and not services.nightlight.available)
                   and not (k == "wifi" and not services.network.available)]
        for index, key in enumerate(visible):
            grid.attach(self.tiles[key], index % 2, index // 2, 1, 1)
        card.pack_start(grid, False, False, 0)

        # Regler
        self.sliders_title = util.label("TON & BILD", "section-title")
        card.pack_start(self.sliders_title, False, False, 0)
        self.volume = SliderRow("audio-volume-high-symbolic", services.audio.set_volume, services.audio.toggle_mute)
        card.pack_start(self.volume, False, False, 0)
        self.brightness = SliderRow("display-brightness-symbolic", services.brightness.set_level)
        card.pack_start(self.brightness, False, False, 0)

        self.battery = util.label("", "tile-sub")
        self.battery.set_margin_top(10)
        card.pack_start(self.battery, False, False, 0)

        for service in (services.audio, services.network, services.bluetooth, services.brightness,
                        services.nightlight, services.battery):
            service.connect("changed", lambda *_: self.refresh() if self.visible else None)
        for signal in ("dnd-changed", "focus-changed", "theme-changed", "facet-changed"):
            hub.connect(signal, lambda *_: self.refresh() if self.visible else None)

    def on_show(self) -> None:
        self.power.set_reveal_child(False)
        self.services.network.refresh()
        self.services.bluetooth.refresh()
        self.services.brightness.refresh()
        self.services.audio.refresh()
        self.refresh()

    def refresh(self) -> None:
        hub, s = self.hub, self.services
        self.facet_label.set_text(f"Facette: {hub.facet['name']}")
        self.tiles["wifi"].update(s.network.wifi_enabled, s.network.label, s.network.icon)
        bt = s.bluetooth.powered
        self.tiles["bluetooth"].update(bool(bt), "Nicht verfügbar" if bt is None else ("An" if bt else "Aus"),
                                       "bluetooth-active-symbolic" if bt else "bluetooth-disabled-symbolic")
        self.tiles["bluetooth"].set_sensitive(bt is not None)
        self.tiles["dnd"].update(hub.dnd, "An" if hub.dnd else "Aus")
        if hub.focus.active:
            self.tiles["focus"].update(True, ("Pause · " if hub.on_break else "") + hub.focus.label())
        else:
            self.tiles["focus"].update(False, f"{hub.config['focus']['work_minutes']} Min. starten")
        mode = hub.config["appearance"].get("mode", "auto")
        names = {"auto": "Automatisch", "light": "Hell", "dark": "Dunkel"}
        self.tiles["mode"].update(hub.dark, names.get(mode, mode),
                                  "weather-clear-night-symbolic" if hub.dark else "weather-clear-symbolic")
        self.tiles["night"].update(s.nightlight.enabled, "An" if s.nightlight.enabled else "Aus")
        self.volume.set_visible(s.audio.available)
        self.volume.set(s.audio.volume, s.audio.icon)
        self.brightness.set_visible(s.brightness.available)
        if s.brightness.available:
            self.brightness.set(s.brightness.level)
        self.sliders_title.set_visible(s.audio.available or s.brightness.available)
        if s.battery.available:
            state = s.battery.state
            self.battery.set_text(f"Akku {state['percent']} % · {'lädt' if state['charging'] else 'entlädt'}")
        self.battery.set_visible(s.battery.available)


class StatBar(Gtk.DrawingArea):
    def __init__(self, color: str, fraction: float):
        super().__init__()
        self.color, self.fraction = color, fraction
        self.set_size_request(-1, 8)
        self.set_valign(Gtk.Align.CENTER)
        self.connect("draw", self._draw)

    def _draw(self, widget, cr) -> bool:
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        r, g, b = colors.hex_to_rgb(self.color)
        radius = height / 2

        def rounded(w):
            cr.new_sub_path()
            cr.arc(radius, radius, radius, 1.5708, 4.7124)
            cr.arc(max(radius, w - radius), radius, radius, 4.7124, 1.5708)
            cr.close_path()

        rounded(width)
        cr.set_source_rgba(r, g, b, 0.18)
        cr.fill()
        rounded(max(height, width * self.fraction))
        cr.set_source_rgb(r, g, b)
        cr.fill()
        return False


class DayPanel(Overlay):
    def __init__(self, app, hub):
        super().__init__(app, "daypanel", halign=Gtk.Align.CENTER, valign=Gtk.Align.START, margins={"top": 4})
        self.hub = hub
        util.add_class(self.card, "panel")
        self.card.set_size_request(420, -1)
        self.time = util.label("", "big-time")
        self.date = util.label("", "big-date")
        self.card.pack_start(self.time, False, False, 0)
        self.card.pack_start(self.date, False, False, 0)
        self.calendar = Gtk.Calendar()
        self.calendar.set_margin_top(6)
        self.card.pack_start(self.calendar, False, False, 0)

        self.card.pack_start(util.label("HEUTE IN DEINEN FACETTEN", "section-title"), False, False, 0)
        self.stats = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.card.pack_start(self.stats, False, False, 0)

        self.digest = util.add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "digest")
        self.digest.set_margin_top(12)
        self.card.pack_start(self.digest, False, False, 0)

        head = Gtk.Box()
        head.pack_start(util.label("BENACHRICHTIGUNGEN", "section-title"), False, False, 0)
        clear = Gtk.Button(label="Alle löschen")
        util.add_class(clear, "chip")
        clear.set_valign(Gtk.Align.END)
        clear.connect("clicked", lambda *_: hub.notifications.clear())
        head.pack_end(clear, False, False, 0)
        self.card.pack_start(head, False, False, 0)
        # Bewusst ohne ScrolledWindow: umbrechende Labels werden darin in GTK 3 abgeschnitten.
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.card.pack_start(self.list, False, False, 0)
        self.more = util.label("", "tile-sub", xalign=0.5)
        self.more.set_margin_top(6)
        self.card.pack_start(self.more, False, False, 0)
        self.empty = util.label("Alles erledigt ✨", "notif-body", xalign=0.5)
        self.empty.set_margin_top(10)
        self.card.pack_start(self.empty, False, False, 0)

        hub.notifications.connect("changed", lambda *_: self.refresh_notifications() if self.visible else None)
        GLib.timeout_add_seconds(1, lambda: self._tick() or True)

    def _tick(self) -> None:
        if self.visible:
            now = datetime.now()
            self.time.set_text(now.strftime("%H:%M"))
            self.date.set_text(long_date(now))

    def on_show(self) -> None:
        now = datetime.now()
        self.calendar.select_month(now.month - 1, now.year)
        self.calendar.select_day(now.day)
        self._tick()
        self.refresh_stats()
        self.refresh_notifications()

    def refresh_stats(self) -> None:
        util.clear(self.stats)
        stats = self.hub.stats_today()
        total = max(stats.values(), default=0) or 1
        shown = False
        for facet in self.hub.facets:
            seconds = stats.get(facet["id"], 0)
            if seconds < 60 and facet["id"] != self.hub.facet_id:
                continue
            shown = True
            row = Gtk.Box(spacing=10)
            name = util.label(facet["name"], "stat-label")
            name.set_size_request(80, -1)
            row.pack_start(name, False, False, 0)
            row.pack_start(StatBar(facet["color"], seconds / total), True, True, 0)
            value = util.label(schedule.format_duration(seconds), "stat-label", xalign=1.0)
            value.set_size_request(80, -1)
            row.pack_start(value, False, False, 0)
            self.stats.pack_start(row, False, False, 0)
        if not shown:
            self.stats.pack_start(util.label("Noch keine Zeit erfasst.", "tile-sub"), False, False, 0)
        self.stats.show_all()

    def refresh_notifications(self) -> None:
        store = self.hub.notifications
        util.clear(self.digest)
        if store.digest:
            self.digest.pack_start(util.label(f"Fokus-Rückblick · {len(store.digest)} gesammelt", "tile-title"), False, False, 0)
            apps = sorted({n.app_name for n in store.digest})
            self.digest.pack_start(util.label("Von: " + ", ".join(apps), "tile-sub", wrap=True), False, False, 0)
            self.digest.show_all()
        self.digest.set_visible(bool(store.digest))
        util.clear(self.list)
        for note in store.items[:4]:
            self.list.pack_start(NotificationCard(self.hub, note, in_center=True), False, False, 0)
        self.list.show_all()
        hidden = len(store.items) - 4
        self.more.set_text(f"… und {hidden} weitere" if hidden > 0 else "")
        self.more.set_visible(hidden > 0)
        self.empty.set_visible(not store.items)
