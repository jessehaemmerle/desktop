"""Info-Center (Action Center): notifications and quick actions."""

import time

from gi.repository import GLib, Gtk, GtkLayerShell, Pango

from tenwin.config import get_settings
from tenwin.gtkutil import add_class, clear_children, flat_button, icon_image, set_class
from tenwin.i18n import _, ngettext
from tenwin.shell.layer import Edge, Popup
from tenwin.shell.notifications import notification_image, sanitize_markup


def relative_time(timestamp):
    delta = time.time() - timestamp
    if delta < 60:
        return _("Now")
    if delta < 3600:
        minutes = int(delta // 60)
        return ngettext("%d minute ago", "%d minutes ago", minutes) % minutes
    return GLib.DateTime.new_from_unix_local(int(timestamp)).format("%H:%M")


class QuickAction:
    def __init__(self, key, label, icon, toggle=None, is_on=None, available=None, activate=None):
        self.key = key
        self.label = label
        self.icon = icon
        self.toggle = toggle
        self.is_on = is_on or (lambda: False)
        self.available = available or (lambda: True)
        self.activate = activate


class ActionCenter(Popup):
    WIDTH = 396

    def __init__(self, shell):
        super().__init__("tenwin-actioncenter", anchors=(Edge.TOP, Edge.BOTTOM, Edge.RIGHT))
        self.shell = shell
        self.settings = get_settings()
        self.qa_buttons = []
        self._build()
        shell.notifications.connect("changed", lambda *_: self.refresh_notifications())
        for service in (shell.network, shell.bluetooth, shell.power):
            service.connect("changed", lambda *_: self.refresh_quick_actions())

    def quick_actions(self):
        s = self.shell
        return [
            QuickAction("network", _("Network"), "tenwin-wifi-3",
                        toggle=lambda: s.network.set_wifi_enabled(not s.network.wifi_enabled),
                        is_on=lambda: s.network.wifi_enabled and s.network.connected,
                        available=lambda: s.network.available),
            QuickAction("bluetooth", _("Bluetooth"), "tenwin-bluetooth",
                        toggle=lambda: s.bluetooth.set_powered(not s.bluetooth.powered),
                        is_on=lambda: s.bluetooth.powered, available=lambda: s.bluetooth.available),
            QuickAction("nightlight", _("Night light"), "tenwin-nightlight",
                        toggle=lambda: self.settings.set("nightlight.enabled",
                                                         not self.settings["nightlight.enabled"]),
                        is_on=lambda: self.settings["nightlight.enabled"],
                        available=lambda: s.nightlight.available),
            QuickAction("settings", _("All settings"), "tenwin-settings",
                        activate=lambda: s.command("settings")),
            QuickAction("airplane", _("Airplane mode"), "tenwin-airplane",
                        toggle=self._toggle_airplane, is_on=lambda: s.network.airplane_mode,
                        available=lambda: s.network.has_wifi or s.bluetooth.available),
            QuickAction("focus", _("Focus assist"), "tenwin-focus-assist",
                        toggle=lambda: self.settings.set("notifications.focus_assist",
                                                         not self.settings["notifications.focus_assist"]),
                        is_on=lambda: self.settings["notifications.focus_assist"]),
            QuickAction("snip", _("Screen snip"), "tenwin-snip", activate=lambda: s.command("snip")),
            QuickAction("battery", _("Battery saver"), "tenwin-battery-saver",
                        toggle=lambda: s.power.set_profile("balanced" if s.power.profile == "power-saver"
                                                           else "power-saver"),
                        is_on=lambda: s.power.profile == "power-saver",
                        available=lambda: "power-saver" in s.power.available_profiles()),
            QuickAction("vpn", _("VPN"), "tenwin-shield", activate=lambda: s.open_settings("vpn"),
                        available=lambda: s.network.available),
            QuickAction("tablet", _("Tablet mode"), "tenwin-tablet",
                        toggle=lambda: self.settings.set("tablet.mode", not self.settings["tablet.mode"]),
                        is_on=lambda: self.settings["tablet.mode"]),
            QuickAction("lock", _("Lock"), "tenwin-lock", activate=lambda: s.command("lock")),
        ]

    def _toggle_airplane(self):
        on = not self.shell.network.airplane_mode
        self.shell.network.set_airplane_mode(on)
        if self.shell.bluetooth.available:
            self.shell.bluetooth.set_powered(not on)

    # -- layout ------------------------------------------------------------

    def _build(self):
        frame = add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "tw-panel", "tw-actioncenter")
        frame.set_size_request(self.WIDTH, -1)
        self.add(frame)

        header = add_class(Gtk.Box(), "tw-ac-header")
        self.manage = flat_button(Gtk.Label(label=_("Manage notifications")), "tw-ac-link")
        self.manage.connect("clicked", lambda *_: self.shell.open_settings("notifications"))
        header.pack_end(self.manage, False, False, 12)
        frame.pack_start(header, False, False, 8)

        self.scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.notif_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.scroll.add(self.notif_box)
        frame.pack_start(self.scroll, True, True, 0)

        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        frame.pack_end(bottom, False, False, 0)
        links = add_class(Gtk.Box(), "tw-ac-link")
        self.expand_button = flat_button(Gtk.Label())
        self.expand_button.connect("clicked", lambda *_: self.settings.set(
            "quickactions.expanded", not self.settings["quickactions.expanded"]))
        links.pack_start(self.expand_button, False, False, 16)
        self.clear_button = flat_button(Gtk.Label(label=_("Clear all notifications")))
        self.clear_button.connect("clicked", lambda *_: self.shell.notifications.clear())
        links.pack_end(self.clear_button, False, False, 16)
        bottom.pack_start(links, False, False, 8)

        self.qa_grid = Gtk.FlowBox(homogeneous=True, column_spacing=2, row_spacing=2)
        self.qa_grid.set_selection_mode(Gtk.SelectionMode.NONE)
        self.qa_grid.set_max_children_per_line(4)
        self.qa_grid.set_min_children_per_line(4)
        self.qa_grid.set_margin_start(12)
        self.qa_grid.set_margin_end(12)
        bottom.pack_start(self.qa_grid, False, False, 0)

        self.slider_row = add_class(Gtk.Box(spacing=12), "tw-slider-row")
        self.slider_row.pack_start(icon_image("tenwin-brightness", 16, symbolic=True), False, False, 0)
        self.brightness = add_class(Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 100, 1), "tw-slider")
        self.brightness.set_draw_value(False)
        self.brightness.connect("value-changed", lambda s: self.shell.brightness.set(s.get_value()))
        self.slider_row.pack_start(self.brightness, True, True, 0)
        self.slider_row.set_no_show_all(True)
        bottom.pack_start(self.slider_row, False, False, 4)
        self.settings.connect("changed", self._on_settings)
        self.refresh_notifications()
        self.refresh_quick_actions()

    def _on_settings(self, _settings, keys):
        if keys & {"quickactions.expanded", "nightlight.enabled", "notifications.focus_assist"}:
            self.refresh_quick_actions()

    def refresh_quick_actions(self):
        clear_children(self.qa_grid)
        actions = [a for a in self.quick_actions() if a.available()]
        expanded = self.settings["quickactions.expanded"]
        if not expanded:
            actions = actions[:4]
        for action in actions:
            button = flat_button(css="tw-quick-action")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            image = icon_image(action.icon, 16, symbolic=True)
            image.set_halign(Gtk.Align.START)
            box.pack_start(image, False, False, 0)
            text = Gtk.Label(label=action.label, xalign=0)
            text.set_ellipsize(Pango.EllipsizeMode.END)
            text.set_max_width_chars(10)
            box.pack_end(text, False, False, 0)
            button.add(box)
            set_class(button, "on", bool(action.toggle) and action.is_on())
            button.connect("clicked", lambda _b, a=action: self._run_action(a))
            self.qa_grid.add(button)
        self.qa_grid.show_all()
        self.expand_button.get_child().set_text(_("Collapse") if expanded else _("Expand"))

    def _run_action(self, action):
        if action.toggle:
            action.toggle()
            GLib.timeout_add(400, lambda: self.refresh_quick_actions() and False)
        elif action.activate:
            self.close_popup()
            action.activate()

    def refresh_notifications(self):
        clear_children(self.notif_box)
        history = self.shell.notifications.history
        if not history:
            empty = add_class(Gtk.Label(label=_("No new notifications"), xalign=0), "tw-ac-empty")
            self.notif_box.pack_start(empty, False, False, 0)
            self.clear_button.set_sensitive(False)
        else:
            self.clear_button.set_sensitive(True)
            groups = {}
            order = []
            for note in history:
                if note.app_name not in groups:
                    groups[note.app_name] = []
                    order.append(note.app_name)
                groups[note.app_name].append(note)
            for app_name in order:
                head = Gtk.Box()
                head.pack_start(add_class(Gtk.Label(label=app_name, xalign=0), "tw-ac-group-title"), True, True, 0)
                clear = flat_button(icon_image("tenwin-close", 10, symbolic=True), "tw-notif-close",
                                    _("Clear all %s notifications") % app_name)
                clear.connect("clicked", lambda _b, a=app_name: self.shell.notifications.clear(a))
                head.pack_end(clear, False, False, 12)
                self.notif_box.pack_start(head, False, False, 0)
                for note in groups[app_name]:
                    self.notif_box.pack_start(self._note_widget(note), False, False, 0)
        self.notif_box.show_all()
        self.shell.update_notification_badge()

    def _note_widget(self, note):
        events = Gtk.EventBox()
        box = add_class(Gtk.Box(spacing=10), "tw-notification")
        box.pack_start(notification_image(note.icon(), 24), False, False, 0)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        top = Gtk.Box()
        summary = add_class(Gtk.Label(label=note.summary, xalign=0), "tw-notif-summary")
        summary.set_ellipsize(Pango.EllipsizeMode.END)
        top.pack_start(summary, True, True, 0)
        top.pack_end(add_class(Gtk.Label(label=relative_time(note.time)), "tw-dim-text"), False, False, 0)
        texts.pack_start(top, False, False, 0)
        if note.body:
            body = add_class(Gtk.Label(xalign=0), "tw-notif-body")
            body.set_markup(sanitize_markup(note.body))
            body.set_line_wrap(True)
            body.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            body.set_lines(3)
            body.set_ellipsize(Pango.EllipsizeMode.END)
            body.set_max_width_chars(40)
            texts.pack_start(body, False, False, 0)
        box.pack_start(texts, True, True, 0)
        close = flat_button(icon_image("tenwin-close", 10, symbolic=True), "tw-notif-close")
        close.set_valign(Gtk.Align.START)
        close.connect("clicked", lambda *_: self.shell.notifications.remove(note.id))
        box.pack_end(close, False, False, 0)
        events.add(box)

        def on_click(_w, event):
            if event.button == 1:
                if any(k == "default" for k, _l in note.actions):
                    self.close_popup()
                    self.shell.notifications.invoke(note, "default")
                elif note.desktop_entry:
                    info = self.shell.apps.get(note.desktop_entry + ".desktop")
                    if info is not None:
                        self.close_popup()
                        self.shell.apps.launch(info)
            return True

        events.connect("button-release-event", on_click)
        return events

    # -- Popup hooks -------------------------------------------------------

    def on_open(self):
        # Exclusive zone 0: the panel spans the height above the taskbar.
        GtkLayerShell.set_exclusive_zone(self, 0)
        self.shell.notifications.hide_toasts()
        self.shell.brightness.refresh()
        available = self.shell.brightness.available
        self.slider_row.set_visible(available)
        if available:
            self.slider_row.show_all()
            self.brightness.set_value(self.shell.brightness.percent)
        self.refresh_notifications()
        self.refresh_quick_actions()
