"""The File Explorer window."""

import os
import threading
import zipfile

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango

from tenwin import fileops
from tenwin.config import get_settings
from tenwin.gtkutil import add_class, clear_children, flat_button, icon_image, menu_item, popup_menu
from tenwin.i18n import _, ngettext
from tenwin.services import system
from tenwin.explorer import model as M
from tenwin.explorer.places import QUICK_ACCESS, THIS_PC, TRASH, NavPane, QuickAccessPage, ThisPCPage
from tenwin.explorer.properties import PropertiesDialog
from tenwin.explorer.ribbon import Ribbon

ICON_SIZES = {"xl": 192, "large": 96, "medium": 48, "small": 16, "list": 16}
SEARCH_LIMIT = 2000


def location_title(gfile):
    uri = gfile.get_uri()
    if uri.startswith(QUICK_ACCESS):
        return _("Quick access")
    if uri.startswith(THIS_PC):
        return _("This PC")
    if uri.startswith(TRASH):
        return _("Recycle Bin")
    if uri.startswith("network:"):
        return _("Network")
    path = gfile.get_path()
    if path == os.path.expanduser("~"):
        return GLib.get_user_name()
    return gfile.get_basename() or uri


class ExplorerWindow(Gtk.ApplicationWindow):
    def __init__(self, app, uri=None):
        super().__init__(application=app, title=_("File Explorer"))
        add_class(self, "tw-app-window", "tw-explorer")
        self.set_default_size(1000, 640)
        self.set_icon_name("org.tenwin.Explorer")
        self.settings = get_settings()
        self.history = []
        self.future = []
        self.location = None
        self.page = None
        self.folder = M.FolderModel()
        self.folder.connect("loaded", lambda *_: self._on_loaded())
        self.folder.connect("error", lambda _m, msg: self._show_error(msg))
        self._search_cancel = None
        self._thumb_queue = []

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)
        self.ribbon = Ribbon(self)
        root.pack_start(self.ribbon, False, False, 0)
        root.pack_start(self._address_bar(), False, False, 0)

        self.paned = Gtk.Paned()
        self.nav = NavPane()
        self.nav.set_size_request(200, -1)
        self.nav.connect("navigate", lambda _n, uri: self.navigate(uri))
        self.paned.pack1(self.nav, False, False)
        self.content = Gtk.Stack()
        self.paned.pack2(self.content, True, False)
        self.paned.set_position(220)
        root.pack_start(self.paned, True, True, 0)

        self._build_views()
        self.this_pc = ThisPCPage()
        self.this_pc.connect("navigate", lambda _p, uri: self.navigate(uri))
        self.this_pc.connect("context", lambda _p, event, target: self._page_context(event, target))
        self.content.add_named(self.this_pc, "this-pc")
        self.quick = QuickAccessPage()
        self.quick.connect("navigate", lambda _p, uri: self.navigate(uri))
        self.quick.connect("open-file", lambda _p, uri: self._open_uri(uri))
        self.quick.connect("context", lambda _p, event, target: self._page_context(event, target))
        self.content.add_named(self.quick, "quick")
        self.message = add_class(Gtk.Label(wrap=True), "tw-dim")
        self.content.add_named(self.message, "message")

        root.pack_start(self._status_bar(), False, False, 0)
        self.connect("key-press-event", self._on_key)
        self.connect("button-press-event", self._on_mouse_nav)
        self.connect("destroy", lambda *_: self.folder.stop())
        self._settings_id = self.settings.connect("changed", self._on_settings)
        self.connect("destroy", lambda *_: self.settings.disconnect(self._settings_id))
        self.show_all()
        self.nav.set_visible(self.settings["explorer.nav_pane"])
        start = uri or (THIS_PC if self.settings["explorer.open_this_pc"] else QUICK_ACCESS)
        self.navigate(start)

    # ------------------------------------------------------------ building

    def _address_bar(self):
        bar = add_class(Gtk.Box(spacing=2), "tw-addressbar")
        self.back_button = flat_button(icon_image("tenwin-arrow-left", 16, symbolic=True), "tw-nav-button",
                                       _("Back (Alt + Left Arrow)"))
        self.back_button.connect("clicked", lambda *_: self.go_back())
        self.forward_button = flat_button(icon_image("tenwin-arrow-right", 16, symbolic=True), "tw-nav-button",
                                          _("Forward (Alt + Right Arrow)"))
        self.forward_button.connect("clicked", lambda *_: self.go_forward())
        self.up_button = flat_button(icon_image("tenwin-arrow-up", 16, symbolic=True), "tw-nav-button",
                                     _("Up (Alt + Up Arrow)"))
        self.up_button.connect("clicked", lambda *_: self.go_up())
        for button in (self.back_button, self.forward_button, self.up_button):
            bar.pack_start(button, False, False, 0)

        self.address_stack = Gtk.Stack()
        frame = add_class(Gtk.Box(), "tw-address")
        self.crumbs = Gtk.Box()
        crumb_events = Gtk.EventBox()
        crumb_events.add(self.crumbs)
        crumb_events.connect("button-release-event", lambda *_: self._edit_address())
        frame.pack_start(crumb_events, True, True, 0)
        refresh = flat_button(icon_image("tenwin-refresh", 14, symbolic=True), "tw-nav-button",
                              _("Refresh (F5)"))
        refresh.connect("clicked", lambda *_: self.refresh())
        frame.pack_end(refresh, False, False, 0)
        self.address_stack.add_named(frame, "crumbs")
        self.address_entry = add_class(Gtk.Entry(), "tw-address-entry")
        self.address_entry.connect("activate", self._on_address)
        self.address_entry.connect("focus-out-event", lambda *_: self.address_stack.set_visible_child_name("crumbs")
                                   or False)
        self.address_stack.add_named(self.address_entry, "entry")
        bar.pack_start(self.address_stack, True, True, 4)

        self.search_entry = add_class(Gtk.SearchEntry(), "tw-search")
        self.search_entry.set_width_chars(26)
        self.search_entry.connect("activate", lambda *_: self.search(self.search_entry.get_text()))
        self.search_entry.connect("stop-search", lambda *_: self._end_search())
        bar.pack_end(self.search_entry, False, False, 0)
        return bar

    def _build_views(self):
        store = self.folder.store
        # Details
        self.tree = Gtk.TreeView(model=store)
        self.tree.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.tree.set_rubber_banding(True)
        self.tree.set_enable_search(False)
        add_class(self.tree, "tw-details")
        name_col = Gtk.TreeViewColumn(_("Name"))
        name_col.set_resizable(True)
        name_col.set_expand(True)
        name_col.set_min_width(240)
        icon_cell = Gtk.CellRendererPixbuf()
        name_col.pack_start(icon_cell, False)
        name_col.set_cell_data_func(icon_cell, self._icon_data, 16)
        self.name_cell = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        self.name_cell.connect("edited", self._on_edited)
        name_col.pack_start(self.name_cell, True)
        name_col.add_attribute(self.name_cell, "text", M.COL_NAME)
        self.name_col = name_col
        self.tree.append_column(name_col)
        self.columns = {"name": name_col}
        for key, title, col, width, xalign in (
                ("modified", _("Date modified"), M.COL_DATE_TEXT, 150, 0.0),
                ("type", _("Type"), M.COL_TYPE_TEXT, 160, 0.0),
                ("size", _("Size"), M.COL_SIZE_TEXT, 90, 1.0),
                ("extra", _("Folder"), M.COL_EXTRA, 220, 0.0)):
            cell = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END, xalign=xalign)
            add_class(self.tree, "tw-details")
            column = Gtk.TreeViewColumn(title, cell, text=col)
            column.set_resizable(True)
            column.set_fixed_width(width)
            column.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
            self.tree.append_column(column)
            self.columns[key] = column
        for key, column in self.columns.items():
            if key != "extra":
                column.set_clickable(True)
                column.connect("clicked", lambda _c, k=key: self.set_sort(k))
        self.tree.connect("row-activated", lambda _t, path, _c: self._activate_path(path))
        self.tree.connect("button-press-event", self._on_view_press)
        self.tree.get_selection().connect("changed", lambda *_: self._update_status())
        self._setup_dnd(self.tree)
        scroll = Gtk.ScrolledWindow()
        scroll.add(self.tree)
        self.content.add_named(scroll, "details")

        # Icons
        self.icons = Gtk.IconView(model=store)
        self.icons.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        add_class(self.icons, "tw-icons")
        self.icon_cell = Gtk.CellRendererPixbuf()
        self.icons.pack_start(self.icon_cell, False)
        self.icons.set_cell_data_func(self.icon_cell, self._icon_data, None)
        self.icon_text = Gtk.CellRendererText(alignment=Pango.Alignment.CENTER, xalign=0.5,
                                              wrap_mode=Pango.WrapMode.WORD_CHAR)
        self.icon_text.connect("edited", self._on_edited)
        self.icons.pack_start(self.icon_text, False)
        self.icons.add_attribute(self.icon_text, "text", M.COL_NAME)
        self.icons.connect("item-activated", lambda _v, path: self._activate_path(path))
        self.icons.connect("button-press-event", self._on_view_press)
        self.icons.connect("selection-changed", lambda *_: self._update_status())
        self._setup_dnd(self.icons)
        scroll = Gtk.ScrolledWindow()
        scroll.add(self.icons)
        self.content.add_named(scroll, "icons")
        self._apply_view()

    def _status_bar(self):
        bar = add_class(Gtk.Box(spacing=16), "tw-statusbar")
        self.status_count = Gtk.Label(xalign=0)
        self.status_selection = Gtk.Label(xalign=0)
        bar.pack_start(self.status_count, False, False, 0)
        bar.pack_start(self.status_selection, False, False, 0)
        details = flat_button(icon_image("tenwin-view-details", 14, symbolic=True), "tw-status-button",
                              _("Displays information about each item in the window. (Ctrl+Shift+6)"))
        details.connect("clicked", lambda *_: self.settings.set("explorer.view", "details"))
        large = flat_button(icon_image("tenwin-view-icons", 14, symbolic=True), "tw-status-button",
                            _("Display items by using large thumbnails. (Ctrl+Shift+2)"))
        large.connect("clicked", lambda *_: self.settings.set("explorer.view", "large"))
        bar.pack_end(large, False, False, 0)
        bar.pack_end(details, False, False, 0)
        return bar

    # ------------------------------------------------------------ views

    def _icon_data(self, _layout, cell, store, it, size):
        if size is None:
            size = ICON_SIZES.get(self.settings["explorer.view"], 48)
        thumb = store[it][M.COL_THUMB]
        cell.set_property("stock-size", Gtk.IconSize.DIALOG)
        if isinstance(thumb, GdkPixbuf.Pixbuf):
            cell.set_property("pixbuf", self._fit(thumb, size))
            return
        if isinstance(thumb, str) and size >= 48:
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(thumb, size, size, True)
                store[it][M.COL_THUMB] = pixbuf
                cell.set_property("pixbuf", pixbuf)
                return
            except GLib.Error:
                store[it][M.COL_THUMB] = None
        icon = store[it][M.COL_ICON]
        theme = Gtk.IconTheme.get_default()
        info = theme.lookup_by_gicon(icon, size, Gtk.IconLookupFlags.FORCE_SIZE) if icon else None
        if info is None:
            info = theme.lookup_icon("text-x-generic", size, Gtk.IconLookupFlags.FORCE_SIZE)
        try:
            cell.set_property("pixbuf", info.load_icon() if info else None)
        except GLib.Error:
            cell.set_property("pixbuf", None)

    @staticmethod
    def _fit(pixbuf, size):
        w, h = pixbuf.get_width(), pixbuf.get_height()
        if max(w, h) <= size:
            return pixbuf
        factor = size / max(w, h)
        return pixbuf.scale_simple(max(1, int(w * factor)), max(1, int(h * factor)), GdkPixbuf.InterpType.BILINEAR)

    def _apply_view(self):
        view = self.settings["explorer.view"]
        if self.page in (None, "folder"):
            self.content.set_visible_child_name("details" if view == "details" else "icons")
        size = ICON_SIZES.get(view, 48)
        if view in ("small", "list"):
            self.icons.set_item_orientation(Gtk.Orientation.HORIZONTAL)
            self.icons.set_item_width(220)
            self.icons.set_columns(-1)
            self.icon_text.set_property("xalign", 0.0)
            self.icon_text.set_property("alignment", Pango.Alignment.LEFT)
            self.icon_text.set_property("wrap-width", -1)
            self.icon_text.set_property("ellipsize", Pango.EllipsizeMode.END)
            self.icons.set_row_spacing(0)
            self.icons.set_item_padding(2)
        else:
            self.icons.set_item_orientation(Gtk.Orientation.VERTICAL)
            self.icons.set_item_width(size + 24 if size >= 96 else 84)
            self.icons.set_columns(-1)
            self.icon_text.set_property("xalign", 0.5)
            self.icon_text.set_property("alignment", Pango.Alignment.CENTER)
            self.icon_text.set_property("wrap-width", size + 16 if size >= 96 else 76)
            self.icon_text.set_property("ellipsize", Pango.EllipsizeMode.NONE)
            self.icons.set_row_spacing(6)
            self.icons.set_item_padding(4)
        self.icon_cell.set_fixed_size(size, size)
        self.icons.queue_resize()
        self.ribbon.update_layout()

    def active_view(self):
        return self.tree if self.settings["explorer.view"] == "details" else self.icons

    # ------------------------------------------------------------ navigation

    def navigate(self, uri, record=True):
        gfile = Gio.File.new_for_uri(uri) if "://" in uri or uri.startswith(("trash:", "computer:")) \
            else Gio.File.new_for_commandline_arg(uri)
        uri = gfile.get_uri()
        if self.location is not None and record and self.location.get_uri() != uri:
            self.history.append(self.location.get_uri())
            self.future = []
        self.location = gfile
        self._end_search(reload=False)
        self.set_title(location_title(gfile))
        self._update_crumbs()
        self.nav.highlight(uri)
        is_trash = uri.startswith(TRASH)
        self.ribbon.set_context(trash=is_trash)
        self.columns["extra"].set_visible(is_trash)
        self.columns["extra"].set_title(_("Original Location") if is_trash else _("Folder"))
        self.columns["modified"].set_title(_("Date Deleted") if is_trash else _("Date modified"))
        self.back_button.set_sensitive(bool(self.history))
        self.forward_button.set_sensitive(bool(self.future))
        self.up_button.set_sensitive(self._parent_uri() is not None)
        self.search_entry.set_placeholder_text(_("Search %s") % location_title(gfile))
        if uri.startswith(QUICK_ACCESS):
            self.page = "quick"
            self.folder.stop()
            self.quick.refresh()
            self.content.set_visible_child_name("quick")
            self._update_status()
        elif uri.startswith(THIS_PC):
            self.page = "this-pc"
            self.folder.stop()
            self.this_pc.refresh()
            self.content.set_visible_child_name("this-pc")
            self._update_status()
        else:
            self.page = "folder"
            self._apply_view()
            self.folder.load(gfile)
            if gfile.get_path():
                Gtk.RecentManager.get_default()  # keep the manager alive for recent files

    def _parent_uri(self):
        if self.location is None:
            return None
        uri = self.location.get_uri()
        if uri.startswith((QUICK_ACCESS, THIS_PC)):
            return None
        if uri.startswith(TRASH):
            return None
        parent = self.location.get_parent()
        if parent is None:
            return THIS_PC
        return parent.get_uri()

    def go_back(self):
        if self.history:
            self.future.append(self.location.get_uri())
            self.navigate(self.history.pop(), record=False)

    def go_forward(self):
        if self.future:
            self.history.append(self.location.get_uri())
            self.navigate(self.future.pop(), record=False)

    def go_up(self):
        parent = self._parent_uri()
        if parent:
            self.navigate(parent)

    def refresh(self):
        if self.location is not None:
            self.navigate(self.location.get_uri(), record=False)
            self.nav.populate()

    def _update_crumbs(self):
        clear_children(self.crumbs)
        parts = []
        gfile = self.location
        uri = gfile.get_uri()
        if uri.startswith((QUICK_ACCESS, THIS_PC, TRASH, "network:")):
            parts = [(location_title(gfile), uri)]
        else:
            current = gfile
            while current is not None:
                parts.append((location_title(current) if current.get_path() != "/" else _("Local Disk (/)"),
                              current.get_uri()))
                current = current.get_parent()
            parts.reverse()
            if gfile.get_path():
                parts.insert(0, (_("This PC"), THIS_PC))
        self.crumbs.pack_start(icon_image("tenwin-folder", 16, symbolic=True), False, False, 6)
        for index, (title, target) in enumerate(parts):
            if index:
                self.crumbs.pack_start(add_class(Gtk.Label(label="›"), "tw-crumb-sep"), False, False, 0)
            button = flat_button(Gtk.Label(label=title), "tw-crumb")
            button.connect("clicked", lambda _b, t=target: self.navigate(t))
            self.crumbs.pack_start(button, False, False, 0)
        self.crumbs.show_all()
        self.address_stack.set_visible_child_name("crumbs")

    def _edit_address(self):
        path = self.location.get_path()
        self.address_entry.set_text(path if path else self.location.get_uri())
        self.address_stack.set_visible_child_name("entry")
        self.address_entry.grab_focus()
        self.address_entry.select_region(0, -1)
        return True

    def _on_address(self, entry):
        text = os.path.expanduser(entry.get_text().strip())
        if not text:
            return
        lowered = text.casefold()
        aliases = {_("this pc").casefold(): THIS_PC, "this pc": THIS_PC, _("recycle bin").casefold(): TRASH,
                   _("quick access").casefold(): QUICK_ACCESS}
        target = aliases.get(lowered)
        if target is None:
            gfile = Gio.File.new_for_commandline_arg(text)
            if gfile.query_file_type(Gio.FileQueryInfoFlags.NONE, None) == Gio.FileType.DIRECTORY:
                target = gfile.get_uri()
            elif gfile.query_exists(None):
                self._open_uri(gfile.get_uri())
                self.address_stack.set_visible_child_name("crumbs")
                return
            else:
                dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.ERROR,
                                           buttons=Gtk.ButtonsType.OK,
                                           text=_("Tenwin can't find '%s'. Check the spelling and try again.")
                                           % text)
                dialog.run()
                dialog.destroy()
                return
        self.navigate(target)

    def _on_loaded(self):
        if self.page == "folder":
            self._apply_view()
        self._update_status()

    def _show_error(self, message):
        self.message.set_text(_("This location can't be opened.") + "\n\n" + message)
        self.content.set_visible_child_name("message")

    def _update_status(self):
        if self.page in ("quick", "this-pc"):
            self.status_count.set_text("")
            self.status_selection.set_text("")
            return
        count = len(self.folder.store)
        self.status_count.set_text(ngettext("%d item", "%d items", count) % count)
        rows = self.selected_rows()
        if rows:
            text = ngettext("%d item selected", "%d items selected", len(rows)) % len(rows)
            files = [r for r in rows if not r[M.COL_IS_DIR]]
            if files and len(files) == len(rows):
                from tenwin.gtkutil import human_size
                text += "  " + human_size(sum(r[M.COL_SIZE] for r in files))
            self.status_selection.set_text(text)
        else:
            self.status_selection.set_text("")

    # ------------------------------------------------------------ selection

    def selected_paths(self):
        view = self.active_view()
        if view is self.tree:
            _model, paths = self.tree.get_selection().get_selected_rows()
            return paths
        return self.icons.get_selected_items()

    def selected_rows(self):
        store = self.folder.store
        if self.page != "folder":
            return []
        return [store[p] for p in self.selected_paths()]

    def selected_files(self):
        return [row[M.COL_FILE] for row in self.selected_rows()]

    def selected_local_paths(self):
        return [f.get_path() for f in self.selected_files() if f.get_path()]

    def select_all(self):
        if self.active_view() is self.tree:
            self.tree.get_selection().select_all()
        else:
            self.icons.select_all()

    def select_none(self):
        if self.active_view() is self.tree:
            self.tree.get_selection().unselect_all()
        else:
            self.icons.unselect_all()

    def invert_selection(self):
        selected = {p.to_string() for p in self.selected_paths()}
        self.select_none()
        for index in range(len(self.folder.store)):
            path = Gtk.TreePath.new_from_indices([index])
            if path.to_string() not in selected:
                if self.active_view() is self.tree:
                    self.tree.get_selection().select_path(path)
                else:
                    self.icons.select_path(path)

    def _select_name(self, name, rename=False):
        for row in self.folder.store:
            if row[M.COL_FILE].get_basename() == name:
                self.select_none()
                path = row.path
                if self.active_view() is self.tree:
                    self.tree.get_selection().select_path(path)
                    self.tree.scroll_to_cell(path, None, False, 0, 0)
                else:
                    self.icons.select_path(path)
                    self.icons.scroll_to_path(path, False, 0, 0)
                if rename:
                    self._start_rename(path)
                return True
        return False

    # ------------------------------------------------------------ activation

    def _activate_path(self, path):
        row = self.folder.store[path]
        gfile = row[M.COL_FILE]
        if self.folder.is_trash:
            self.properties()
            return
        if row[M.COL_IS_DIR]:
            self.navigate(gfile.get_uri())
        else:
            self._open_uri(gfile.get_uri())

    def _open_uri(self, uri):
        try:
            Gio.AppInfo.launch_default_for_uri(uri, None)
            Gtk.RecentManager.get_default().add_item(uri)
        except GLib.Error as exc:
            self._error(_("Can't open this file"), exc.message)

    def open_selected(self):
        for path in self.selected_paths():
            self._activate_path(path)

    def open_with(self, app, files):
        try:
            app.launch(files, None)
        except GLib.Error as exc:
            self._error(_("Can't open this file"), exc.message)

    def _error(self, title, message=""):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.ERROR,
                                   buttons=Gtk.ButtonsType.OK, text=title)
        if message:
            dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()

    # ------------------------------------------------------------ commands

    def current_dir(self):
        if self.page != "folder" or self.location is None or self.folder.is_trash:
            return None
        return self.location.get_path()

    def copy(self):
        files = self.selected_files()
        if files:
            fileops.clipboard_set([f.get_uri() for f in files], cut=False)

    def cut(self):
        files = self.selected_files()
        if files:
            fileops.clipboard_set([f.get_uri() for f in files], cut=True)

    def paste(self):
        directory = self.current_dir()
        if directory:
            fileops.paste_into(directory, parent=self)

    def copy_path(self):
        paths = self.selected_local_paths() or ([self.current_dir()] if self.current_dir() else [])
        if paths:
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text("\n".join('"%s"' % p for p in paths), -1)

    def pin_quick_access(self):
        targets = [p for p in self.selected_local_paths() if os.path.isdir(p)] or \
            ([self.current_dir()] if self.current_dir() else [])
        pins = list(self.settings["explorer.quick_access"])
        for path in targets:
            if path not in pins:
                pins.append(path)
        self.settings.set("explorer.quick_access", pins)

    def unpin_quick_access(self, path):
        self.settings.set("explorer.quick_access", [p for p in self.settings["explorer.quick_access"] if p != path])

    def _choose_folder(self, title):
        dialog = Gtk.FileChooserDialog(title=title, transient_for=self, action=Gtk.FileChooserAction.SELECT_FOLDER)
        dialog.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("Select folder"), Gtk.ResponseType.OK)
        result = dialog.get_filename() if dialog.run() == Gtk.ResponseType.OK else None
        dialog.destroy()
        return result

    def move_to(self):
        files = self.selected_files()
        if files:
            target = self._choose_folder(_("Move Items"))
            if target:
                fileops.FileOperation(files, target, move=True, parent=self).start()

    def copy_to(self):
        files = self.selected_files()
        if files:
            target = self._choose_folder(_("Copy Items"))
            if target:
                fileops.FileOperation(files, target, move=False, parent=self).start()

    def delete(self, permanent=False):
        files = self.selected_files()
        if not files:
            return
        if self.folder.is_trash:
            permanent = True
        if permanent:
            if not fileops.confirm_delete(self, len(files), True):
                return
            errors = fileops.delete_permanently(files)
            fileops.show_errors(self, _("Some items could not be deleted."), errors)
        else:
            fileops.trash(files, parent=self)

    def rename(self):
        paths = self.selected_paths()
        if len(paths) == 1 and not self.folder.is_trash:
            self._start_rename(paths[0])

    def _start_rename(self, path):
        row = self.folder.store[path]
        # Edit the real file name (with extension).
        row[M.COL_NAME] = row[M.COL_FILE].get_basename()
        if self.active_view() is self.tree:
            self.name_cell.set_property("editable", True)
            self.tree.set_cursor_on_cell(path, self.name_col, self.name_cell, True)
        else:
            self.icon_text.set_property("editable", True)
            self.icons.set_cursor(path, self.icon_text, True)

    def _on_edited(self, cell, path, new_text):
        cell.set_property("editable", False)
        row = self.folder.store[path]
        gfile = row[M.COL_FILE]
        new_text = new_text.strip()
        if not new_text or new_text == gfile.get_basename():
            self.folder.refill()
            return
        try:
            fileops.rename(gfile.get_path(), new_text)
        except (OSError, ValueError) as exc:
            self._error(_("Rename"), str(exc))
            self.folder.refill()

    def new_folder(self):
        directory = self.current_dir()
        if not directory:
            return
        try:
            path = fileops.new_folder(directory)
        except OSError as exc:
            self._error(_("Can't create the folder"), str(exc))
            return
        self._after_create(os.path.basename(path))

    def new_text_file(self):
        directory = self.current_dir()
        if not directory:
            return
        try:
            path = fileops.new_text_file(directory)
        except OSError as exc:
            self._error(_("Can't create the file"), str(exc))
            return
        self._after_create(os.path.basename(path))

    def _after_create(self, name):
        """Select the new item and start renaming it once the folder reloaded."""
        attempts = {"left": 10}

        def try_select():
            if self._select_name(name, rename=True):
                return GLib.SOURCE_REMOVE
            attempts["left"] -= 1
            if attempts["left"] == 5:
                self.folder.load(self.location)
            return GLib.SOURCE_CONTINUE if attempts["left"] > 0 else GLib.SOURCE_REMOVE

        GLib.timeout_add(200, try_select)

    def properties(self):
        files = self.selected_files() or ([self.location] if self.location is not None and self.page == "folder"
                                          else [])
        if files:
            PropertiesDialog(files, self)

    def open_terminal(self):
        system.open_terminal(self.current_dir() or os.path.expanduser("~"))

    def email(self):
        paths = [p for p in self.selected_local_paths() if os.path.isfile(p)]
        if not paths:
            return
        argv = ["xdg-email"]
        for p in paths:
            argv += ["--attach", p]
        if not system.run(argv):
            self._error(_("No email app is installed."))

    def compress(self):
        paths = self.selected_local_paths()
        directory = self.current_dir()
        if not paths or not directory:
            return
        base = os.path.splitext(os.path.basename(paths[0]))[0] if len(paths) == 1 else \
            os.path.basename(directory) or "Archiv"
        target = os.path.join(directory, fileops.unique_name(directory, base + ".zip"))

        def work():
            error = None
            try:
                with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
                    for path in paths:
                        if os.path.isdir(path):
                            for root, _dirs, files in os.walk(path):
                                for name in files:
                                    full = os.path.join(root, name)
                                    archive.write(full, os.path.relpath(full, directory))
                        else:
                            archive.write(path, os.path.basename(path))
            except OSError as exc:
                error = str(exc)
            GLib.idle_add(lambda: (self._error(_("Compressed (zipped) Folders Error"), error) if error
                                   else self._select_name(os.path.basename(target))) and False)

        threading.Thread(target=work, daemon=True).start()

    def extract(self):
        archives = [p for p in self.selected_local_paths() if zipfile.is_zipfile(p)]
        for archive in archives:
            directory = os.path.dirname(archive)
            target = os.path.join(directory, fileops.unique_name(directory, os.path.splitext(
                os.path.basename(archive))[0]))

            def work(a=archive, t=target):
                error = None
                try:
                    with zipfile.ZipFile(a) as zf:
                        root = os.path.realpath(t)
                        for member in zf.infolist():
                            dest = os.path.realpath(os.path.join(t, member.filename))
                            # Refuse entries that escape the target folder ("zip slip").
                            if not (dest == root or dest.startswith(root + os.sep)):
                                raise OSError(_("The archive contains unsafe paths: %s") % member.filename)
                        zf.extractall(t)
                except (OSError, zipfile.BadZipFile) as exc:
                    error = str(exc)
                GLib.idle_add(lambda: (self._error(_("Compressed (zipped) Folders Error"), error) if error
                                       else self.navigate(Gio.File.new_for_path(t).get_uri())) and False)

            threading.Thread(target=work, daemon=True).start()

    # -- recycle bin ---------------------------------------------------------

    def empty_trash(self):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                                   buttons=Gtk.ButtonsType.YES_NO,
                                   text=_("Are you sure you want to permanently delete all items in the Recycle Bin?"))
        dialog.set_title(_("Delete Multiple Items"))
        ok = dialog.run() == Gtk.ResponseType.YES
        dialog.destroy()
        if ok:
            empty_trash()

    def restore_selected(self, files=None):
        for gfile in files or self.selected_files():
            try:
                info = gfile.query_info("trash::orig-path", Gio.FileQueryInfoFlags.NONE, None)
                orig = info.get_attribute_byte_string("trash::orig-path")
                if not orig:
                    continue
                target = Gio.File.new_for_path(orig)
                if target.query_exists(None):
                    directory = os.path.dirname(orig)
                    target = Gio.File.new_for_path(os.path.join(directory, fileops.unique_name(
                        directory, os.path.basename(orig))))
                parent = target.get_parent()
                if parent is not None and not parent.query_exists(None):
                    parent.make_directory_with_parents(None)
                gfile.move(target, Gio.FileCopyFlags.NOFOLLOW_SYMLINKS, None, None, None)
            except GLib.Error as exc:
                self._error(_("Restore"), exc.message)

    def restore_all(self):
        self.restore_selected([row[M.COL_FILE] for row in self.folder.store])

    # ------------------------------------------------------------ search

    def search(self, text):
        text = text.strip()
        if not text:
            self._end_search()
            return
        root = self.current_dir() or (os.path.expanduser("~") if self.page in ("quick", "this-pc") else None)
        if root is None:
            return
        if self._search_cancel is not None:
            self._search_cancel.set()
        cancel = threading.Event()
        self._search_cancel = cancel
        self.status_selection.set_text(_("Searching…"))
        query = text.casefold()

        def work():
            results = []
            for directory, dirs, files in os.walk(root):
                if cancel.is_set():
                    return
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for name in dirs + files:
                    if query in name.casefold():
                        results.append(os.path.join(directory, name))
                        if len(results) >= SEARCH_LIMIT:
                            break
                if len(results) >= SEARCH_LIMIT:
                    break
            GLib.idle_add(self._show_results, root, results, cancel)

        threading.Thread(target=work, daemon=True).start()

    def _show_results(self, root, results, cancel):
        if cancel.is_set():
            return False
        entries = []
        for path in results:
            gfile = Gio.File.new_for_path(path)
            try:
                info = gfile.query_info(M.ATTRS, Gio.FileQueryInfoFlags.NONE, None)
            except GLib.Error:
                continue
            entries.append((gfile.get_parent(), info))
        self.page = "folder"
        self.columns["extra"].set_visible(True)
        self.columns["extra"].set_title(_("Folder"))
        self.set_title(_("Search Results in %s") % os.path.basename(root))
        self.folder.set_results(Gio.File.new_for_path(root), entries)
        self._apply_view()
        return False

    def _end_search(self, reload=True):
        if self._search_cancel is not None:
            self._search_cancel.set()
            self._search_cancel = None
            if reload and self.location is not None:
                self.navigate(self.location.get_uri(), record=False)

    # ------------------------------------------------------------ menus

    def set_sort(self, key):
        self.folder.set_sort(key)
        for k, column in self.columns.items():
            if k == key:
                column.set_sort_indicator(True)
                column.set_sort_order(Gtk.SortType.DESCENDING if self.folder.sort_desc else Gtk.SortType.ASCENDING)
            else:
                column.set_sort_indicator(False)

    def show_sort_menu(self, widget):
        menu = Gtk.Menu()
        for key, text in (("name", _("Name")), ("modified", _("Date modified")), ("type", _("Type")),
                          ("size", _("Size"))):
            mark = "•  " if self.folder.sort_key == key else "    "
            menu.append(menu_item(mark + text, lambda k=key: self.set_sort(k)))
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(menu_item(_("Ascending"), lambda: self.folder.set_sort(self.folder.sort_key, False)))
        menu.append(menu_item(_("Descending"), lambda: self.folder.set_sort(self.folder.sort_key, True)))
        popup_menu(menu, widget=widget)

    def show_file_menu(self, widget):
        menu = Gtk.Menu()
        menu.append(menu_item(_("Open new window"), lambda: self.get_application().open_window(
            self.location.get_uri() if self.location else None)))
        menu.append(menu_item(_("Open in Terminal"), self.open_terminal, "tenwin-terminal"))
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(menu_item(_("Change folder and search options"), lambda: self.ribbon.select("view")))
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(menu_item(_("Close"), self.close))
        popup_menu(menu, widget=widget)

    def _on_view_press(self, view, event):
        if event.button != 3:
            return False
        if view is self.tree:
            hit = self.tree.get_path_at_pos(int(event.x), int(event.y))
            path = hit[0] if hit else None
            if path is not None and not self.tree.get_selection().path_is_selected(path):
                self.tree.get_selection().unselect_all()
                self.tree.get_selection().select_path(path)
            elif path is None:
                self.tree.get_selection().unselect_all()
        else:
            path = self.icons.get_path_at_pos(int(event.x), int(event.y))
            if path is not None and not self.icons.path_is_selected(path):
                self.icons.unselect_all()
                self.icons.select_path(path)
            elif path is None:
                self.icons.unselect_all()
        if self.selected_paths():
            self._item_menu(event)
        else:
            self._background_menu(event)
        return True

    def _item_menu(self, event):
        rows = self.selected_rows()
        files = [r[M.COL_FILE] for r in rows]
        menu = Gtk.Menu()
        if self.folder.is_trash:
            menu.append(menu_item(_("Restore"), self.restore_selected))
            menu.append(Gtk.SeparatorMenuItem())
            menu.append(menu_item(_("Cut"), self.cut))
            menu.append(Gtk.SeparatorMenuItem())
            menu.append(menu_item(_("Delete"), self.delete))
            menu.append(Gtk.SeparatorMenuItem())
            menu.append(menu_item(_("Properties"), self.properties))
            popup_menu(menu, event=event)
            return
        menu.append(menu_item(_("Open"), self.open_selected))
        single_dir = len(rows) == 1 and rows[0][M.COL_IS_DIR]
        if single_dir:
            uri = files[0].get_uri()
            menu.append(menu_item(_("Open in new window"), lambda: self.get_application().open_window(uri)))
            menu.append(menu_item(_("Pin to Quick access"), self.pin_quick_access, "tenwin-pin"))
            menu.append(menu_item(_("Open in Terminal"), lambda: system.open_terminal(files[0].get_path())))
        else:
            ctypes = {self._content_type(f) for f in files}
            if len(ctypes) == 1:
                ctype = ctypes.pop()
                apps = Gio.AppInfo.get_all_for_type(ctype) if ctype else []
                item = Gtk.MenuItem(label=_("Open with"))
                sub = Gtk.Menu()
                add_class(sub, "tw-menu")
                for app in apps[:12]:
                    sub.append(menu_item(app.get_display_name(), lambda a=app: self.open_with(a, files),
                                         app.get_icon()))
                sub.append(Gtk.SeparatorMenuItem())
                sub.append(menu_item(_("Choose another app"), lambda: self._choose_app(files, ctype)))
                item.set_submenu(sub)
                menu.append(item)
            if any(zipfile.is_zipfile(f.get_path()) for f in files if f.get_path() and f.get_path().endswith(".zip")):
                menu.append(menu_item(_("Extract All..."), self.extract, "tenwin-zip"))
        menu.append(Gtk.SeparatorMenuItem())
        send = Gtk.MenuItem(label=_("Send to"))
        sub = Gtk.Menu()
        add_class(sub, "tw-menu")
        sub.append(menu_item(_("Compressed (zipped) folder"), self.compress, "tenwin-zip"))
        sub.append(menu_item(_("Desktop (create shortcut)"), self._link_to_desktop, "tenwin-desktop"))
        sub.append(menu_item(_("Mail recipient"), self.email, "tenwin-mail"))
        send.set_submenu(sub)
        menu.append(send)
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(menu_item(_("Cut"), self.cut))
        menu.append(menu_item(_("Copy"), self.copy))
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(menu_item(_("Create shortcut"), self._create_link))
        menu.append(menu_item(_("Delete"), self.delete))
        menu.append(menu_item(_("Rename"), self.rename, sensitive=len(rows) == 1))
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(menu_item(_("Properties"), self.properties))
        popup_menu(menu, event=event)

    def _background_menu(self, event):
        menu = Gtk.Menu()
        view = Gtk.MenuItem(label=_("View"))
        sub = Gtk.Menu()
        add_class(sub, "tw-menu")
        for key, text in (("xl", _("Extra large icons")), ("large", _("Large icons")), ("medium", _("Medium icons")),
                          ("small", _("Small icons")), ("list", _("List")), ("details", _("Details"))):
            mark = "•  " if self.settings["explorer.view"] == key else "    "
            sub.append(menu_item(mark + text, lambda k=key: self.settings.set("explorer.view", k)))
        view.set_submenu(sub)
        menu.append(view)
        sort = Gtk.MenuItem(label=_("Sort by"))
        sub = Gtk.Menu()
        add_class(sub, "tw-menu")
        for key, text in (("name", _("Name")), ("modified", _("Date modified")), ("type", _("Type")),
                          ("size", _("Size"))):
            sub.append(menu_item(text, lambda k=key: self.set_sort(k)))
        sort.set_submenu(sub)
        menu.append(sort)
        menu.append(menu_item(_("Refresh"), self.refresh))
        menu.append(Gtk.SeparatorMenuItem())
        if self.folder.is_trash:
            menu.append(menu_item(_("Empty Recycle Bin"), self.empty_trash))
        else:
            paste = menu_item(_("Paste"), self.paste)
            paste.set_sensitive(False)
            fileops.clipboard_has_files(lambda has: paste.set_sensitive(has and bool(self.current_dir())))
            menu.append(paste)
            menu.append(Gtk.SeparatorMenuItem())
            menu.append(menu_item(_("Open in Terminal"), self.open_terminal, "tenwin-terminal"))
            new = Gtk.MenuItem(label=_("New"))
            sub = Gtk.Menu()
            add_class(sub, "tw-menu")
            sub.append(menu_item(_("Folder"), self.new_folder, "tenwin-folder"))
            sub.append(menu_item(_("Text Document"), self.new_text_file, "tenwin-documents"))
            new.set_submenu(sub)
            menu.append(new)
            menu.append(Gtk.SeparatorMenuItem())
            menu.append(menu_item(_("Properties"), self.properties))
        popup_menu(menu, event=event)

    def _page_context(self, event, target):
        menu = Gtk.Menu()
        if isinstance(target, Gio.File):
            uri = target.get_uri()
            path = target.get_path()
            menu.append(menu_item(_("Open"), lambda: self.navigate(uri)))
            menu.append(menu_item(_("Open in new window"), lambda: self.get_application().open_window(uri)))
            if path in self.settings["explorer.quick_access"]:
                menu.append(menu_item(_("Unpin from Quick access"), lambda: self.unpin_quick_access(path)))
            menu.append(Gtk.SeparatorMenuItem())
            menu.append(menu_item(_("Properties"), lambda: PropertiesDialog([target], self)))
        else:
            obj, location = target
            if location is not None:
                menu.append(menu_item(_("Open"), lambda: self.navigate(location.get_uri())))
            if isinstance(obj, Gio.Mount) and (obj.can_eject() or obj.can_unmount()):
                menu.append(menu_item(_("Eject"), lambda: self._eject(obj)))
            if location is not None:
                menu.append(Gtk.SeparatorMenuItem())
                menu.append(menu_item(_("Properties"), lambda: PropertiesDialog([location], self)))
        popup_menu(menu, event=event)

    def _eject(self, mount):
        op = Gtk.MountOperation(parent=self)

        def done(m, result):
            try:
                (m.eject_with_operation_finish if m.can_eject() else m.unmount_with_operation_finish)(result)
            except GLib.Error as exc:
                self._error(_("Problem Ejecting Device"), exc.message)
            self.refresh()

        if mount.can_eject():
            mount.eject_with_operation(Gio.MountUnmountFlags.NONE, op, None, done)
        else:
            mount.unmount_with_operation(Gio.MountUnmountFlags.NONE, op, None, done)

    def _content_type(self, gfile):
        try:
            return gfile.query_info("standard::content-type", Gio.FileQueryInfoFlags.NONE,
                                    None).get_content_type()
        except GLib.Error:
            return None

    def _choose_app(self, files, ctype):
        dialog = Gtk.AppChooserDialog.new_for_content_type(self, Gtk.DialogFlags.MODAL, ctype)
        if dialog.run() == Gtk.ResponseType.OK and dialog.get_app_info() is not None:
            self.open_with(dialog.get_app_info(), files)
        dialog.destroy()

    def _create_link(self):
        directory = self.current_dir()
        for path in self.selected_local_paths():
            name = fileops.unique_name(directory, _("%s - Shortcut") % os.path.basename(path))
            try:
                os.symlink(path, os.path.join(directory, name))
            except OSError as exc:
                self._error(_("Create shortcut"), str(exc))

    def _link_to_desktop(self):
        from tenwin import paths
        desktop = paths.xdg_user_dir("DESKTOP")
        os.makedirs(desktop, exist_ok=True)
        for path in self.selected_local_paths():
            name = fileops.unique_name(desktop, _("%s - Shortcut") % os.path.basename(path))
            try:
                os.symlink(path, os.path.join(desktop, name))
            except OSError as exc:
                self._error(_("Create shortcut"), str(exc))

    # ------------------------------------------------------------ drag and drop

    def _setup_dnd(self, view):
        targets = [Gtk.TargetEntry.new("text/uri-list", 0, 0)]
        actions = Gdk.DragAction.COPY | Gdk.DragAction.MOVE
        view.enable_model_drag_source(Gdk.ModifierType.BUTTON1_MASK, targets, actions)
        view.enable_model_drag_dest(targets, actions)
        view.connect("drag-data-get", self._drag_get)
        view.connect("drag-data-received", self._drag_received)

    def _drag_get(self, _view, _context, data, _info, _time):
        data.set_uris([f.get_uri() for f in self.selected_files()])

    def _drag_received(self, view, context, x, y, data, _info, time):
        uris = data.get_uris()
        directory = self.current_dir()
        if view is self.tree:
            hit = self.tree.get_dest_row_at_pos(x, y)
            path = hit[0] if hit else None
        else:
            path = self.icons.get_path_at_pos(x, y)
        if path is not None:
            row = self.folder.store[path]
            if row[M.COL_IS_DIR] and row[M.COL_FILE].get_path():
                directory = row[M.COL_FILE].get_path()
        if not directory or not uris:
            context.finish(False, False, time)
            return
        sources = [Gio.File.new_for_uri(u) for u in uris]
        sources = [s for s in sources if s.get_parent() is None or s.get_parent().get_path() != directory]
        sources = [s for s in sources if s.get_path() != directory]
        if sources:
            move = context.get_selected_action() == Gdk.DragAction.MOVE
            if not move and context.get_selected_action() != Gdk.DragAction.COPY:
                move = self._same_fs(sources[0], directory)
            fileops.FileOperation(sources, directory, move=move, parent=self).start()
        context.finish(True, False, time)

    @staticmethod
    def _same_fs(gfile, directory):
        try:
            return os.stat(gfile.get_path()).st_dev == os.stat(directory).st_dev
        except (OSError, TypeError):
            return False

    # ------------------------------------------------------------ input

    def _on_mouse_nav(self, _widget, event):
        if event.button == 8:
            self.go_back()
            return True
        if event.button == 9:
            self.go_forward()
            return True
        return False

    def _on_key(self, _widget, event):
        if self.address_entry.has_focus() or self.search_entry.has_focus():
            if event.keyval == Gdk.KEY_Escape:
                self.address_stack.set_visible_child_name("crumbs")
                self.active_view().grab_focus()
                return True
            return False
        state = event.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK |
                               Gdk.ModifierType.SHIFT_MASK)
        ctrl = Gdk.ModifierType.CONTROL_MASK
        alt = Gdk.ModifierType.MOD1_MASK
        shift = Gdk.ModifierType.SHIFT_MASK
        key = Gdk.keyval_to_lower(event.keyval)
        editing = self.name_cell.get_property("editable") or self.icon_text.get_property("editable")
        if editing:
            return False
        bindings = {
            (alt, Gdk.KEY_Left): self.go_back, (alt, Gdk.KEY_Right): self.go_forward,
            (alt, Gdk.KEY_Up): self.go_up, (0, Gdk.KEY_BackSpace): self.go_back,
            (0, Gdk.KEY_F5): self.refresh, (ctrl, Gdk.KEY_r): self.refresh,
            (ctrl, Gdk.KEY_c): self.copy, (ctrl, Gdk.KEY_x): self.cut, (ctrl, Gdk.KEY_v): self.paste,
            (ctrl, Gdk.KEY_a): self.select_all, (0, Gdk.KEY_Delete): self.delete,
            (shift, Gdk.KEY_Delete): lambda: self.delete(permanent=True), (0, Gdk.KEY_F2): self.rename,
            (ctrl | shift, Gdk.KEY_n): self.new_folder,
            (ctrl, Gdk.KEY_n): lambda: self.get_application().open_window(self.location.get_uri()),
            (ctrl, Gdk.KEY_w): self.close, (alt, Gdk.KEY_Return): self.properties,
            (ctrl, Gdk.KEY_e): self.search_entry.grab_focus, (ctrl, Gdk.KEY_f): self.search_entry.grab_focus,
            (0, Gdk.KEY_F3): self.search_entry.grab_focus, (ctrl, Gdk.KEY_l): self._edit_address,
            (alt, Gdk.KEY_d): self._edit_address, (0, Gdk.KEY_F4): self._edit_address,
            (ctrl, Gdk.KEY_F1): lambda: self.ribbon.set_expanded(not self.ribbon.revealer.get_reveal_child()),
            (ctrl | shift, Gdk.KEY_6): lambda: self.settings.set("explorer.view", "details"),
            (ctrl | shift, Gdk.KEY_2): lambda: self.settings.set("explorer.view", "large"),
            (ctrl | shift, Gdk.KEY_1): lambda: self.settings.set("explorer.view", "xl"),
            (ctrl | shift, Gdk.KEY_3): lambda: self.settings.set("explorer.view", "medium"),
            (ctrl | shift, Gdk.KEY_4): lambda: self.settings.set("explorer.view", "small"),
            (ctrl | shift, Gdk.KEY_5): lambda: self.settings.set("explorer.view", "list"),
        }
        action = bindings.get((int(state), key))
        if action is None and key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not state:
            action = self.open_selected
        if action is not None:
            action()
            return True
        return False

    def _on_settings(self, _settings, keys):
        if "explorer.view" in keys:
            self._apply_view()
        if keys & {"explorer.show_hidden", "explorer.show_extensions"}:
            self.ribbon.ext_check.set_active(self.settings["explorer.show_extensions"])
            self.ribbon.hidden_check.set_active(self.settings["explorer.show_hidden"])
            self.folder.refill()
        if "explorer.nav_pane" in keys:
            self.nav.set_visible(self.settings["explorer.nav_pane"])
        if "explorer.quick_access" in keys and self.page == "quick":
            self.quick.refresh()


def empty_trash():
    trash = Gio.File.new_for_uri("trash:///")
    try:
        for info in trash.enumerate_children("standard::name", Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, None):
            try:
                trash.get_child(info.get_name()).delete(None)
            except GLib.Error:
                pass
    except GLib.Error:
        pass
