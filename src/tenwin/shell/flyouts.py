"""Taskbar flyouts: clock/calendar, volume, network, battery, window list."""

import os

from gi.repository import Gdk, GLib, Gtk, Pango

from tenwin.config import get_settings
from tenwin.gtkutil import add_class, clear_children, flat_button, icon_image, set_class, set_icon
from tenwin.i18n import _, current_language
from tenwin.services.network import strength_icon
from tenwin.shell.layer import Edge, Popup, taskbar_edge


def week_starts_monday():
    lc = os.environ.get("LC_TIME") or os.environ.get("LC_ALL") or os.environ.get("LANG") or ""
    sunday = ("en_US", "en_CA", "en_PH", "ja_", "ko_", "zh_", "he_", "pt_BR", "es_MX", "hi_")
    return not lc.startswith(sunday)


class TrayFlyout(Popup):
    """Flyout anchored at the right end of the taskbar."""

    def __init__(self, shell, namespace, width):
        super().__init__(namespace, anchors=(taskbar_edge(), Edge.RIGHT))
        self.shell = shell
        self.frame = add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "tw-panel", "tw-flyout")
        self.frame.set_size_request(width, -1)
        self.add(self.frame)

    def footer_link(self, text, callback):
        bar = add_class(Gtk.Box(), "tw-flyout-footer")
        button = flat_button(Gtk.Label(label=text, xalign=0))
        button.connect("clicked", lambda *_: (self.close_popup(), callback()))
        bar.pack_start(button, False, False, 0)
        return bar


# ---------------------------------------------------------------- calendar

class CalendarFlyout(TrayFlyout):
    def __init__(self, shell):
        super().__init__(shell, "tenwin-calendar", 360)
        self.time_label = add_class(Gtk.Label(xalign=0), "tw-big-time")
        self.frame.pack_start(self.time_label, False, False, 0)
        self.date_button = flat_button(add_class(Gtk.Label(xalign=0), "tw-big-date"))
        self.date_button.connect("clicked", lambda *_: self.show_month(GLib.DateTime.new_now_local()))
        self.frame.pack_start(self.date_button, False, False, 0)
        self.frame.pack_start(Gtk.Separator(), False, False, 0)

        cal = add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "tw-calendar")
        head = Gtk.Box()
        self.month_label = add_class(Gtk.Label(xalign=0), "tw-cal-header")
        head.pack_start(self.month_label, True, True, 0)
        up = flat_button(icon_image("tenwin-chevron-up", 12, symbolic=True))
        up.connect("clicked", lambda *_: self.shift(-1))
        down = flat_button(icon_image("tenwin-chevron-down", 12, symbolic=True))
        down.connect("clicked", lambda *_: self.shift(1))
        head.pack_end(down, False, False, 0)
        head.pack_end(up, False, False, 0)
        cal.pack_start(head, False, False, 0)
        self.grid = Gtk.Grid(column_homogeneous=True)
        cal.pack_start(self.grid, False, False, 0)
        self.frame.pack_start(cal, False, False, 0)
        self.frame.pack_start(Gtk.Separator(), False, False, 0)
        self.frame.pack_start(self.footer_link(_("Date and time settings"),
                                               lambda: shell.open_settings("datetime")), False, False, 0)
        self.shown = GLib.DateTime.new_now_local()
        self._tick_id = 0
        cal.add_events(Gdk.EventMask.SCROLL_MASK)

    def on_open(self):
        self.show_month(GLib.DateTime.new_now_local())
        self._tick()
        self._tick_id = GLib.timeout_add(1000, self._tick)

    def on_close(self):
        if self._tick_id:
            GLib.source_remove(self._tick_id)
            self._tick_id = 0

    def _tick(self):
        now = GLib.DateTime.new_now_local()
        fmt = "%H:%M:%S" if get_settings()["region.clock_24h"] else "%l:%M:%S %p"
        self.time_label.set_text(now.format(fmt).strip())
        date_fmt = "%A, %e. %B %Y" if current_language() == "de" else "%A, %B %e, %Y"
        self.date_button.get_child().set_text(now.format(date_fmt).replace("  ", " "))
        return GLib.SOURCE_CONTINUE

    def shift(self, months):
        self.show_month(self.shown.add_months(months))

    def show_month(self, dt):
        self.shown = GLib.DateTime.new_local(dt.get_year(), dt.get_month(), 1, 0, 0, 0)
        self.month_label.set_text(self.shown.format("%B %Y"))
        clear_children(self.grid)
        monday = week_starts_monday()
        # Weekday headers from a known week (2024-01-01 was a Monday).
        base = GLib.DateTime.new_local(2024, 1, 1 if monday else 7, 0, 0, 0)
        for i in range(7):
            name = base.add_days(i).format("%a").rstrip(".")[:2]
            self.grid.attach(add_class(Gtk.Label(label=name), "tw-cal-weekday"), i, 0, 1, 1)
        first_weekday = self.shown.get_day_of_week()  # 1 = Monday … 7 = Sunday
        offset = (first_weekday - 1) if monday else (first_weekday % 7)
        start = self.shown.add_days(-offset)
        today = GLib.DateTime.new_now_local()
        for cell in range(42):
            day = start.add_days(cell)
            button = flat_button(Gtk.Label(label=str(day.get_day_of_month())))
            if day.get_month() != self.shown.get_month():
                add_class(button, "other-month")
            if (day.get_year(), day.get_day_of_year()) == (today.get_year(), today.get_day_of_year()):
                add_class(button, "today")
            self.grid.attach(button, cell % 7, 1 + cell // 7, 1, 1)
        self.grid.show_all()


# ---------------------------------------------------------------- volume

class VolumeFlyout(TrayFlyout):
    def __init__(self, shell):
        super().__init__(shell, "tenwin-volume", 360)
        self.audio = shell.audio
        self.device_button = flat_button(css="tw-flyout-title")
        head = Gtk.Box(spacing=8)
        self.device_label = Gtk.Label(xalign=0)
        self.device_label.set_ellipsize(Pango.EllipsizeMode.END)
        head.pack_start(self.device_label, True, True, 0)
        head.pack_end(icon_image("tenwin-chevron-up", 12, symbolic=True), False, False, 0)
        self.device_button.add(head)
        self.device_button.connect("clicked", lambda *_: self._toggle_devices())
        self.devices = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.devices.set_no_show_all(True)
        self.frame.pack_start(self.devices, False, False, 0)
        self.frame.pack_start(self.device_button, False, False, 0)

        row = Gtk.Box(spacing=12)
        row.set_margin_start(12)
        row.set_margin_end(16)
        row.set_margin_bottom(16)
        self.mute_button = flat_button()
        self.mute_image = icon_image(self.audio.icon_name(), 24, symbolic=True)
        self.mute_button.add(self.mute_image)
        self.mute_button.set_size_request(40, 40)
        self.mute_button.connect("clicked", lambda *_: self.audio.toggle_mute())
        row.pack_start(self.mute_button, False, False, 0)
        self.scale = add_class(Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1), "tw-slider")
        self.scale.set_draw_value(False)
        self._handler = self.scale.connect("value-changed", lambda s: self.audio.set_volume(s.get_value()))
        row.pack_start(self.scale, True, True, 0)
        self.value_label = Gtk.Label(label="0")
        self.value_label.set_size_request(36, -1)
        add_class(self.value_label, "tw-flyout-title")
        row.pack_end(self.value_label, False, False, 0)
        self.frame.pack_start(row, False, False, 0)
        self.audio.connect("changed", lambda *_: self.update())
        self.update()

    def update(self):
        sink = self.audio.sink
        self.device_label.set_text(sink.description if sink else _("No audio output device is installed"))
        self.scale.handler_block(self._handler)
        self.scale.set_value(self.audio.volume)
        self.scale.handler_unblock(self._handler)
        self.value_label.set_text(str(self.audio.volume))
        set_icon(self.mute_image, self.audio.icon_name(), 24, symbolic=True)
        self.scale.set_sensitive(sink is not None)

    def _toggle_devices(self):
        if self.devices.get_visible():
            self.devices.hide()
            return
        clear_children(self.devices)
        self.devices.pack_start(add_class(Gtk.Label(label=_("Select playback device"), xalign=0),
                                          "tw-flyout-title"), False, False, 0)
        for dev in self.audio.sinks:
            button = flat_button(css="tw-device-row")
            label = Gtk.Label(label=dev.description, xalign=0)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            button.add(label)
            set_class(button, "selected", dev.name == self.audio.default_sink)
            button.connect("clicked", lambda _b, n=dev.name: (self.audio.set_default_sink(n), self.devices.hide()))
            self.devices.pack_start(button, False, False, 0)
        self.devices.pack_start(Gtk.Separator(), False, False, 0)
        self.devices.show_all()

    def on_open(self):
        self.devices.hide()
        self.audio.refresh()


# ---------------------------------------------------------------- network

class NetworkFlyout(TrayFlyout):
    def __init__(self, shell):
        super().__init__(shell, "tenwin-network", 360)
        self.net = shell.network
        self.expanded = None
        self.scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.scroll.set_min_content_height(80)
        self.scroll.set_max_content_height(460)
        self.scroll.set_propagate_natural_height(True)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.scroll.add(self.list)
        self.frame.pack_start(self.scroll, True, True, 0)
        self.frame.pack_start(self.footer_link(_("Network & Internet settings"),
                                               lambda: shell.open_settings("network-status")), False, False, 0)
        self.tiles = Gtk.Box(spacing=2, homogeneous=False)
        self.tiles.set_margin_start(12)
        self.tiles.set_margin_bottom(12)
        self.frame.pack_start(self.tiles, False, False, 0)
        self.net.connect("changed", lambda *_: self.is_open() and self.update())

    def on_open(self):
        self.expanded = None
        self.net.request_scan()
        self.update()

    def update(self):
        clear_children(self.list)
        kind, name, _strength = self.net.primary()
        if kind in ("wired", "other"):
            row = add_class(Gtk.Box(spacing=12), "tw-wifi-row")
            row.pack_start(icon_image("tenwin-network-wired", 24, symbolic=True), False, False, 0)
            texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            texts.pack_start(add_class(Gtk.Label(label=name, xalign=0), "tw-result-title"), False, False, 0)
            texts.pack_start(add_class(Gtk.Label(label=_("Connected"), xalign=0), "tw-dim-text"), False, False, 0)
            row.pack_start(texts, True, True, 0)
            self.list.pack_start(row, False, False, 0)
        if not self.net.available:
            self.list.pack_start(add_class(Gtk.Label(label=_("NetworkManager is not running."), xalign=0),
                                           "tw-flyout-title"), False, False, 0)
        elif self.net.has_wifi and self.net.wifi_enabled:
            for ap in self.net.access_points():
                self.list.pack_start(self._ap_row(ap), False, False, 0)
        elif self.net.has_wifi:
            self.list.pack_start(add_class(Gtk.Label(label=_("Wi-Fi is turned off"), xalign=0),
                                           "tw-flyout-title"), False, False, 0)
        self.list.show_all()

        clear_children(self.tiles)
        if self.net.has_wifi:
            self.tiles.pack_start(self._tile(_("Wi-Fi"), "tenwin-wifi-3", self.net.wifi_enabled,
                                             lambda: self.net.set_wifi_enabled(not self.net.wifi_enabled)),
                                  False, False, 0)
            self.tiles.pack_start(self._tile(_("Airplane mode"), "tenwin-airplane", self.net.airplane_mode,
                                             lambda: self.net.set_airplane_mode(not self.net.airplane_mode)),
                                  False, False, 0)
        self.tiles.show_all()

    def _tile(self, text, icon, on, callback):
        button = flat_button(css="tw-quick-action")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        image = icon_image(icon, 16, symbolic=True)
        image.set_halign(Gtk.Align.START)
        box.pack_start(image, False, False, 0)
        box.pack_end(Gtk.Label(label=text, xalign=0), False, False, 0)
        button.add(box)
        set_class(button, "on", on)
        button.connect("clicked", lambda *_: callback())
        return button

    def _ap_row(self, ap):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        button = flat_button(css="tw-wifi-row")
        row = Gtk.Box(spacing=12)
        row.pack_start(icon_image(strength_icon(ap.strength), 24, symbolic=True), False, False, 0)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        texts.pack_start(add_class(Gtk.Label(label=ap.ssid, xalign=0), "tw-result-title"), False, False, 0)
        if ap.active:
            status = _("Connected, secured") if ap.secure else _("Connected, open")
        else:
            status = _("Secured") if ap.secure else _("Open")
        texts.pack_start(add_class(Gtk.Label(label=status, xalign=0), "tw-dim-text"), False, False, 0)
        row.pack_start(texts, True, True, 0)
        button.add(row)
        outer.pack_start(button, False, False, 0)
        is_expanded = self.expanded == ap.ssid
        set_class(button, "expanded", is_expanded)
        button.connect("clicked", lambda *_: self._expand(ap.ssid))
        if is_expanded:
            detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            detail.set_margin_start(52)
            detail.set_margin_end(16)
            detail.set_margin_bottom(12)
            actions = Gtk.Box()
            if ap.active:
                disconnect = flat_button(Gtk.Label(label=_("Disconnect")), "tw-button-solid")
                disconnect.connect("clicked", lambda *_: self.net.disconnect_wifi())
                actions.pack_end(disconnect, False, False, 0)
                detail.pack_start(actions, False, False, 0)
            else:
                status = add_class(Gtk.Label(xalign=0, wrap=True), "tw-dim-text")
                password = None
                if ap.secure and not self.net.known(ap.ssid):
                    detail.pack_start(Gtk.Label(label=_("Enter the network security key"), xalign=0),
                                      False, False, 0)
                    password = Gtk.Entry(visibility=False)
                    password.set_input_purpose(Gtk.InputPurpose.PASSWORD)
                    detail.pack_start(password, False, False, 0)
                connect = flat_button(Gtk.Label(label=_("Connect") if password is None else _("Next")),
                                      "tw-button-accent")

                def do_connect(*_args):
                    key = password.get_text() if password is not None else None
                    status.set_text(_("Connecting…"))

                    def done(ok, msg):
                        status.set_text("" if ok else _("Can't connect to this network") + "\n" + msg)
                    self.net.connect_ap(ap, key, done)

                connect.connect("clicked", do_connect)
                if password is not None:
                    password.connect("activate", do_connect)
                actions.pack_end(connect, False, False, 0)
                detail.pack_start(actions, False, False, 0)
                detail.pack_start(status, False, False, 0)
            outer.pack_start(detail, False, False, 0)
        return outer

    def _expand(self, ssid):
        self.expanded = None if self.expanded == ssid else ssid
        self.update()


# ---------------------------------------------------------------- battery

class BatteryFlyout(TrayFlyout):
    PROFILES = ["power-saver", "balanced", "performance"]

    def __init__(self, shell):
        super().__init__(shell, "tenwin-battery", 360)
        self.power = shell.power
        top = Gtk.Box(spacing=16)
        top.set_margin_start(16)
        top.set_margin_top(16)
        self.icon = icon_image(self.power.icon_name(), 32, symbolic=True)
        top.pack_start(self.icon, False, False, 0)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.percent = add_class(Gtk.Label(xalign=0), "tw-big-time")
        self.percent.set_margin_start(0)
        texts.pack_start(self.percent, False, False, 0)
        self.estimate = add_class(Gtk.Label(xalign=0), "tw-dim-text")
        texts.pack_start(self.estimate, False, False, 0)
        top.pack_start(texts, True, True, 0)
        self.frame.pack_start(top, False, False, 0)

        self.mode_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.mode_box.set_margin_start(16)
        self.mode_box.set_margin_end(16)
        self.mode_box.set_margin_top(12)
        self.mode_label = Gtk.Label(xalign=0)
        self.mode_box.pack_start(self.mode_label, False, False, 0)
        self.mode = add_class(Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 2, 1), "tw-slider")
        self.mode.set_draw_value(False)
        self.mode.set_round_digits(0)
        self._handler = self.mode.connect("value-changed", self._on_mode)
        self.mode_box.pack_start(self.mode, False, False, 6)
        ends = Gtk.Box()
        ends.pack_start(add_class(Gtk.Label(label=_("Best battery life")), "tw-dim-text"), False, False, 0)
        ends.pack_end(add_class(Gtk.Label(label=_("Best performance")), "tw-dim-text"), False, False, 0)
        self.mode_box.pack_start(ends, False, False, 0)
        self.frame.pack_start(self.mode_box, False, False, 0)
        self.frame.pack_start(self.footer_link(_("Battery settings"), lambda: shell.open_settings("power")),
                              False, False, 8)
        self.power.connect("changed", lambda *_: self.update())

    def update(self):
        p = self.power
        set_icon(self.icon, p.icon_name(), 32, symbolic=True)
        self.percent.set_text("%d %%" % p.percent)
        if p.charging:
            text = _("Fully charged") if p.state == 4 else _("Charging")
        elif p.time_to_empty:
            hours, minutes = divmod(p.time_to_empty // 60, 60)
            text = _("%d h %02d min remaining") % (hours, minutes)
        else:
            text = ""
        self.estimate.set_text(text)
        profiles = p.available_profiles()
        self.mode_box.set_visible(bool(profiles))
        if p.profile in self.PROFILES:
            self.mode.handler_block(self._handler)
            self.mode.set_value(self.PROFILES.index(p.profile))
            self.mode.handler_unblock(self._handler)
        names = {"power-saver": _("Battery saver"), "balanced": _("Recommended"),
                 "performance": _("Best performance")}
        self.mode_label.set_text(_("Power mode: %s") % names.get(p.profile, "–"))

    def _on_mode(self, scale):
        value = int(round(scale.get_value()))
        profile = self.PROFILES[value]
        if profile in self.power.available_profiles():
            self.power.set_profile(profile)

    def on_open(self):
        self.update()


# ---------------------------------------------------------------- windows

class WindowListPopup(Popup):
    """Shown when clicking a taskbar button that groups several windows."""

    def __init__(self, shell):
        super().__init__("tenwin-windowlist", anchors=(taskbar_edge(), Edge.LEFT))
        self.shell = shell
        self.box = add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "tw-panel")
        self.box.set_size_request(280, -1)
        self.add(self.box)

    def show_for(self, app_button, windows):
        clear_children(self.box)
        for window in windows:
            row = Gtk.Box(spacing=10)
            button = flat_button(css="tw-result")
            content = Gtk.Box(spacing=10)
            content.pack_start(icon_image(app_button.group.icon, 16), False, False, 0)
            label = Gtk.Label(label=window.title or app_button.group.name, xalign=0)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            label.set_max_width_chars(32)
            content.pack_start(label, True, True, 0)
            button.add(content)
            button.connect("clicked", lambda _b, w=window: (self.close_popup(), self.shell.wm.activate(w)))
            row.pack_start(button, True, True, 0)
            close = flat_button(icon_image("tenwin-close", 10, symbolic=True), "tw-notif-close")
            close.connect("clicked", lambda _b, w=window: (self.shell.wm.close(w), self.close_popup()))
            row.pack_end(close, False, False, 4)
            self.box.pack_start(row, False, False, 0)
        x = app_button.translate_coordinates(app_button.get_toplevel(), 0, 0)[0]
        width = app_button.get_allocated_width()
        self.set_margins(left=max(0, x + width // 2 - 140))
        self.open_popup(app_button.taskbar.monitor)
