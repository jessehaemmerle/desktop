"""The taskbar (one per monitor)."""

from gi.repository import Gdk, GLib, Gtk, Pango

from tenwin.config import get_settings
from tenwin.gtkutil import add_class, flat_button, icon_image, menu_item, popup_menu, set_class, set_icon
from tenwin.i18n import _, pgettext
from tenwin.shell.layer import Edge, Layer, LayerWindow, taskbar_edge, taskbar_height


class AppGroup:
    """Windows of one application (or a pinned app without windows)."""

    def __init__(self, key, info, single_window=False):
        self.key = key
        self.info = info
        self.windows = []
        self.single_window = single_window  # "never combine": one button per window

    @property
    def name(self):
        if self.info is not None:
            return self.info.get_display_name()
        return self.windows[0].title if self.windows else self.key

    @property
    def icon(self):
        return self.info.get_icon() if self.info is not None else None


def group_windows(shell):
    """Pinned apps first, then other running apps in order of appearance."""
    groups = []
    by_key = {}
    for info in shell.apps.pinned_taskbar():
        group = AppGroup(info.get_id(), info)
        groups.append(group)
        by_key[group.key] = group
    for window in shell.wm.list():
        if window.parent:
            continue  # dialogs are grouped with their parent window
        info = shell.apps.for_window(window.app_id)
        key = info.get_id() if info is not None else "window:" + (window.app_id or str(window.id))
        group = by_key.get(key)
        if group is None:
            group = AppGroup(key, info)
            groups.append(group)
            by_key[key] = group
        group.windows.append(window)
    if get_settings()["taskbar.combine"] == "never":
        split = []
        for group in groups:
            if not group.windows:
                split.append(group)
                continue
            for window in group.windows:
                single = AppGroup("win:%d" % window.id, group.info, single_window=True)
                single.windows = [window]
                split.append(single)
        groups = split
    return groups


DND_TASKBAR = "application/x-tenwin-taskbar"
DND_TILE = "application/x-tenwin-tile"


class AppButton(Gtk.EventBox):
    def __init__(self, taskbar, group):
        super().__init__()
        self.taskbar = taskbar
        self.shell = taskbar.shell
        self.group = group
        self.set_above_child(False)
        self.button = flat_button(css="tw-app")
        overlay = Gtk.Overlay()
        size = 16 if get_settings()["taskbar.small_icons"] else 24
        self.image = icon_image(group.icon, size)
        self.image.set_halign(Gtk.Align.CENTER)
        self.image.set_valign(Gtk.Align.CENTER)
        self.indicator = add_class(Gtk.Box(), "tw-app-indicator")
        self.indicator.set_valign(Gtk.Align.END)
        self.indicator.set_halign(Gtk.Align.CENTER)
        self.title = None
        if group.single_window:
            # "Never combine": icon plus window title, like Windows 10.
            row = Gtk.Box(spacing=8)
            row.pack_start(self.image, False, False, 0)
            self.title = Gtk.Label(xalign=0)
            self.title.set_ellipsize(Pango.EllipsizeMode.END)
            self.title.set_width_chars(14)
            self.title.set_max_width_chars(14)
            row.pack_start(self.title, True, True, 0)
            overlay.add(row)
            add_class(self.button, "labelled")
            self.indicator.set_halign(Gtk.Align.FILL)
        else:
            overlay.add(self.image)
        overlay.add_overlay(self.indicator)
        self.button.add(overlay)
        self.button.set_size_request(-1, taskbar_height())
        self.add(self.button)
        self.button.connect("button-release-event", self._on_release)
        self.button.connect("query-tooltip", self._on_tooltip)
        self.button.set_has_tooltip(True)
        self._setup_dnd()
        self.update()

    def update(self):
        windows = self.group.windows
        set_class(self.button, "running", bool(windows))
        set_class(self.button, "active", any(w.activated and not w.minimized for w in windows))
        set_class(self.button, "stacked", len(windows) > 1)
        if self.title is not None and windows:
            self.title.set_text(windows[0].title or self.group.name)

    # Drag pinned apps to reorder them; drop Start menu apps to pin them.
    def _setup_dnd(self):
        targets = [Gtk.TargetEntry.new(DND_TASKBAR, Gtk.TargetFlags.SAME_APP, 0),
                   Gtk.TargetEntry.new(DND_TILE, Gtk.TargetFlags.SAME_APP, 1)]
        if self.group.info is not None:
            self.button.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, targets[:1], Gdk.DragAction.MOVE)
            self.button.drag_source_set_icon_gicon(self.group.icon) if self.group.icon else None
            self.button.connect("drag-data-get", lambda _w, _c, data, _i, _t: data.set(
                data.get_target(), 8, self.group.info.get_id().encode()))
        self.button.drag_dest_set(Gtk.DestDefaults.ALL, targets, Gdk.DragAction.MOVE)
        self.button.connect("drag-data-received", self._on_drop)

    def _on_drop(self, _widget, _context, _x, _y, data, info_type, _time):
        raw = data.get_data().decode()
        desktop_id = raw[4:] if info_type == 1 and raw.startswith("app:") else (raw if info_type == 0 else None)
        if not desktop_id:
            return
        before = self.group.info.get_id() if self.group.info is not None else None
        if before == desktop_id:
            return
        self.shell.apps.move_pinned(desktop_id, before)

    def _on_tooltip(self, _widget, _x, _y, _keyboard, tooltip):
        if self.group.windows:
            tooltip.set_text("\n".join(w.title or self.group.name for w in self.group.windows))
        else:
            tooltip.set_text(self.group.name)
        return True

    def _on_release(self, _widget, event):
        self.shell.close_popups()
        if event.button == 1:
            self.activate()
        elif event.button == 2:
            self.launch()
        elif event.button == 3:
            self.show_menu(event)
        return True

    def launch(self):
        if self.group.info is not None:
            self.shell.apps.launch(self.group.info)

    def activate(self):
        windows = self.group.windows
        if not windows:
            self.launch()
        elif len(windows) == 1:
            self.shell.wm.toggle(windows[0])
        else:
            self.shell.window_list.show_for(self, windows)

    def show_menu(self, event):
        menu = Gtk.Menu()
        info = self.group.info
        if info is not None:
            for action in info.list_actions()[:5]:
                menu.append(menu_item(info.get_action_name(action),
                                      lambda a=action: self.shell.apps.launch(info, action=a)))
            if info.list_actions():
                menu.append(Gtk.SeparatorMenuItem())
            menu.append(menu_item(info.get_display_name(), self.launch, info.get_icon()))
            if self.shell.apps.is_pinned(info):
                menu.append(menu_item(_("Unpin from taskbar"),
                                      lambda: self.shell.apps.set_pinned(info, False), "tenwin-unpin"))
            else:
                menu.append(menu_item(_("Pin to taskbar"),
                                      lambda: self.shell.apps.set_pinned(info, True), "tenwin-pin"))
        if self.group.windows:
            label = _("Close window") if len(self.group.windows) == 1 else _("Close all windows")
            menu.append(menu_item(label, self._close_all, "tenwin-close"))
        popup_menu(menu, event=event)

    def _close_all(self):
        for window in self.group.windows:
            self.shell.wm.close(window)


class Clock(Gtk.EventBox):
    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.button = flat_button(css="tw-clock")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_valign(Gtk.Align.CENTER)
        self.time_label = Gtk.Label(justify=Gtk.Justification.CENTER)
        self.date_label = Gtk.Label(justify=Gtk.Justification.CENTER)
        box.pack_start(self.time_label, False, False, 0)
        box.pack_start(self.date_label, False, False, 0)
        self.button.add(box)
        self.add(self.button)
        self.button.connect("clicked", lambda *_: shell.toggle_popup(shell.calendar))
        self.button.set_has_tooltip(True)
        self.button.connect("query-tooltip", self._tooltip)
        self.update()
        self._schedule()

    def _schedule(self):
        now = GLib.DateTime.new_now_local()
        seconds = get_settings()["region.clock_seconds"]
        delay = 1000 - now.get_microsecond() // 1000 if seconds else \
            (60 - now.get_second()) * 1000 - now.get_microsecond() // 1000
        GLib.timeout_add(max(50, delay), self._tick)

    def _tick(self):
        self.update()
        self._schedule()
        return GLib.SOURCE_REMOVE

    def update(self):
        settings = get_settings()
        now = GLib.DateTime.new_now_local()
        if settings["region.clock_24h"]:
            fmt = "%H:%M:%S" if settings["region.clock_seconds"] else "%H:%M"
        else:
            fmt = "%l:%M:%S %p" if settings["region.clock_seconds"] else "%l:%M %p"
        self.time_label.set_text(now.format(fmt).strip())
        small = settings["taskbar.small_icons"]
        self.date_label.set_visible(not small)
        self.date_label.set_no_show_all(small)
        self.date_label.set_text(now.format("%x"))

    def _tooltip(self, _w, _x, _y, _k, tooltip):
        tooltip.set_text(GLib.DateTime.new_now_local().format("%A, %e. %B %Y").replace("  ", " ")
                         if _lang_de() else GLib.DateTime.new_now_local().format("%A, %B %e, %Y"))
        return True


def _lang_de():
    from tenwin.i18n import current_language
    return current_language() == "de"


class StatusIcon(Gtk.EventBox):
    """Network / volume / battery icon in the notification area."""

    def __init__(self, icon_name, on_click, tooltip_func, on_scroll=None):
        super().__init__()
        self.button = flat_button(css="tw-tray-item")
        self.image = icon_image(icon_name, 16, symbolic=True)
        self.button.add(self.image)
        self.add(self.button)
        self.button.connect("clicked", lambda *_: on_click())
        self.button.set_has_tooltip(True)
        self.button.connect("query-tooltip", lambda _w, _x, _y, _k, t: t.set_text(tooltip_func()) or True)
        if on_scroll:
            self.button.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
            self.button.connect("scroll-event", lambda _w, e: on_scroll(e) or True)

    def set_icon(self, icon_name):
        set_icon(self.image, icon_name, 16, symbolic=True)


class Taskbar(LayerWindow):
    def __init__(self, shell, monitor):
        edge = taskbar_edge()
        super().__init__("tenwin-taskbar", layer=Layer.TOP, anchors=(edge, Edge.LEFT, Edge.RIGHT),
                         monitor=monitor, exclusive="auto", css="tw-surface tw-taskbar")
        self.shell = shell
        self.monitor = monitor
        self.app_buttons = {}
        self.app_box = Gtk.Box()
        self._build()
        self.connect("button-release-event", self._on_background_click)
        self.show_all()

    # -- layout ----------------------------------------------------------

    def _build(self):
        settings = get_settings()
        set_class(self, "small", settings["taskbar.small_icons"])
        height = taskbar_height()
        self.set_size_request(-1, height)
        root = Gtk.Box()
        root.set_size_request(-1, height)
        self.add(root)

        left = Gtk.Box()
        root.pack_start(left, True, True, 0)

        self.start_button = flat_button(css="tw-tb-button tw-start-button", tooltip=_("Start"))
        self.start_button.add(icon_image("tenwin-start", 16, symbolic=True))
        self.start_button.connect("button-release-event", self._on_start_click)
        left.pack_start(self.start_button, False, False, 0)

        mode = settings["taskbar.search"]
        if mode == "box":
            search = flat_button(css="tw-search-box")
            box = Gtk.Box(spacing=10)
            box.pack_start(icon_image("tenwin-search", 16, symbolic=True), False, False, 0)
            placeholder = Gtk.Label(label=_("Type here to search"), xalign=0)
            placeholder.set_ellipsize(Pango.EllipsizeMode.END)
            box.pack_start(placeholder, True, True, 0)
            search.add(box)
            search.connect("clicked", lambda *_: self.shell.toggle_popup(self.shell.search, self.monitor))
            left.pack_start(search, False, False, 0)
        elif mode == "icon":
            search = flat_button(icon_image("tenwin-search", 16, symbolic=True), "tw-tb-button", _("Search"))
            search.connect("clicked", lambda *_: self.shell.toggle_popup(self.shell.search, self.monitor))
            left.pack_start(search, False, False, 0)

        if settings["taskbar.show_taskview"]:
            tv = flat_button(icon_image("tenwin-taskview", 16, symbolic=True), "tw-tb-button", _("Task View"))
            tv.connect("clicked", lambda *_: self.shell.command("task-view"))
            left.pack_start(tv, False, False, 0)

        left.pack_start(self.app_box, False, False, 0)

        right = Gtk.Box()
        root.pack_end(right, False, False, 0)
        right.pack_start(self.shell.tray.create_widget(self), False, False, 0)

        self.network_icon = StatusIcon(self.shell.network.icon_name(),
                                       lambda: self.shell.toggle_popup(self.shell.network_flyout, self.monitor),
                                       self._network_tooltip)
        right.pack_start(self.network_icon, False, False, 0)
        self.volume_icon = StatusIcon(self.shell.audio.icon_name(),
                                      lambda: self.shell.toggle_popup(self.shell.volume_flyout, self.monitor),
                                      self._volume_tooltip, self._volume_scroll)
        right.pack_start(self.volume_icon, False, False, 0)
        self.battery_icon = StatusIcon(self.shell.power.icon_name(),
                                       lambda: self.shell.toggle_popup(self.shell.battery_flyout, self.monitor),
                                       self._battery_tooltip)
        right.pack_start(self.battery_icon, False, False, 0)
        self.battery_icon.set_no_show_all(True)
        self.battery_icon.set_visible(self.shell.power.has_battery)

        self.layout_label = None
        layouts = [l for l in settings["input.keyboard_layouts"].split(",") if l]
        if len(layouts) > 1:
            self.layout_label = Gtk.Label(label=layouts[0][:3].upper())
            add_class(self.layout_label, "tw-lang")
            self.layout_label.set_tooltip_text(_("Switch input language: Win+Space"))
            right.pack_start(self.layout_label, False, False, 0)

        self.clock = Clock(self.shell)
        right.pack_start(self.clock, False, False, 0)

        ac = flat_button(css="tw-ac-button", tooltip=_("Action center"))
        overlay = Gtk.Overlay()
        self.ac_image = icon_image("tenwin-action-center", 16, symbolic=True)
        overlay.add(self.ac_image)
        self.badge = add_class(Gtk.Label(), "tw-badge")
        self.badge.set_halign(Gtk.Align.END)
        self.badge.set_valign(Gtk.Align.START)
        self.badge.set_no_show_all(True)
        overlay.add_overlay(self.badge)
        ac.add(overlay)
        ac.connect("clicked", lambda *_: self.shell.toggle_popup(self.shell.action_center, self.monitor))
        right.pack_start(ac, False, False, 0)

        if settings["taskbar.show_desktop_button"]:
            show_desktop = flat_button(css="tw-show-desktop", tooltip=_("Show desktop"))
            show_desktop.connect("clicked", lambda *_: self.shell.command("show-desktop"))
            right.pack_start(show_desktop, False, False, 0)

        self.refresh_apps()
        self.update_status()

    def rebuild(self):
        for child in self.get_children():
            self.remove(child)
            child.destroy()
        self.app_box = Gtk.Box()
        self.app_buttons = {}
        self.set_anchors((taskbar_edge(), Edge.LEFT, Edge.RIGHT))
        self._build()
        self.show_all()

    # -- updates -----------------------------------------------------------

    def refresh_apps(self):
        groups = group_windows(self.shell)
        keys = [g.key for g in groups]
        if keys != list(self.app_buttons):
            for button in self.app_buttons.values():
                self.app_box.remove(button)
                button.destroy()
            self.app_buttons = {}
            for group in groups:
                button = AppButton(self, group)
                self.app_buttons[group.key] = button
                self.app_box.pack_start(button, False, False, 0)
            self.app_box.show_all()
        else:
            for group in groups:
                button = self.app_buttons[group.key]
                button.group = group
                button.update()

    def app_groups(self):
        return [b.group for b in self.app_buttons.values()]

    def update_status(self):
        self.network_icon.set_icon(self.shell.network.icon_name())
        self.volume_icon.set_icon(self.shell.audio.icon_name())
        has_battery = self.shell.power.has_battery
        self.battery_icon.set_visible(has_battery)
        if has_battery:
            self.battery_icon.set_icon(self.shell.power.icon_name())

    def set_notification_count(self, count, dnd=False):
        icon = "tenwin-focus-assist" if dnd else ("tenwin-action-center-new" if count else "tenwin-action-center")
        set_icon(self.ac_image, icon, 16, symbolic=True)
        self.badge.set_text(str(count) if count < 100 else "99+")
        self.badge.set_visible(bool(count) and not dnd)

    def set_start_open(self, is_open):
        set_class(self.start_button, "open", is_open)

    # -- events ------------------------------------------------------------

    def _on_start_click(self, _widget, event):
        if event.button == 3:
            self.shell.close_popups()
            self.shell.winx.show_at(self.start_button)
        else:
            self.shell.toggle_popup(self.shell.start_menu, self.monitor)
        return True

    def _on_background_click(self, _widget, event):
        if event.button != 3:
            return False
        self.shell.close_popups()
        settings = get_settings()

        def choice(text, key, value):
            mark = "•  " if settings[key] == value else "     "
            return menu_item(mark + text, lambda: settings.set(key, value))

        def toggle(text, key):
            mark = "✓  " if settings[key] else "     "
            return menu_item(mark + text, lambda: settings.set(key, not settings[key]))

        menu = Gtk.Menu()
        search = Gtk.MenuItem(label=_("Search"))
        sub = add_class(Gtk.Menu(), "tw-menu")
        sub.append(choice(pgettext("taskbar", "Hidden"), "taskbar.search", "hidden"))
        sub.append(choice(_("Show search icon"), "taskbar.search", "icon"))
        sub.append(choice(_("Show search box"), "taskbar.search", "box"))
        search.set_submenu(sub)
        menu.append(search)
        menu.append(toggle(_("Show Task View button"), "taskbar.show_taskview"))
        menu.append(toggle(_("Show the \"Show desktop\" button"), "taskbar.show_desktop_button"))
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(toggle(_("Use small taskbar buttons"), "taskbar.small_icons"))
        never = settings["taskbar.combine"] == "never"
        menu.append(menu_item(("✓  " if never else "     ") + _("Show window titles (never combine)"),
                              lambda: settings.set("taskbar.combine", "always" if never else "never")))
        menu.append(toggle(_("Always show all icons in the notification area"), "taskbar.tray_show_all"))
        position = Gtk.MenuItem(label=_("Taskbar location on screen"))
        sub = add_class(Gtk.Menu(), "tw-menu")
        sub.append(choice(_("Bottom"), "taskbar.position", "bottom"))
        sub.append(choice(_("Top"), "taskbar.position", "top"))
        position.set_submenu(sub)
        menu.append(position)
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(menu_item(_("Task Manager"), lambda: self.shell.command("task-manager")))
        menu.append(menu_item(_("Show the desktop"), lambda: self.shell.command("show-desktop")))
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(menu_item(_("Taskbar settings"), lambda: self.shell.open_settings("taskbar"),
                              "tenwin-settings"))
        popup_menu(menu, event=event)
        return True

    def _network_tooltip(self):
        kind, name, _strength = self.shell.network.primary()
        if kind == "none":
            return _("Not connected")
        return "%s\n%s" % (name, _("Internet access"))

    def _volume_tooltip(self):
        audio = self.shell.audio
        if audio.sink is None:
            return _("No audio output device is installed")
        return "%s: %s" % (audio.sink.description,
                           _("Muted") if audio.muted else "%d %%" % audio.volume)

    def _volume_scroll(self, event):
        delta = 0
        if event.direction == Gdk.ScrollDirection.UP:
            delta = 2
        elif event.direction == Gdk.ScrollDirection.DOWN:
            delta = -2
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            delta = -2 if event.delta_y > 0 else 2
        if delta:
            self.shell.audio.change_volume(delta)

    def _battery_tooltip(self):
        power = self.shell.power
        text = "%d %%" % power.percent
        if power.charging:
            text += " " + _("(charging)")
        elif power.time_to_empty:
            hours, minutes = divmod(power.time_to_empty // 60, 60)
            text += " " + _("remaining: %d h %02d min") % (hours, minutes)
        return text

