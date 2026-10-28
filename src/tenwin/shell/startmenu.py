"""The Start menu: rail, alphabetical app list and live tiles."""

import os
import shutil

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from tenwin import paths
from tenwin.apps import first_letter
from tenwin.config import get_settings
from tenwin.gtkutil import (add_class, clear_children, flat_button, icon_image, menu_item,
                            popup_menu, set_class)
from tenwin import fileops, tilemenu, tiles
from tenwin.i18n import _
from tenwin.services import system
from tenwin.shell.layer import Edge, Popup, taskbar_edge

CELL = tiles.CELL
GAP = tiles.GAP

CALENDAR_APPS = {"org.gnome.Calendar.desktop", "gnome-calendar.desktop"}
MIN_WIDTH = 48 + 272 + tiles.GROUP_WIDTH + 40
MIN_HEIGHT = 400
DEFAULT_HEIGHT = 640
GRIP = 6

# Kept for callers and tests that import them from here.
layout_tiles = tiles.layout_tiles
COLUMNS = tiles.COLUMNS


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
        outer = Gtk.Overlay()
        self.add(outer)
        frame = add_class(Gtk.Box(), "tw-panel", "tw-start")
        outer.add(frame)
        self._add_grips(outer)
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
        self._make_drag_source(button, tiles.app_key(info.get_id()))
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
        return tiles.load(self.shell.apps)

    def save_groups(self, groups):
        tiles.save(groups)

    def _tile_columns(self):
        width = self.get_allocated_width() if self.get_realized() else 0
        requested = self.settings["start.width"]
        width = requested or width
        if not width:
            return 2
        return tiles.group_columns_for_width(width - 48 - 272 - 28)

    def _populate_tiles(self, columns_count=None):
        clear_children(self.tile_area)
        groups = self.tile_groups()
        count = columns_count or self._tile_columns()
        count = max(1, min(count, len(groups) or 1))
        self._shown_columns = count
        columns = []
        for _i in range(count):
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            col.set_size_request(tiles.GROUP_WIDTH, -1)
            self.tile_area.pack_start(col, False, False, 0)
            columns.append(col)
        if not any(g["tiles"] for g in groups):
            hint = add_class(Gtk.Label(label=_("Right-click an app and choose \"Pin to Start\"."),
                                       xalign=0, wrap=True), "tw-dim-text")
            hint.set_max_width_chars(30)
            hint.set_margin_top(16)
            columns[0].pack_start(hint, False, False, 0)
        for index, group in enumerate(groups):
            columns[index % count].pack_start(self._group_widget(group, index), False, False, 0)
        columns[len(groups) % count].pack_start(self._new_group_target(len(groups)), False, False, 0)
        self.tile_area.show_all()

    def _new_group_target(self, index):
        """Drop zone and button that start a new group (category)."""
        button = flat_button(css="tw-new-group")
        row = Gtk.Box(spacing=8)
        row.pack_start(icon_image("tenwin-new-folder", 16, symbolic=True), False, False, 0)
        row.pack_start(Gtk.Label(label=_("New group"), xalign=0), True, True, 0)
        button.add(row)
        button.set_tooltip_text(_("Drag a tile or an app here to create a new group"))
        button.connect("clicked", lambda *_: self._ask_new_group())
        self._make_drop_target(button, index, None)
        return button

    def _ask_new_group(self):
        name = tilemenu.ask_group_name()
        if name is not None:
            groups = self.tile_groups()
            groups.append({"name": name, "tiles": []})
            self.save_groups(groups)

    def _group_widget(self, group, group_index):
        box = add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "tw-tile-group")
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
            tiles.rename_group(groups, group_index, entry.get_text())
            self.save_groups(groups)

        title_button.connect("clicked", start_edit)
        title_button.connect("button-release-event",
                             lambda _w, e: self._group_menu(group_index, e, start_edit) if e.button == 3 else False)
        entry.connect("activate", finish_edit)
        entry.connect("focus-out-event", lambda *_: finish_edit() or False)
        box.pack_start(title_stack, False, False, 0)

        grid = Gtk.Fixed()
        placed, rows = tiles.layout_tiles(group["tiles"])
        for tile, col, row, w, h in placed:
            widget = self._tile_widget(tile, group_index, w, h)
            if widget is not None:
                grid.put(widget, col * (CELL + GAP), row * (CELL + GAP))
        # Leave one empty row as drop zone at the end of the group.
        grid.set_size_request(tiles.GROUP_WIDTH, rows * (CELL + GAP) + CELL // 2)
        events = Gtk.EventBox()
        events.add(grid)
        self._make_drop_target(events, group_index, None)
        box.pack_start(events, False, False, 0)
        box.set_margin_bottom(8)
        return box

    def _tile_target(self, tile):
        """(title, icon, open callback, desktop app info or None) for a tile."""
        if tile.get("app"):
            info = self.shell.apps.get(tile["app"])
            if info is None:
                return None
            return info.get_display_name(), info.get_icon(), lambda: self.launch(info), info
        path = tile.get("path")
        if not path or not os.path.exists(path):
            return None
        gfile = Gio.File.new_for_path(path)
        icon = "folder" if os.path.isdir(path) else "text-x-generic"
        try:
            icon = gfile.query_info("standard::icon", Gio.FileQueryInfoFlags.NONE, None).get_icon()
        except GLib.Error:
            pass
        name = os.path.basename(path.rstrip("/")) or path
        if os.path.isdir(path):
            return name, icon, lambda: self._run_ctl("explorer", path), None
        if path.endswith(".desktop"):
            # Same trust check as on the desktop: never run an untrusted launcher silently.
            app = Gio.DesktopAppInfo.new_from_filename(path)
            if app is not None:
                name, icon = app.get_display_name(), app.get_icon() or icon
            return name, icon, lambda: (self.close_popup(), fileops.launch_desktop_file(path)), None
        return name, icon, lambda: (self.close_popup(), self.shell.open_uri(gfile.get_uri())), None

    def _tile_widget(self, tile, group_index, w, h):
        target = self._tile_target(tile)
        if target is None:
            return None
        title, icon, open_cb, info = target
        key = tiles.tile_key(tile)
        width, height = w * CELL + (w - 1) * GAP, h * CELL + (h - 1) * GAP
        button = flat_button(css="tw-tile")
        button.set_size_request(width, height)
        overlay = Gtk.Overlay()
        size = tile.get("size", "medium")
        icon_px = {"small": 24, "medium": 32, "wide": 32, "large": 64}[size]
        if info is not None and info.get_id() in CALENDAR_APPS and size != "small":
            now = GLib.DateTime.new_now_local()
            center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            center.set_valign(Gtk.Align.CENTER)
            center.pack_start(Gtk.Label(label=now.format("%A")), False, False, 0)
            center.pack_start(add_class(Gtk.Label(label=str(now.get_day_of_month())), "tw-tile-big"),
                              False, False, 0)
            overlay.add(center)
        else:
            overlay.add(icon_image(icon, icon_px))
        if size != "small":
            name = Gtk.Label(label=title, xalign=0)
            name.set_ellipsize(Pango.EllipsizeMode.END)
            name.set_halign(Gtk.Align.START)
            name.set_valign(Gtk.Align.END)
            name.set_margin_start(6)
            name.set_margin_bottom(4)
            name.set_max_width_chars(12 if size == "medium" else 26)
            overlay.add_overlay(name)
        button.add(overlay)
        button.set_tooltip_text(title)
        button.connect("clicked", lambda *_: open_cb())
        button.connect("button-release-event",
                       lambda _w, e: self._tile_menu(tile, info, e) if e.button == 3 else False)
        self._make_drag_source(button, key)
        self._make_drop_target(button, group_index, key)
        return button

    # -- drag and drop ------------------------------------------------------

    TARGETS = [Gtk.TargetEntry.new("application/x-tenwin-tile", Gtk.TargetFlags.SAME_APP, 0)]

    def _make_drag_source(self, widget, key):
        widget.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, self.TARGETS, Gdk.DragAction.MOVE)
        widget.connect("drag-data-get", lambda _w, _c, data, _i, _t: data.set(data.get_target(), 8, key.encode()))

    def _make_drop_target(self, widget, group_index, before_key):
        widget.drag_dest_set(Gtk.DestDefaults.ALL, self.TARGETS, Gdk.DragAction.MOVE)
        widget.connect("drag-motion", lambda *_: add_class(widget, "drop-target") and False)
        widget.connect("drag-leave", lambda *_: set_class(widget, "drop-target", False))
        widget.connect("drag-data-received",
                       lambda _w, _c, _x, _y, data, _i, _t: self._drop(data.get_data().decode(), group_index,
                                                                       before_key))

    def _drop(self, key, group_index, before_key):
        if key == before_key:
            return
        groups = self.tile_groups()
        if group_index >= len(groups):
            # Dropped on "New group": name it after the app's category.
            name = tiles.suggested_group(groups, key, self.shell.apps)
            tiles.pin(groups, key, new_group_name=name)
        else:
            tiles.move(groups, key, group_index, before_key)
        self.save_groups(groups)

    # -- context menus -----------------------------------------------------

    def is_pinned_start(self, info):
        return tiles.is_pinned(self.tile_groups(), tiles.app_key(info.get_id()))

    def pin_start(self, info, pinned=True, group=None):
        self.pin_key(tiles.app_key(info.get_id()), pinned, group)

    def pin_key(self, key, pinned=True, group=None):
        if pinned:
            tilemenu.pin([key], group=group, apps=self.shell.apps)
        else:
            tilemenu.unpin([key], apps=self.shell.apps)

    def pin_submenu(self, key, label=None):
        return tilemenu.pin_submenu([key], label, self.shell.apps)

    def _app_menu(self, info, event):
        menu = Gtk.Menu()
        key = tiles.app_key(info.get_id())
        menu.append(self.pin_submenu(key, _("Move to group") if self.is_pinned_start(info) else None))
        if self.is_pinned_start(info):
            menu.append(menu_item(_("Unpin from Start"), lambda: self.pin_start(info, False), "tenwin-unpin"))
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

    def _tile_menu(self, tile, info, event):
        key = tiles.tile_key(tile)
        menu = Gtk.Menu()
        menu.append(menu_item(_("Unpin from Start"), lambda: self.pin_key(key, False), "tenwin-unpin"))
        menu.append(self.pin_submenu(key, _("Move to group")))
        resize = Gtk.MenuItem(label=_("Resize"))
        sub = Gtk.Menu()
        for size, text in (("small", _("Small")), ("medium", _("Medium")), ("wide", _("Wide")),
                           ("large", _("Large"))):
            item = menu_item(("✓  " if tile.get("size") == size else "     ") + text,
                             lambda s=size: self._resize(key, s))
            sub.append(item)
        add_class(sub, "tw-menu")
        resize.set_submenu(sub)
        menu.append(resize)
        if info is not None:
            if self.shell.apps.is_pinned(info):
                menu.append(menu_item(_("Unpin from taskbar"), lambda: self.shell.apps.set_pinned(info, False)))
            else:
                menu.append(menu_item(_("Pin to taskbar"), lambda: self.shell.apps.set_pinned(info, True)))
        elif tile.get("path"):
            menu.append(menu_item(_("Open file location"),
                                  lambda: self._run_ctl("explorer", os.path.dirname(tile["path"].rstrip("/")))))
        popup_menu(menu, event=event)
        return True

    def _group_menu(self, index, event, start_edit):
        groups = self.tile_groups()
        menu = Gtk.Menu()
        menu.append(menu_item(_("Rename group"), start_edit, "tenwin-rename"))
        up = menu_item(_("Move group up"), lambda: self._edit_groups(tiles.move_group, index, -1))
        up.set_sensitive(index > 0)
        menu.append(up)
        down = menu_item(_("Move group down"), lambda: self._edit_groups(tiles.move_group, index, 1))
        down.set_sensitive(index < len(groups) - 1)
        menu.append(down)
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(menu_item(_("Sort all tiles into categories"), self.group_by_category, "tenwin-tiles"))
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(menu_item(_("Unpin group from Start"), lambda: self._edit_groups(tiles.remove_group, index),
                              "tenwin-unpin"))
        popup_menu(menu, event=event)
        return True

    def _edit_groups(self, func, *args):
        groups = self.tile_groups()
        func(groups, *args)
        self.save_groups(groups)

    def group_by_category(self):
        self.save_groups(tiles.group_by_category(self.tile_groups(), self.shell.apps))

    def _resize(self, key, size):
        self._edit_groups(tiles.resize, key, size)

    # -- resizing (drag the outer edges like on Windows 10) --------------------

    def _add_grips(self, overlay):
        top = taskbar_edge() == Edge.TOP
        self.grips = []
        for kind in ("side", "edge", "corner"):
            grip = Gtk.EventBox()
            grip.set_above_child(True)
            grip.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                            Gdk.EventMask.POINTER_MOTION_MASK)
            if kind in ("side", "corner"):
                grip.set_halign(Gtk.Align.END)
                grip.set_size_request(GRIP if kind == "side" else GRIP * 2, -1 if kind == "side" else GRIP * 2)
            else:
                grip.set_halign(Gtk.Align.FILL)
                grip.set_size_request(-1, GRIP)
            if kind == "side":
                grip.set_valign(Gtk.Align.FILL)
            else:
                grip.set_valign(Gtk.Align.END if top else Gtk.Align.START)
            cursor = {"side": "ew-resize", "edge": "ns-resize",
                      "corner": "nwse-resize" if top else "nesw-resize"}[kind]
            grip.connect("realize", lambda w, c=cursor: w.get_window().set_cursor(
                Gdk.Cursor.new_from_name(w.get_display(), c)))
            grip.connect("button-press-event", self._grip_press, kind)
            grip.connect("motion-notify-event", self._grip_motion, kind)
            grip.connect("button-release-event", self._grip_release)
            overlay.add_overlay(grip)
            overlay.set_overlay_pass_through(grip, False)
            self.grips.append(grip)
        self._resizing = None

    def _limits(self):
        monitor = self.shell.current_monitor
        if monitor is None:
            return 1600, 900
        geo = monitor.get_geometry()
        from tenwin.shell.layer import taskbar_height
        return geo.width - 8, geo.height - taskbar_height() - 8

    def _grip_press(self, widget, event, kind):
        if event.button != 1:
            return False
        x, y = widget.translate_coordinates(self, int(event.x), int(event.y))
        self._resizing = {"kind": kind, "dx": self.get_allocated_width() - x, "dy": y}
        return True

    def _grip_motion(self, widget, event, kind):
        if not self._resizing:
            return False
        x, y = widget.translate_coordinates(self, int(event.x), int(event.y))
        max_w, max_h = self._limits()
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        if kind in ("side", "corner"):
            width = max(MIN_WIDTH, min(max_w, x + self._resizing["dx"]))
        if kind in ("edge", "corner"):
            if taskbar_edge() == Edge.TOP:
                height = y + GRIP
            else:
                # The surface grows upwards: its top edge follows the pointer.
                height = self.get_allocated_height() - (y - self._resizing["dy"])
            height = max(MIN_HEIGHT, min(max_h, height))
        self._resizing["size"] = (int(width), int(height))
        self.set_size_request(int(width), int(height))
        columns = tiles.group_columns_for_width(int(width) - 48 - 272 - 28)
        if columns != getattr(self, "_shown_columns", None):
            self._populate_tiles(columns)
        return True

    def _grip_release(self, _widget, event):
        if not self._resizing or event.button != 1:
            return False
        size = self._resizing.get("size")
        self._resizing = None
        if size:
            self.settings.update({"start.width": size[0], "start.height": size[1]})
        return True

    def reset_size(self):
        self.settings.update({"start.width": 0, "start.height": 0})

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
        if keys & {"start.width", "start.height"} and not self._resizing and self.is_open():
            self._apply_size()
        if "start.folders" in keys:
            old = self.rail
            parent = old.get_parent()
            parent.remove(old)
            self.rail = self._build_rail()
            self.rail.set_halign(Gtk.Align.START)
            parent.add_overlay(self.rail)
            self.rail.show_all()

    # -- Popup hooks ---------------------------------------------------------

    def _apply_size(self):
        max_w, max_h = self._limits()
        width = self.settings["start.width"]
        height = self.settings["start.height"] or DEFAULT_HEIGHT
        width = max(MIN_WIDTH, min(max_w, width)) if width else -1
        height = max(MIN_HEIGHT, min(max_h, height))
        self.set_size_request(width, height)
        if width == -1:
            self.resize(1, height)  # shrink back to the natural width
        self._populate_tiles(tiles.group_columns_for_width(width - 48 - 272 - 28) if width > 0 else 2)

    def on_open(self):
        self.toggle_rail(False)
        self.list_stack.set_visible_child_name("list")
        self.list_scroll.get_vadjustment().set_value(0)
        self._apply_size()  # also refreshes the live calendar tile

    def after_show(self):
        self.shell.set_start_open(True)

    def on_close(self):
        self.shell.set_start_open(False)
