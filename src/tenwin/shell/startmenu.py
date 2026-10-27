"""The Start menu: rail, alphabetical app list and live tiles."""

import os
import shutil

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from tenwin import paths
from tenwin.apps import first_letter
from tenwin.config import get_settings
from tenwin.gtkutil import (add_class, clear_children, flat_button, icon_image, menu_item,
                            popup_menu, set_class)
from tenwin.i18n import N_, _
from tenwin.services import system
from tenwin.shell.layer import Edge, Popup, taskbar_edge

CELL = 48
GAP = 4
COLUMNS = 6  # small-tile columns per group (= 3 medium tiles)
SIZES = {"small": (1, 1), "medium": (2, 2), "wide": (4, 2), "large": (4, 4)}

DEFAULT_GROUPS = [
    (N_("Productivity"), [
        ("org.gnome.Calendar.desktop", "medium"),
        ("thunderbird.desktop", "wide"), ("thunderbird_thunderbird.desktop", "wide"),
        ("org.gnome.Evolution.desktop", "wide"),
        ("firefox_firefox.desktop", "medium"), ("firefox.desktop", "medium"),
        ("libreoffice-writer.desktop", "small"), ("libreoffice-calc.desktop", "small"),
        ("libreoffice-impress.desktop", "small"), ("org.tenwin.Explorer.desktop", "small"),
        ("org.gnome.TextEditor.desktop", "medium"), ("org.gnome.gedit.desktop", "medium"),
    ]),
    (N_("Explore"), [
        ("snap-store_snap-store.desktop", "wide"), ("org.gnome.Software.desktop", "wide"),
        ("org.gnome.Weather.desktop", "medium"), ("org.gnome.Calculator.desktop", "medium"),
        ("org.gnome.Loupe.desktop", "medium"), ("org.gnome.eog.desktop", "medium"),
        ("org.gnome.Totem.desktop", "medium"), ("rhythmbox.desktop", "medium"),
        ("org.tenwin.Settings.desktop", "medium"), ("org.gnome.Terminal.desktop", "small"),
        ("gnome-system-monitor.desktop", "small"), ("org.gnome.SystemMonitor.desktop", "small"),
    ]),
]

CALENDAR_APPS = {"org.gnome.Calendar.desktop", "gnome-calendar.desktop"}


def default_tiles(apps):
    groups = []
    for name, candidates in DEFAULT_GROUPS:
        tiles, seen = [], set()
        for desktop_id, size in candidates:
            info = apps.get(desktop_id)
            if info is None or not info.should_show():
                continue
            # Skip alternatives of the same program (snap vs. deb).
            base = desktop_id.split("_")[0].split(".desktop")[0].rsplit(".", 1)[-1].lower()
            if base in seen:
                continue
            seen.add(base)
            tiles.append({"app": info.get_id(), "size": size})
            if len(tiles) >= 6:
                break
        if tiles:
            groups.append({"name": _(name), "tiles": tiles})
    return groups


def layout_tiles(tiles, columns=COLUMNS):
    """First-fit placement. Returns [(tile, col, row, w, h)] and the row count."""
    occupied = set()
    placed = []
    rows = 0
    for tile in tiles:
        w, h = SIZES.get(tile.get("size"), SIZES["medium"])
        w = min(w, columns)
        row = 0
        while True:
            spot = None
            for col in range(0, columns - w + 1):
                cells = {(col + dx, row + dy) for dx in range(w) for dy in range(h)}
                if not cells & occupied:
                    spot = col
                    break
            if spot is not None:
                occupied |= {(spot + dx, row + dy) for dx in range(w) for dy in range(h)}
                placed.append((tile, spot, row, w, h))
                rows = max(rows, row + h)
                break
            row += 1
    return placed, rows


class StartMenu(Popup):
    def __init__(self, shell):
        super().__init__("tenwin-start", anchors=(taskbar_edge(), Edge.LEFT))
        self.shell = shell
        self.settings = get_settings()
        self.letter_rows = {}
        self.rail_expanded = False
        self._build()
        self.connect("key-press-event", self._on_key_typing)
        shell.apps.connect("changed", lambda *_: self.populate())
        self.settings.connect("changed", self._on_settings)

    # -- construction ------------------------------------------------------

    def _build(self):
        frame = add_class(Gtk.Box(), "tw-panel", "tw-start")
        self.add(frame)
        overlay = Gtk.Overlay()
        frame.pack_start(overlay, True, True, 0)

        content = Gtk.Box()
        overlay.add(content)
        spacer = Gtk.Box()
        spacer.set_size_request(48, -1)
        content.pack_start(spacer, False, False, 0)

        self.list_stack = Gtk.Stack()
        self.list_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.list_stack.set_size_request(272, -1)
        self.list_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.list_box = add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "tw-applist")
        self.list_scroll.add(self.list_box)
        self.list_stack.add_named(self.list_scroll, "list")
        self.letter_grid = add_class(Gtk.FlowBox(), "tw-letter-grid")
        self.letter_grid.set_max_children_per_line(4)
        self.letter_grid.set_min_children_per_line(4)
        self.letter_grid.set_selection_mode(Gtk.SelectionMode.NONE)
        self.letter_grid.set_valign(Gtk.Align.CENTER)
        self.letter_grid.set_halign(Gtk.Align.CENTER)
        self.list_stack.add_named(self.letter_grid, "letters")
        content.pack_start(self.list_stack, False, False, 0)
        self.list_stack.show_all()

        self.tile_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.tile_area = Gtk.Box(spacing=24)
        self.tile_area.set_margin_start(8)
        self.tile_area.set_margin_end(20)
        self.tile_area.set_margin_bottom(12)
        self.tile_scroll.add(self.tile_area)
        content.pack_start(self.tile_scroll, True, True, 0)

        self.rail = self._build_rail()
        self.rail.set_halign(Gtk.Align.START)
        overlay.add_overlay(self.rail)
        self.populate()

    def _build_rail(self):
        rail = add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "tw-start-rail")
        self.rail_labels = []

        def rail_button(icon, text, callback):
            button = flat_button(css="tw-rail-button", tooltip=text)
            box = Gtk.Box(spacing=0)
            image = icon_image(icon, 16, symbolic=True)
            image.set_size_request(48, 48)
            box.pack_start(image, False, False, 0)
            revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_RIGHT,
                                    transition_duration=120)
            lbl = Gtk.Label(label=text, xalign=0)
            lbl.set_size_request(200, -1)
            revealer.add(lbl)
            box.pack_start(revealer, True, True, 0)
            button.add(box)
            button.connect("clicked", lambda b: callback(b))
            self.rail_labels.append(revealer)
            return button

        rail.pack_start(rail_button("tenwin-hamburger", _("START"), lambda _b: self.toggle_rail()),
                        False, False, 0)
        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        rail.pack_end(bottom, False, False, 0)
        user = GLib.get_real_name() if GLib.get_real_name() not in ("", "Unknown") else GLib.get_user_name()
        bottom.pack_start(rail_button("tenwin-user", user, self._user_menu), False, False, 0)
        folders = self.settings["start.folders"]
        entries = {
            "documents": ("tenwin-documents", _("Documents"), lambda _b: self._open_dir("DOCUMENTS")),
            "downloads": ("tenwin-downloads", _("Downloads"), lambda _b: self._open_dir("DOWNLOAD")),
            "music": ("tenwin-music", _("Music"), lambda _b: self._open_dir("MUSIC")),
            "pictures": ("tenwin-pictures", _("Pictures"), lambda _b: self._open_dir("PICTURES")),
            "videos": ("tenwin-videos", _("Videos"), lambda _b: self._open_dir("VIDEOS")),
            "explorer": ("tenwin-explorer", _("File Explorer"), lambda _b: self._run_ctl("explorer")),
            "settings": ("tenwin-settings", _("Settings"), lambda _b: self._run_ctl("settings")),
        }
        for key in ("explorer", "documents", "downloads", "music", "pictures", "videos", "settings"):
            if key in folders:
                icon, text, cb = entries[key]
                bottom.pack_start(rail_button(icon, text, cb), False, False, 0)
        bottom.pack_start(rail_button("tenwin-power", _("Power"), self._power_menu), False, False, 0)
        return rail

    def toggle_rail(self, expanded=None):
        self.rail_expanded = (not self.rail_expanded) if expanded is None else expanded
        for revealer in self.rail_labels:
            revealer.set_reveal_child(self.rail_expanded)
        set_class(self.rail, "expanded", self.rail_expanded)

    # -- content -----------------------------------------------------------

    def populate(self):
        self._populate_list()
        self._populate_tiles()

    def _section_title(self, text):
        return add_class(Gtk.Label(label=text, xalign=0), "tw-section-title")

    def _populate_list(self):
        clear_children(self.list_box)
        self.letter_rows = {}
        apps = self.shell.apps
        if self.settings["start.show_recently_added"]:
            recent = apps.recently_added()
            if recent:
                self.list_box.pack_start(self._section_title(_("Recently added")), False, False, 0)
                for info in recent:
                    self.list_box.pack_start(self._app_row(info), False, False, 0)
        if self.settings["start.show_most_used"]:
            used = apps.most_used()
            if used:
                self.list_box.pack_start(self._section_title(_("Most used")), False, False, 0)
                for info in used:
                    self.list_box.pack_start(self._app_row(info), False, False, 0)
        current = None
        for info in apps.apps:
            letter = first_letter(info.get_display_name())
            if letter != current:
                current = letter
                header = flat_button(css="tw-letter")
                header.add(Gtk.Label(label=letter, xalign=0))
                header.connect("clicked", lambda *_: self._show_letters())
                self.letter_rows[letter] = header
                self.list_box.pack_start(header, False, False, 0)
            self.list_box.pack_start(self._app_row(info), False, False, 0)
        self.list_box.show_all()

        clear_children(self.letter_grid)
        for letter in ["#"] + [chr(c) for c in range(ord("A"), ord("Z") + 1)]:
            button = flat_button(Gtk.Label(label=letter))
            button.set_sensitive(letter in self.letter_rows)
            button.connect("clicked", lambda _b, l=letter: self._jump_to(l))
            self.letter_grid.add(button)
        self.letter_grid.show_all()

    def _app_row(self, info):
        button = flat_button(css="tw-app-row")
        box = Gtk.Box(spacing=12)
        icon_box = add_class(Gtk.Box(), "tw-app-icon", "plain")
        icon = icon_image(info.get_icon(), 24)
        icon.set_size_request(32, 32)
        icon_box.pack_start(icon, True, True, 0)
        box.pack_start(icon_box, False, False, 0)
        name = Gtk.Label(label=info.get_display_name(), xalign=0)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        box.pack_start(name, True, True, 0)
        button.add(box)
        button.set_tooltip_text(info.get_description() or info.get_display_name())
        button.connect("clicked", lambda *_: self.launch(info))
        button.connect("button-release-event", lambda _w, e: self._app_menu(info, e) if e.button == 3 else False)
        self._make_drag_source(button, info.get_id())
        return button

    def _show_letters(self):
        self.list_stack.set_visible_child_name("letters")

    def _jump_to(self, letter):
        self.list_stack.set_visible_child_name("list")
        row = self.letter_rows.get(letter)
        if row is None:
            return
        def scroll():
            alloc = row.get_allocation()
            self.list_scroll.get_vadjustment().set_value(alloc.y)
            return False
        GLib.idle_add(scroll)

    # -- tiles -------------------------------------------------------------

    def tile_groups(self):
        groups = self.settings["start.tiles"]
        if groups is None:
            groups = default_tiles(self.shell.apps)
        return groups

    def save_groups(self, groups):
        self.settings.set("start.tiles", groups)

    def _populate_tiles(self):
        clear_children(self.tile_area)
        groups = [g for g in self.tile_groups() if g.get("tiles")]
        columns = [Gtk.Box(orientation=Gtk.Orientation.VERTICAL), Gtk.Box(orientation=Gtk.Orientation.VERTICAL)]
        for col in columns:
            col.set_size_request(COLUMNS * CELL + (COLUMNS - 1) * GAP, -1)
            self.tile_area.pack_start(col, False, False, 0)
        if not groups:
            hint = add_class(Gtk.Label(label=_("Right-click an app and choose \"Pin to Start\"."),
                                       xalign=0, wrap=True), "tw-dim-text")
            hint.set_max_width_chars(30)
            hint.set_margin_top(16)
            columns[0].pack_start(hint, False, False, 0)
        for index, group in enumerate(groups):
            target = columns[index % 2] if len(groups) > 1 else columns[0]
            target.pack_start(self._group_widget(group, index), False, False, 0)
        if len(groups) <= 1:
            columns[1].destroy()
        self.tile_area.show_all()

    def _group_widget(self, group, group_index):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        title_stack = Gtk.Stack()
        title_button = flat_button(css="tw-tile-group-title")
        title_label = Gtk.Label(label=group.get("name") or _("Name group"), xalign=0)
        title_button.add(title_label)
        entry = Gtk.Entry(text=group.get("name", ""))
        title_stack.add_named(title_button, "label")
        title_stack.add_named(entry, "entry")

        def start_edit(*_args):
            title_stack.set_visible_child_name("entry")
            entry.grab_focus()

        def finish_edit(*_args):
            groups = self.tile_groups()
            if group_index < len(groups):
                groups[group_index]["name"] = entry.get_text().strip()
                self.save_groups(groups)

        title_button.connect("clicked", start_edit)
        entry.connect("activate", finish_edit)
        box.pack_start(title_stack, False, False, 0)

        grid = Gtk.Fixed()
        placed, rows = layout_tiles(group["tiles"])
        for tile, col, row, w, h in placed:
            widget = self._tile_widget(tile, group_index, w, h)
            if widget is not None:
                grid.put(widget, col * (CELL + GAP), row * (CELL + GAP))
        grid.set_size_request(COLUMNS * CELL + (COLUMNS - 1) * GAP, max(0, rows * (CELL + GAP) - GAP))
        box.pack_start(grid, False, False, 0)
        box.set_margin_bottom(12)
        return box

    def _tile_widget(self, tile, group_index, w, h):
        info = self.shell.apps.get(tile.get("app"))
        if info is None:
            return None
        width, height = w * CELL + (w - 1) * GAP, h * CELL + (h - 1) * GAP
        button = flat_button(css="tw-tile")
        button.set_size_request(width, height)
        overlay = Gtk.Overlay()
        size = tile.get("size", "medium")
        icon_px = {"small": 24, "medium": 32, "wide": 32, "large": 64}[size]
        if info.get_id() in CALENDAR_APPS and size != "small":
            now = GLib.DateTime.new_now_local()
            center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            center.set_valign(Gtk.Align.CENTER)
            center.pack_start(Gtk.Label(label=now.format("%A")), False, False, 0)
            center.pack_start(add_class(Gtk.Label(label=str(now.get_day_of_month())), "tw-tile-big"),
                              False, False, 0)
            overlay.add(center)
        else:
            overlay.add(icon_image(info.get_icon(), icon_px))
        if size != "small":
            name = Gtk.Label(label=info.get_display_name(), xalign=0)
            name.set_ellipsize(Pango.EllipsizeMode.END)
            name.set_halign(Gtk.Align.START)
            name.set_valign(Gtk.Align.END)
            name.set_margin_start(6)
            name.set_margin_bottom(4)
            name.set_max_width_chars(12 if size == "medium" else 26)
            overlay.add_overlay(name)
        button.add(overlay)
        button.set_tooltip_text(info.get_display_name())
        button.connect("clicked", lambda *_: self.launch(info))
        button.connect("button-release-event",
                       lambda _w, e: self._tile_menu(tile, group_index, info, e) if e.button == 3 else False)
        self._make_drag_source(button, info.get_id())
        self._make_drop_target(button, group_index, tile)
        return button

    # -- drag and drop ------------------------------------------------------

    TARGETS = [Gtk.TargetEntry.new("application/x-tenwin-app", Gtk.TargetFlags.SAME_APP, 0)]

    def _make_drag_source(self, widget, desktop_id):
        widget.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, self.TARGETS, Gdk.DragAction.MOVE)
        widget.connect("drag-data-get", lambda _w, _c, data, _i, _t:
                       data.set(data.get_target(), 8, desktop_id.encode()))

    def _make_drop_target(self, widget, group_index, tile):
        widget.drag_dest_set(Gtk.DestDefaults.ALL, self.TARGETS, Gdk.DragAction.MOVE)
        widget.connect("drag-motion", lambda *_: add_class(widget, "drop-target") and False)
        widget.connect("drag-leave", lambda *_: set_class(widget, "drop-target", False))
        widget.connect("drag-data-received",
                       lambda _w, _c, _x, _y, data, _i, _t: self._drop(data.get_data().decode(), group_index, tile))

    def _drop(self, desktop_id, group_index, before_tile):
        groups = self.tile_groups()
        moving = None
        for group in groups:
            for tile in list(group["tiles"]):
                if tile["app"] == desktop_id:
                    moving = tile
                    group["tiles"].remove(tile)
        if moving is None:
            moving = {"app": desktop_id, "size": "medium"}
        target = groups[group_index]["tiles"] if group_index < len(groups) else groups[-1]["tiles"]
        index = len(target)
        for i, tile in enumerate(target):
            if tile["app"] == before_tile["app"]:
                index = i
                break
        target.insert(index, moving)
        self.save_groups([g for g in groups if g["tiles"]])

    # -- context menus -----------------------------------------------------

    def is_pinned_start(self, info):
        return any(t["app"] == info.get_id() for g in self.tile_groups() for t in g["tiles"])

    def pin_start(self, info, pinned=True):
        groups = self.tile_groups()
        if pinned:
            if not groups:
                groups = [{"name": "", "tiles": []}]
            groups[-1]["tiles"].append({"app": info.get_id(), "size": "medium"})
        else:
            for group in groups:
                group["tiles"] = [t for t in group["tiles"] if t["app"] != info.get_id()]
        self.save_groups([g for g in groups if g["tiles"] or g.get("name")])

    def _app_menu(self, info, event):
        menu = Gtk.Menu()
        if self.is_pinned_start(info):
            menu.append(menu_item(_("Unpin from Start"), lambda: self.pin_start(info, False), "tenwin-unpin"))
        else:
            menu.append(menu_item(_("Pin to Start"), lambda: self.pin_start(info, True), "tenwin-pin"))
        more = Gtk.MenuItem(label=_("More"))
        sub = Gtk.Menu()
        if self.shell.apps.is_pinned(info):
            sub.append(menu_item(_("Unpin from taskbar"), lambda: self.shell.apps.set_pinned(info, False)))
        else:
            sub.append(menu_item(_("Pin to taskbar"), lambda: self.shell.apps.set_pinned(info, True)))
        if info.get_filename():
            sub.append(menu_item(_("Open file location"),
                                 lambda: self._run_ctl("explorer", os.path.dirname(info.get_filename()))))
        add_class(sub, "tw-menu")
        more.set_submenu(sub)
        menu.append(more)
        if shutil.which("gnome-software") or shutil.which("snap-store"):
            menu.append(menu_item(_("Uninstall"), lambda: self._uninstall(info), "tenwin-delete"))
        popup_menu(menu, event=event)
        return True

    def _tile_menu(self, tile, group_index, info, event):
        menu = Gtk.Menu()
        menu.append(menu_item(_("Unpin from Start"), lambda: self.pin_start(info, False), "tenwin-unpin"))
        resize = Gtk.MenuItem(label=_("Resize"))
        sub = Gtk.Menu()
        for size, text in (("small", _("Small")), ("medium", _("Medium")), ("wide", _("Wide")),
                           ("large", _("Large"))):
            item = menu_item(("✓  " if tile.get("size") == size else "     ") + text,
                             lambda s=size: self._resize(group_index, tile, s))
            sub.append(item)
        add_class(sub, "tw-menu")
        resize.set_submenu(sub)
        menu.append(resize)
        if self.shell.apps.is_pinned(info):
            menu.append(menu_item(_("Unpin from taskbar"), lambda: self.shell.apps.set_pinned(info, False)))
        else:
            menu.append(menu_item(_("Pin to taskbar"), lambda: self.shell.apps.set_pinned(info, True)))
        popup_menu(menu, event=event)
        return True

    def _resize(self, group_index, tile, size):
        groups = self.tile_groups()
        for t in groups[group_index]["tiles"]:
            if t["app"] == tile["app"]:
                t["size"] = size
        self.save_groups(groups)

    def _uninstall(self, info):
        self.close_popup()
        if shutil.which("gnome-software"):
            system.run(["gnome-software", "--details=%s" % info.get_id()])
        else:
            system.run(["snap-store"])

    def _user_menu(self, button):
        menu = Gtk.Menu()
        menu.append(menu_item(_("Change account settings"), lambda: self.shell.open_settings("accounts")))
        menu.append(menu_item(_("Lock"), lambda: self.shell.command("lock")))
        menu.append(menu_item(_("Sign out"), lambda: self.shell.command("logout")))
        popup_menu(menu, widget=button)

    def _power_menu(self, button):
        menu = Gtk.Menu()
        menu.append(menu_item(_("Sleep"), lambda: self.shell.command("suspend"), "tenwin-sleep"))
        menu.append(menu_item(_("Shut down"), lambda: self.shell.command("poweroff"), "tenwin-power"))
        menu.append(menu_item(_("Restart"), lambda: self.shell.command("reboot"), "tenwin-restart"))
        popup_menu(menu, widget=button)

    # -- actions -----------------------------------------------------------

    def launch(self, info):
        self.close_popup()
        self.shell.apps.launch(info)

    def _open_dir(self, kind):
        self._run_ctl("explorer", paths.xdg_user_dir(kind))

    def _run_ctl(self, what, arg=None):
        self.close_popup()
        self.shell.command(what if arg is None else "%s %s" % (what, Gio.File.new_for_path(arg).get_uri()))

    def _on_key_typing(self, _widget, event):
        if event.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK):
            return False
        char = Gdk.keyval_to_unicode(event.keyval)
        if char and chr(char).isprintable() and not chr(char).isspace():
            self.close_popup()
            self.shell.search.open_with_text(chr(char), self.shell.current_monitor)
            return True
        return False

    def _on_settings(self, _settings, keys):
        if keys & {"start.tiles", "start.show_most_used", "start.show_recently_added"}:
            self.populate()
        if "start.folders" in keys:
            old = self.rail
            parent = old.get_parent()
            parent.remove(old)
            self.rail = self._build_rail()
            self.rail.set_halign(Gtk.Align.START)
            parent.add_overlay(self.rail)
            self.rail.show_all()

    # -- Popup hooks ---------------------------------------------------------

    def on_open(self):
        self.toggle_rail(False)
        self.list_stack.set_visible_child_name("list")
        monitor = self.shell.current_monitor
        height = 640
        if monitor is not None:
            geo = monitor.get_geometry()
            height = min(height, geo.height - 60)
        self.set_size_request(-1, height)
        self.list_scroll.get_vadjustment().set_value(0)
        self._populate_tiles()  # refresh the live calendar tile

    def after_show(self):
        self.shell.set_start_open(True)

    def on_close(self):
        self.shell.set_start_open(False)
