"""Horizont – die obere Leiste aus drei schwebenden Inseln."""

from __future__ import annotations

from datetime import datetime

from gi.repository import Gdk, GLib, Gtk

from . import util
from .dates import short_date


class FacetChip(Gtk.Button):
    def __init__(self, hub, facet: dict):
        super().__init__()
        self.hub = hub
        self.facet_id = facet["id"]
        util.add_class(self, "facet-chip")
        box = Gtk.Box()
        self.dot = Gtk.Box()
        self.dot.set_valign(Gtk.Align.CENTER)
        util.add_class(self.dot, "facet-dot")
        self._dot_css = Gtk.CssProvider()
        self.dot.get_style_context().add_provider(self._dot_css, Gtk.STYLE_PROVIDER_PRIORITY_USER + 20)
        box.pack_start(self.dot, False, False, 0)
        self.revealer = Gtk.Revealer()
        self.revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_RIGHT)
        self.revealer.set_transition_duration(240)
        self.name = util.label(facet["name"], "facet-name")
        self.revealer.add(self.name)
        box.pack_start(self.revealer, False, False, 0)
        self.add(box)
        self.connect("clicked", lambda *_: hub.switch_facet(self.facet_id))
        self.update(facet)

    def update(self, facet: dict) -> None:
        self.name.set_text(facet["name"])
        self._dot_css.load_from_data(f".facet-dot {{ background-color: {facet['color']}; }}".encode())
        active = facet["id"] == self.hub.facet_id
        util.toggle_class(self, "active", active)
        self.revealer.set_reveal_child(active)
        index = self.hub.facet_index(facet["id"]) + 1
        self.set_tooltip_text(f"{facet['name']}  (Super+{index})" if index < 10 else facet["name"])


class TopBar:
    def __init__(self, app, hub, services):
        self.hub, self.services = hub, services
        self.window = util.layer_window(app, "bar", layer="top", anchors=("top", "left", "right"),
                                        margins={"top": 0, "left": 0, "right": 0}, exclusive="auto")
        root = Gtk.Box()
        # Ränder innerhalb des Fensters, damit der Inselschatten nicht abgeschnitten wird
        root.set_margin_top(6)
        root.set_margin_start(8)
        root.set_margin_end(8)
        root.set_margin_bottom(12)
        self.window.add(root)

        # ---- links: Logo + Facetten
        left = util.add_class(Gtk.Box(spacing=2), "island")
        logo = Gtk.Button()
        util.add_class(logo, "bar-button")
        logo.add(util.label("◆ Prisma", "prisma-logo"))
        logo.set_tooltip_text("Kompass öffnen (Super+Leertaste)")
        logo.connect("clicked", lambda *_: app.activate_action("kompass", None))
        left.pack_start(logo, False, False, 0)
        self.facet_box = Gtk.Box(spacing=2)
        left.pack_start(self.facet_box, False, False, 0)
        root.pack_start(self._scroll(left, lambda d: hub.cycle_facet(d)), False, False, 0)

        # ---- Mitte: Uhr
        center = util.add_class(Gtk.Box(), "island")
        self.clock_button = Gtk.Button()
        util.add_class(self.clock_button, "bar-button")
        clock_box = Gtk.Box()
        self.date_label = util.label("", "clock-date")
        self.clock_label = util.label("", "clock")
        clock_box.pack_start(self.date_label, False, False, 0)
        clock_box.pack_start(self.clock_label, False, False, 0)
        self.clock_button.add(clock_box)
        self.clock_button.set_tooltip_text("Tagesüberblick & Benachrichtigungen (Super+N)")
        self.clock_button.connect("clicked", lambda *_: app.activate_action("daypanel", None))
        center.pack_start(self.clock_button, False, False, 0)
        root.set_center_widget(center)

        # ---- rechts: Fokus + Status
        right = Gtk.Box(spacing=6)
        self.focus_revealer = Gtk.Revealer()
        self.focus_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_LEFT)
        focus_btn = Gtk.Button()
        util.add_class(focus_btn, "focus-chip")
        focus_inner = Gtk.Box(spacing=6)
        focus_inner.pack_start(util.icon_image("alarm-symbolic", 14), False, False, 0)
        self.focus_label = util.label("", "status-text")
        focus_inner.pack_start(self.focus_label, False, False, 0)
        focus_btn.add(focus_inner)
        focus_btn.set_tooltip_text("Fokus beenden")
        focus_btn.connect("clicked", lambda *_: hub.stop_focus())
        self.focus_button = focus_btn
        self.focus_revealer.add(focus_btn)
        right.pack_start(self.focus_revealer, False, False, 0)

        status = util.add_class(Gtk.Box(), "island")
        self.status_button = Gtk.Button()
        util.add_class(self.status_button, "bar-button")
        self.status_button.set_tooltip_text("Schnelleinstellungen (Super+A)")
        icons = Gtk.Box(spacing=10)
        self.bell = util.icon_image("preferences-system-notifications-symbolic", 16)
        self.badge = util.label("", "badge", xalign=0.5)
        bell_box = Gtk.Box(spacing=3)
        bell_box.pack_start(self.bell, False, False, 0)
        bell_box.pack_start(self.badge, False, False, 0)
        icons.pack_start(bell_box, False, False, 0)
        self.net_icon = util.icon_image("network-offline-symbolic", 16)
        self.vol_icon = util.icon_image("audio-volume-medium-symbolic", 16)
        self.bat_icon = util.icon_image("battery-missing-symbolic", 16)
        self.bat_label = util.label("", "status-text")
        for widget in (self.net_icon, self.vol_icon, self.bat_icon):
            util.add_class(widget, "status-icon")
            icons.pack_start(widget, False, False, 0)
        icons.pack_start(self.bat_label, False, False, 0)
        self.status_button.add(icons)
        self.status_button.connect("clicked", lambda *_: app.activate_action("quicksettings", None))
        status.pack_start(self.status_button, False, False, 0)
        right.pack_start(self._scroll(status, lambda d: services.audio.step(-d)), False, False, 0)
        root.pack_end(right, False, False, 0)

        self._chips: dict[str, FacetChip] = {}
        self.rebuild_facets()
        hub.connect("facet-changed", lambda *_: self.refresh_facets())
        hub.connect("config-changed", lambda *_: self.rebuild_facets())
        hub.connect("focus-changed", lambda *_: self.update_focus())
        hub.connect("dnd-changed", lambda *_: self.update_notifications())
        hub.notifications.connect("changed", lambda *_: self.update_notifications())
        services.audio.connect("changed", lambda *_: self.update_status())
        services.network.connect("changed", lambda *_: self.update_status())
        services.battery.connect("changed", lambda *_: self.update_status())

        self.window.show_all()
        self.update_clock()
        self.update_status()
        self.update_focus()
        self.update_notifications()
        GLib.timeout_add(1000, self._tick)

    def _scroll(self, widget: Gtk.Widget, callback) -> Gtk.Widget:
        """Hüllt ``widget`` in eine EventBox, die Mausrad-Ereignisse empfängt."""
        box = Gtk.EventBox()
        box.set_visible_window(False)
        box.add(widget)
        box.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        state = {"acc": 0.0}

        def on_scroll(_w, event):
            ok, dx, dy = event.get_scroll_deltas()
            if not ok:
                dy = {Gdk.ScrollDirection.UP: -1, Gdk.ScrollDirection.DOWN: 1}.get(event.direction, 0)
            state["acc"] += dy
            if abs(state["acc"]) >= 1:
                callback(1 if state["acc"] > 0 else -1)
                state["acc"] = 0.0
            return True

        box.connect("scroll-event", on_scroll)
        return box

    # ----------------------------------------------------------- Aktualisieren
    def rebuild_facets(self) -> None:
        util.clear(self.facet_box)
        self._chips = {}
        for facet in self.hub.facets:
            chip = FacetChip(self.hub, facet)
            self._chips[facet["id"]] = chip
            self.facet_box.pack_start(chip, False, False, 0)
        self.facet_box.show_all()
        self.refresh_facets()

    def refresh_facets(self) -> None:
        for facet in self.hub.facets:
            chip = self._chips.get(facet["id"])
            if chip:
                chip.update(facet)

    def _tick(self) -> bool:
        self.update_clock()
        return True

    def update_clock(self) -> None:
        now = datetime.now()
        seconds = self.hub.config["appearance"].get("clock_seconds")
        self.clock_label.set_text(now.strftime("%H:%M:%S" if seconds else "%H:%M"))
        self.date_label.set_text(short_date(now))

    def update_focus(self) -> None:
        focus = self.hub.focus
        self.focus_revealer.set_reveal_child(focus.active)
        if focus.active:
            prefix = "Pause " if self.hub.on_break else ""
            self.focus_label.set_text(prefix + focus.label())
            util.toggle_class(self.focus_button, "break", self.hub.on_break)

    def update_notifications(self) -> None:
        count = self.hub.notifications.count
        self.badge.set_text(str(count) if count < 100 else "99+")
        self.badge.set_visible(count > 0)
        self.bell.set_from_icon_name(
            "notifications-disabled-symbolic" if self.hub.dnd else "preferences-system-notifications-symbolic",
            Gtk.IconSize.MENU,
        )
        self.bell.set_pixel_size(16)

    def update_status(self) -> None:
        net, audio, battery = self.services.network, self.services.audio, self.services.battery
        self.net_icon.set_visible(net.available)
        self.net_icon.set_from_icon_name(net.icon, Gtk.IconSize.MENU)
        self.net_icon.set_tooltip_text(net.label)
        self.vol_icon.set_visible(audio.available)
        self.vol_icon.set_from_icon_name(audio.icon, Gtk.IconSize.MENU)
        self.vol_icon.set_tooltip_text(f"Lautstärke {round(audio.volume * 100)} %")
        has_battery = battery.available
        self.bat_icon.set_visible(has_battery)
        self.bat_label.set_visible(has_battery)
        if has_battery:
            self.bat_icon.set_from_icon_name(battery.icon, Gtk.IconSize.MENU)
            self.bat_label.set_text(f"{battery.state['percent']} %")
        for image in (self.net_icon, self.vol_icon, self.bat_icon):
            image.set_pixel_size(16)
