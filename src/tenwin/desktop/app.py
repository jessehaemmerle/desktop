"""tenwin-desktop: wallpaper and desktop icons on the background layer."""

import logging
import os
import signal
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, GtkLayerShell, Pango

from tenwin import fileops, paths, theme
from tenwin.config import get_settings
from tenwin.gtkutil import add_class, clear_children, icon_image, menu_item, popup_menu, run_detached, set_class
from tenwin.i18n import _
from tenwin.shell.layer import Edge, Layer, LayerWindow

log = logging.getLogger("tenwin.desktop")

ICON_SIZES = {"large": 96, "medium": 48, "small": 32}
CELL = {"large": (120, 134), "medium": (78, 96), "small": (74, 70)}
SPECIAL = {
    "this-pc": ("computer:///", "tenwin-this-pc"),
    "trash": ("trash:///", "tenwin-trash-empty"),
    "home": (None, "user-home"),
}
ATTRS = ("standard::name,standard::display-name,standard::icon,standard::content-type,standard::type,"
         "standard::size,standard::is-hidden,standard::is-backup,time::modified,thumbnail::path")


class Wallpaper:
    """Renders the configured background into a cairo context."""

    def __init__(self):
        self.settings = get_settings()
        self._pixbuf = None
        self._key = None

    def _source(self, width, height):
        path = self.settings["background.picture"] or paths.default_wallpaper()
        key = (path, width, height, self.settings["background.fit"])
        if key == self._key:
            return self._pixbuf
        self._key = key
        self._pixbuf = None
        try:
            fmt, w, h = GdkPixbuf.Pixbuf.get_file_info(path)
            if fmt is None:
                return None
            if fmt.is_scalable():
                factor = max(width / w, height / h)
                self._pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, int(w * factor), int(h * factor), True)
            else:
                self._pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
        except GLib.Error as exc:
            log.warning("cannot load wallpaper %s: %s", path, exc)
        return self._pixbuf

    def draw(self, cr, width, height):
        r, g, b = _hex(self.settings["background.color"])
        cr.set_source_rgb(r, g, b)
        cr.paint()
        if self.settings["background.type"] != "picture":
            return
        pixbuf = self._source(width, height)
        if pixbuf is None:
            return
        pw, ph = pixbuf.get_width(), pixbuf.get_height()
        fit = self.settings["background.fit"]
        cr.save()
        if fit == "tile":
            Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
            cr.get_source().set_extend(1)  # cairo.EXTEND_REPEAT
            cr.paint()
        elif fit == "center":
            Gdk.cairo_set_source_pixbuf(cr, pixbuf, (width - pw) / 2, (height - ph) / 2)
            cr.paint()
        else:
            if fit == "stretch":
                sx, sy = width / pw, height / ph
            else:
                factor = max(width / pw, height / ph) if fit == "fill" else min(width / pw, height / ph)
                sx = sy = factor
            cr.translate((width - pw * sx) / 2, (height - ph * sy) / 2)
            cr.scale(sx, sy)
            Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
            cr.get_source().set_filter(2)  # cairo.FILTER_GOOD
            cr.paint()
        cr.restore()


def _hex(color):
    color = (color or "#000000").lstrip("#")
    try:
        return tuple(int(color[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return (0, 0, 0)


class DesktopItem:
    def __init__(self, key, name, icon, gfile=None, uri=None, content_type="", size=0, mtime=0, is_dir=False):
        self.key = key
        self.name = name
        self.icon = icon
        self.gfile = gfile
        self.uri = uri or (gfile.get_uri() if gfile else None)
        self.content_type = content_type
        self.size = size
        self.mtime = mtime
        self.is_dir = is_dir

    @property
    def path(self):
        return self.gfile.get_path() if self.gfile else None


class DesktopIcon(Gtk.EventBox):
    def __init__(self, view, item):
        super().__init__()
        self.view = view
        self.item = item
        size = view.settings["desktop.icon_size"]
        w, h = CELL.get(size, CELL["medium"])
        box = add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2), "tw-desk-icon")
        box.set_size_request(w, h)
        image = icon_image(item.icon, ICON_SIZES.get(size, 48))
        box.pack_start(image, False, False, 2)
        self.label = Gtk.Label(label=item.name, justify=Gtk.Justification.CENTER)
        self.label.set_line_wrap(True)
        self.label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.label.set_lines(2)
        self.label.set_ellipsize(Pango.EllipsizeMode.END)
        self.label.set_max_width_chars(11 if size != "large" else 16)
        box.pack_start(self.label, False, False, 0)
        self.add(box)
        self.box = box
        self.set_tooltip_text(item.name)
        self.connect("button-press-event", self._on_press)
        self.connect("button-release-event", self._on_release)
        if item.gfile is not None:
            self.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, [], Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
            self.drag_source_add_uri_targets()
            self.connect("drag-data-get", self._drag_get)
            self.connect("drag-begin", lambda *_: self.view.select(self, keep=True))
        if item.is_dir or item.key == "trash":
            self.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
            self.drag_dest_add_uri_targets()
            self.connect("drag-data-received", self._drop)

    def set_selected(self, selected):
        set_class(self.box, "selected", selected)

    def _on_press(self, _widget, event):
        if event.button == 1 and event.type == Gdk.EventType._2BUTTON_PRESS:
            self.view.open_items([self.item])
            return True
        if event.button == 1:
            ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
            self.view.select(self, toggle=bool(ctrl))
            self.view.window.present()
            return False
        if event.button == 3:
            if self not in self.view.selected:
                self.view.select(self)
            return True
        return False

    def _on_release(self, _widget, event):
        if event.button == 3:
            self.view.item_menu(event)
            return True
        return False

    def _drag_get(self, _widget, _context, data, _info, _time):
        data.set_uris([i.item.uri for i in self.view.selected if i.item.gfile is not None])

    def _drop(self, _widget, _context, _x, _y, data, _info, _time):
        uris = [u for u in data.get_uris() if u != self.item.uri]
        if not uris:
            return
        if self.item.key == "trash":
            fileops.trash([Gio.File.new_for_uri(u).get_path() for u in uris])
        else:
            fileops.FileOperation([Gio.File.new_for_uri(u) for u in uris], self.item.path, move=True).start()


class DesktopView(Gtk.Overlay):
    def __init__(self, window, show_icons):
        super().__init__()
        self.window = window
        self.settings = get_settings()
        self.wallpaper = window.wallpaper
        self.show_icons = show_icons
        self.selected = []
        self.icons = []
        self.area = Gtk.DrawingArea()
        self.area.connect("draw", self._draw)
        self.add(self.area)
        self.events = Gtk.EventBox()
        self.events.set_visible_window(False)
        self.events.connect("button-press-event", self._on_background_press)
        self.events.connect("button-release-event", self._on_background_release)
        self.flow = Gtk.FlowBox(orientation=Gtk.Orientation.VERTICAL)
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow.set_homogeneous(True)
        self.flow.set_valign(Gtk.Align.START)
        self.flow.set_halign(Gtk.Align.START)
        self.flow.set_column_spacing(2)
        self.flow.set_row_spacing(2)
        self.flow.set_max_children_per_line(30)
        self.flow.set_margin_start(4)
        self.flow.set_margin_top(4)
        self.flow.set_margin_bottom(44)  # keep icons above the taskbar
        self.events.add(self.flow)
        self.add_overlay(self.events)
        self.events.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        self.events.drag_dest_add_uri_targets()
        self.events.connect("drag-data-received", self._on_drop)
        self.window.connect("key-press-event", self._on_key)

    def _draw(self, widget, cr):
        alloc = widget.get_allocation()
        self.wallpaper.draw(cr, alloc.width, alloc.height)
        return False

    # -- items ---------------------------------------------------------------

    def desktop_dir(self):
        return paths.xdg_user_dir("DESKTOP")

    def collect(self):
        s = self.settings
        items = []
        if s["desktop.show_this_pc"]:
            items.append(DesktopItem("this-pc", _("This PC"), "tenwin-this-pc", uri="computer:///"))
        if s["desktop.show_home"]:
            home = Gio.File.new_for_path(os.path.expanduser("~"))
            items.append(DesktopItem("home", GLib.get_real_name() or GLib.get_user_name(), "user-home",
                                     gfile=home, is_dir=True))
        if s["desktop.show_trash"]:
            icon = "tenwin-trash-full" if self._trash_has_items() else "tenwin-trash-empty"
            items.append(DesktopItem("trash", _("Recycle Bin"), icon, uri="trash:///"))
        directory = Gio.File.new_for_path(self.desktop_dir())
        files = []
        try:
            enumerator = directory.enumerate_children(ATTRS, Gio.FileQueryInfoFlags.NONE, None)
            for info in enumerator:
                if info.get_is_hidden() or info.get_is_backup():
                    continue
                gfile = directory.get_child(info.get_name())
                is_dir = info.get_file_type() == Gio.FileType.DIRECTORY
                icon = info.get_icon()
                name = info.get_display_name()
                if info.get_name().endswith(".desktop"):
                    app = Gio.DesktopAppInfo.new_from_filename(gfile.get_path())
                    if app is not None:
                        icon = app.get_icon() or icon
                        name = app.get_display_name() or name
                thumb = info.get_attribute_byte_string("thumbnail::path")
                if thumb:
                    icon = Gio.FileIcon.new(Gio.File.new_for_path(thumb))
                mtime = info.get_attribute_uint64("time::modified")
                files.append(DesktopItem("file:" + info.get_name(), name, icon, gfile=gfile,
                                         content_type=info.get_content_type() or "", size=info.get_size(),
                                         mtime=mtime, is_dir=is_dir))
        except GLib.Error as exc:
            log.info("desktop folder: %s", exc)
        order = s["desktop.sort"]
        if order == "size":
            files.sort(key=lambda i: (not i.is_dir, -i.size, i.name.casefold()))
        elif order == "type":
            files.sort(key=lambda i: (not i.is_dir, i.content_type, i.name.casefold()))
        elif order == "modified":
            files.sort(key=lambda i: (not i.is_dir, -i.mtime))
        else:
            files.sort(key=lambda i: (not i.is_dir, i.name.casefold()))
        return items + files

    def _trash_has_items(self):
        try:
            info = Gio.File.new_for_uri("trash:///").query_info("trash::item-count", Gio.FileQueryInfoFlags.NONE,
                                                                None)
            return info.get_attribute_uint32("trash::item-count") > 0
        except GLib.Error:
            return False

    def refresh(self):
        clear_children(self.flow)
        self.icons = []
        selected_keys = {i.item.key for i in self.selected}
        self.selected = []
        if self.show_icons and self.settings["desktop.show_icons"]:
            for item in self.collect():
                icon = DesktopIcon(self, item)
                self.icons.append(icon)
                child = Gtk.FlowBoxChild()
                child.set_can_focus(False)
                child.add(icon)
                self.flow.add(child)
                if item.key in selected_keys:
                    self.selected.append(icon)
                    icon.set_selected(True)
        self.flow.show_all()
        self.area.queue_draw()

    # -- selection -------------------------------------------------------------

    def select(self, icon, toggle=False, keep=False):
        if keep and icon in self.selected:
            return
        if toggle:
            if icon in self.selected:
                self.selected.remove(icon)
                icon.set_selected(False)
            else:
                self.selected.append(icon)
                icon.set_selected(True)
            return
        for other in self.selected:
            other.set_selected(False)
        self.selected = [icon]
        icon.set_selected(True)

    def clear_selection(self):
        for icon in self.selected:
            icon.set_selected(False)
        self.selected = []

    def selected_files(self):
        return [i.item.path for i in self.selected if i.item.gfile is not None and i.item.key.startswith("file:")]

    # -- actions -------------------------------------------------------------

    def open_items(self, items):
        for item in items:
            if item.key in ("this-pc", "trash") or item.is_dir:
                run_detached([paths.binary("tenwin-explorer"), item.uri])
            elif item.path and item.path.endswith(".desktop"):
                app = Gio.DesktopAppInfo.new_from_filename(item.path)
                if app is not None:
                    app.launch([], None)
            elif item.uri:
                try:
                    Gio.AppInfo.launch_default_for_uri(item.uri, None)
                except GLib.Error as exc:
                    self._error(_("Can't open this file"), exc.message)

    def _error(self, title, text):
        dialog = Gtk.MessageDialog(message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK, text=title)
        dialog.format_secondary_text(text)
        dialog.run()
        dialog.destroy()

    def delete_selected(self, permanent=False):
        files = self.selected_files()
        if not files:
            return
        if permanent:
            if fileops.confirm_delete(None, len(files), True):
                fileops.delete_permanently(files)
        else:
            fileops.trash(files)

    def rename_selected(self):
        if len(self.selected) != 1 or not self.selected[0].item.key.startswith("file:"):
            return
        icon = self.selected[0]
        popover = Gtk.Popover(relative_to=icon)
        entry = Gtk.Entry(text=icon.item.gfile.get_basename())
        entry.set_width_chars(20)
        popover.add(entry)
        name = entry.get_text()
        stem = os.path.splitext(name)[0] if not icon.item.is_dir else name

        def commit(*_args):
            new = entry.get_text().strip()
            popover.popdown()
            if new and new != icon.item.gfile.get_basename():
                try:
                    fileops.rename(icon.item.path, new)
                except (OSError, ValueError) as exc:
                    self._error(_("Rename"), str(exc))

        entry.connect("activate", commit)
        popover.show_all()
        entry.grab_focus()
        entry.select_region(0, len(stem))

    def copy_selected(self, cut=False):
        files = self.selected_files()
        if files:
            fileops.clipboard_set(files, cut)

    def paste(self):
        fileops.paste_into(self.desktop_dir())

    def new_folder(self):
        os.makedirs(self.desktop_dir(), exist_ok=True)
        path = fileops.new_folder(self.desktop_dir())
        GLib.timeout_add(400, self._select_and_rename, os.path.basename(path))

    def new_text(self):
        os.makedirs(self.desktop_dir(), exist_ok=True)
        path = fileops.new_text_file(self.desktop_dir())
        GLib.timeout_add(400, self._select_and_rename, os.path.basename(path))

    def _select_and_rename(self, name):
        self.refresh()
        for icon in self.icons:
            if icon.item.key == "file:" + name:
                self.select(icon)
                self.rename_selected()
        return GLib.SOURCE_REMOVE

    # -- menus -------------------------------------------------------------

    def item_menu(self, event):
        items = [i.item for i in self.selected]
        menu = Gtk.Menu()
        menu.append(menu_item(_("Open"), lambda: self.open_items(items)))
        files = self.selected_files()
        if any(i.key == "trash" for i in items):
            menu.append(menu_item(_("Empty Recycle Bin"), self._empty_trash))
        if files:
            menu.append(Gtk.SeparatorMenuItem())
            menu.append(menu_item(_("Cut"), lambda: self.copy_selected(True)))
            menu.append(menu_item(_("Copy"), lambda: self.copy_selected(False)))
            menu.append(Gtk.SeparatorMenuItem())
            menu.append(menu_item(_("Delete"), self.delete_selected))
            menu.append(menu_item(_("Rename"), self.rename_selected, sensitive=len(files) == 1))
            menu.append(Gtk.SeparatorMenuItem())
            menu.append(menu_item(_("Properties"), lambda: run_detached(
                [paths.binary("tenwin-explorer"), "--properties"] + files)))
        elif any(i.key == "this-pc" for i in items):
            menu.append(menu_item(_("Properties"), lambda: run_detached(
                [paths.binary("tenwin-settings"), "tenwin-settings:about"])))
        popup_menu(menu, event=event)

    def background_menu(self, event):
        s = self.settings
        menu = Gtk.Menu()

        view = Gtk.MenuItem(label=_("View"))
        sub = Gtk.Menu()
        for key, text in (("large", _("Large icons")), ("medium", _("Medium icons")), ("small", _("Small icons"))):
            sub.append(menu_item(("•  " if s["desktop.icon_size"] == key else "    ") + text,
                                 lambda k=key: s.set("desktop.icon_size", k)))
        sub.append(Gtk.SeparatorMenuItem())
        sub.append(menu_item(("✓  " if s["desktop.show_icons"] else "    ") + _("Show desktop icons"),
                             lambda: s.set("desktop.show_icons", not s["desktop.show_icons"])))
        add_class(sub, "tw-menu")
        view.set_submenu(sub)
        menu.append(view)

        sort = Gtk.MenuItem(label=_("Sort by"))
        sub = Gtk.Menu()
        for key, text in (("name", _("Name")), ("size", _("Size")), ("type", _("Item type")),
                          ("modified", _("Date modified"))):
            sub.append(menu_item(text, lambda k=key: s.set("desktop.sort", k)))
        add_class(sub, "tw-menu")
        sort.set_submenu(sub)
        menu.append(sort)
        menu.append(menu_item(_("Refresh"), self.refresh))
        menu.append(Gtk.SeparatorMenuItem())
        paste = menu_item(_("Paste"), self.paste)
        paste.set_sensitive(False)
        fileops.clipboard_has_files(lambda has: paste.set_sensitive(has))
        menu.append(paste)
        menu.append(Gtk.SeparatorMenuItem())
        new = Gtk.MenuItem(label=_("New"))
        sub = Gtk.Menu()
        sub.append(menu_item(_("Folder"), self.new_folder, "tenwin-folder"))
        sub.append(menu_item(_("Text Document"), self.new_text, "tenwin-documents"))
        add_class(sub, "tw-menu")
        new.set_submenu(sub)
        menu.append(new)
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(menu_item(_("Display settings"), lambda: self._settings("display"), "tenwin-display"))
        menu.append(menu_item(_("Personalize"), lambda: self._settings("background"), "tenwin-personalization"))
        popup_menu(menu, event=event)

    def _settings(self, page):
        run_detached([paths.binary("tenwin-settings"), "tenwin-settings:" + page])

    def _empty_trash(self):
        run_detached([paths.binary("tenwin-explorer"), "--empty-trash"])

    # -- events --------------------------------------------------------------

    def _on_background_press(self, _widget, event):
        if event.button in (1, 3):
            self.clear_selection()
            self.window.present()
        return False

    def _on_background_release(self, _widget, event):
        if event.button == 3:
            self.background_menu(event)
            return True
        return False

    def _on_drop(self, _widget, context, _x, _y, data, _info, _time):
        uris = data.get_uris()
        target = self.desktop_dir()
        sources = [Gio.File.new_for_uri(u) for u in uris
                   if os.path.dirname(Gio.File.new_for_uri(u).get_path() or "") != target]
        if sources:
            move = context.get_selected_action() == Gdk.DragAction.MOVE
            fileops.FileOperation(sources, target, move=move).start()

    def _on_key(self, _widget, event):
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        shift = event.state & Gdk.ModifierType.SHIFT_MASK
        key = event.keyval
        if key == Gdk.KEY_Delete:
            self.delete_selected(permanent=bool(shift))
        elif key == Gdk.KEY_F2:
            self.rename_selected()
        elif key == Gdk.KEY_F5:
            self.refresh()
        elif key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.open_items([i.item for i in self.selected])
        elif ctrl and key in (Gdk.KEY_c, Gdk.KEY_C):
            self.copy_selected()
        elif ctrl and key in (Gdk.KEY_x, Gdk.KEY_X):
            self.copy_selected(cut=True)
        elif ctrl and key in (Gdk.KEY_v, Gdk.KEY_V):
            self.paste()
        elif ctrl and key in (Gdk.KEY_a, Gdk.KEY_A):
            for icon in self.icons:
                if icon not in self.selected:
                    self.selected.append(icon)
                    icon.set_selected(True)
        elif ctrl and shift and key in (Gdk.KEY_n, Gdk.KEY_N):
            self.new_folder()
        else:
            return False
        return True


class DesktopWindow(LayerWindow):
    def __init__(self, app, monitor, primary):
        super().__init__("tenwin-desktop", layer=Layer.BACKGROUND,
                         anchors=(Edge.TOP, Edge.BOTTOM, Edge.LEFT, Edge.RIGHT), monitor=monitor,
                         keyboard="on_demand", exclusive=-1, css="tw-desktop")
        self.app = app
        self.monitor = monitor
        self.wallpaper = Wallpaper()
        self.view = DesktopView(self, primary)
        self.add(self.view)
        self.view.refresh()
        self.show_all()


class DesktopApp:
    def __init__(self):
        theme.install("desktop")
        self.settings = get_settings()
        self.windows = {}
        display = Gdk.Display.get_default()
        display.connect("monitor-added", lambda *_: self.rebuild())
        display.connect("monitor-removed", lambda *_: self.rebuild())
        self.rebuild()
        self._watch_desktop_dir()
        self._watch_trash()
        self.settings.connect("changed", self._on_settings)

    def rebuild(self):
        for window in self.windows.values():
            window.destroy()
        self.windows = {}
        display = Gdk.Display.get_default()
        primary = display.get_primary_monitor() or display.get_monitor(0)
        for i in range(display.get_n_monitors()):
            monitor = display.get_monitor(i)
            self.windows[monitor] = DesktopWindow(self, monitor, monitor == primary)

    def refresh(self):
        for window in self.windows.values():
            window.view.refresh()

    def _watch_desktop_dir(self):
        directory = Gio.File.new_for_path(paths.xdg_user_dir("DESKTOP"))
        try:
            self.monitor = directory.monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
            self.monitor.connect("changed", lambda *_: self._queue_refresh())
        except GLib.Error as exc:
            log.info("cannot watch desktop folder: %s", exc)
        self._refresh_id = 0

    def _watch_trash(self):
        try:
            self.trash_monitor = Gio.File.new_for_uri("trash:///").monitor_directory(Gio.FileMonitorFlags.NONE, None)
            self.trash_monitor.connect("changed", lambda *_: self._queue_refresh())
        except GLib.Error:
            self.trash_monitor = None

    def _queue_refresh(self):
        if self._refresh_id:
            return

        def run():
            self._refresh_id = 0
            self.refresh()
            return GLib.SOURCE_REMOVE
        self._refresh_id = GLib.timeout_add(250, run)

    def _on_settings(self, _settings, keys):
        if any(k.startswith(("desktop.",)) for k in keys):
            self.refresh()
        if any(k.startswith("background.") for k in keys):
            for window in self.windows.values():
                window.view.area.queue_draw()


def main():
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    GLib.set_prgname("tenwin-desktop")
    Gtk.init(sys.argv)
    if not GtkLayerShell.is_supported():
        log.error("The compositor does not support wlr-layer-shell.")
        return 1
    DesktopApp()
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: Gtk.main_quit() or False)
    Gtk.main()
    return 0
