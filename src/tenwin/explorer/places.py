"""Navigation pane tree plus the "Quick access" and "This PC" pages."""

import os

from gi.repository import Gio, GLib, GObject, Gtk, Pango

from tenwin import paths
from tenwin.config import get_settings
from tenwin.gtkutil import add_class, clear_children, flat_button, human_size, icon_image
from tenwin.i18n import _

QUICK_ACCESS = "tenwin://quick-access"
THIS_PC = "computer:///"
TRASH = "trash:///"

USER_DIRS = [("DESKTOP", "Desktop", "user-desktop"), ("DOWNLOAD", "Downloads", "folder-download"),
             ("DOCUMENTS", "Documents", "folder-documents"), ("MUSIC", "Music", "folder-music"),
             ("PICTURES", "Pictures", "folder-pictures"), ("VIDEOS", "Videos", "folder-videos")]


def user_dirs():
    result = []
    for kind, label, icon in USER_DIRS:
        path = paths.xdg_user_dir(kind)
        if os.path.isdir(path):
            result.append((os.path.basename(path) if kind != "DESKTOP" else _("Desktop"), path, icon))
    return result


def quick_access_folders():
    pins = get_settings()["explorer.quick_access"]
    folders = []
    defaults = [p for _n, p, _i in user_dirs() if os.path.basename(p) in
                {os.path.basename(paths.xdg_user_dir(k)) for k in ("DESKTOP", "DOWNLOAD", "DOCUMENTS", "PICTURES")}]
    for path in defaults + [p for p in pins if p not in defaults]:
        if os.path.isdir(path):
            folders.append(path)
    return folders


def drives():
    """[(name, Gio.File or None, icon, Gio.Mount|Gio.Volume|None, free, size)]"""
    result = []
    root = Gio.File.new_for_path("/")
    free, size = fs_usage(root)
    result.append((_("Local Disk (/)"), root, "tenwin-drive", None, free, size))
    home = Gio.File.new_for_path(os.path.expanduser("~"))
    hfree, hsize = fs_usage(home)
    if hsize and hsize != size:
        result.append((_("Home (%s)") % os.path.expanduser("~"), home, "tenwin-drive", None, hfree, hsize))
    monitor = Gio.VolumeMonitor.get()
    seen = set()
    for mount in monitor.get_mounts():
        if mount.is_shadowed():
            continue
        location = mount.get_root()
        uri = location.get_uri()
        if uri in seen or uri in ("file:///",):
            continue
        seen.add(uri)
        mfree, msize = fs_usage(location)
        result.append((mount.get_name(), location, "tenwin-drive-removable" if mount.can_eject() or
                       mount.can_unmount() else "tenwin-drive", mount, mfree, msize))
    for volume in monitor.get_volumes():
        if volume.get_mount() is None and volume.can_mount():
            result.append((volume.get_name(), None, "tenwin-drive-removable", volume, 0, 0))
    return result


def fs_usage(gfile):
    try:
        info = gfile.query_filesystem_info("filesystem::size,filesystem::free", None)
        return info.get_attribute_uint64("filesystem::free"), info.get_attribute_uint64("filesystem::size")
    except GLib.Error:
        return 0, 0


class NavPane(Gtk.ScrolledWindow):
    """Tree with Quick access, This PC, drives, Network and Recycle Bin."""

    __gsignals__ = {"navigate": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    COL_ICON, COL_NAME, COL_URI, COL_LOADED = range(4)

    def __init__(self):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER)
        add_class(self, "tw-navpane")
        self.store = Gtk.TreeStore(Gio.Icon, str, str, bool)
        self.tree = Gtk.TreeView(model=self.store, headers_visible=False, enable_search=False)
        self.tree.set_show_expanders(True)
        self.tree.set_level_indentation(4)
        column = Gtk.TreeViewColumn()
        icon = Gtk.CellRendererPixbuf()
        icon.set_property("stock-size", Gtk.IconSize.MENU)
        column.pack_start(icon, False)
        column.add_attribute(icon, "gicon", self.COL_ICON)
        text = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        column.pack_start(text, True)
        column.add_attribute(text, "text", self.COL_NAME)
        self.tree.append_column(column)
        self.tree.connect("row-activated", self._on_activated)
        self.tree.connect("test-expand-row", self._on_expand)
        self.tree.get_selection().connect("changed", self._on_selected)
        self._suppress = False
        self.add(self.tree)
        self.populate()
        monitor = Gio.VolumeMonitor.get()
        for sig in ("mount-added", "mount-removed", "volume-added", "volume-removed"):
            monitor.connect(sig, lambda *_: self.populate())
        get_settings().connect("changed", lambda _s, keys: "explorer.quick_access" in keys and self.populate())

    def _gicon(self, name):
        return Gio.ThemedIcon.new_with_default_fallbacks(name)

    def _add_folder(self, parent, name, path_or_uri, icon):
        uri = path_or_uri if "://" in path_or_uri else Gio.File.new_for_path(path_or_uri).get_uri()
        it = self.store.append(parent, [self._gicon(icon) if isinstance(icon, str) else icon, name, uri, False])
        self.store.append(it, [None, "", "", True])  # placeholder so the row is expandable
        return it

    def populate(self):
        self.store.clear()
        qa = self.store.append(None, [self._gicon("tenwin-star-symbolic"), _("Quick access"), QUICK_ACCESS, True])
        for path in quick_access_folders():
            self._add_folder(qa, os.path.basename(path) or path, path, "folder")
        pc = self.store.append(None, [self._gicon("tenwin-this-pc"), _("This PC"), THIS_PC, True])
        for name, path, icon in user_dirs():
            self._add_folder(pc, name, path, icon)
        for name, location, icon, _obj, _free, _size in drives():
            if location is not None:
                self._add_folder(pc, name, location.get_uri(), icon)
        self.store.append(None, [self._gicon("tenwin-network-symbolic"), _("Network"), "network:///", True])
        self.store.append(None, [self._gicon("tenwin-trash-empty"), _("Recycle Bin"), TRASH, True])
        self.tree.expand_row(self.store.get_path(qa), False)
        self.tree.expand_row(self.store.get_path(pc), False)

    def _on_expand(self, _tree, it, _path):
        if self.store[it][self.COL_LOADED]:
            return False
        self.store[it][self.COL_LOADED] = True
        child = self.store.iter_children(it)
        uri = self.store[it][self.COL_URI]
        gfile = Gio.File.new_for_uri(uri)
        subdirs = []
        try:
            for info in gfile.enumerate_children("standard::name,standard::display-name,standard::type,"
                                                 "standard::is-hidden,standard::icon",
                                                 Gio.FileQueryInfoFlags.NONE, None):
                if info.get_file_type() == Gio.FileType.DIRECTORY and not info.get_is_hidden():
                    subdirs.append((info.get_display_name(), gfile.get_child(info.get_name()).get_uri(),
                                    info.get_icon()))
        except GLib.Error:
            pass
        subdirs.sort(key=lambda s: s[0].casefold())
        for name, sub_uri, icon in subdirs[:500]:
            self._add_folder(it, name, sub_uri, icon)
        if child is not None:
            self.store.remove(child)
        return False

    def _on_activated(self, _tree, path, _column):
        if self.tree.row_expanded(path):
            self.tree.collapse_row(path)
        else:
            self.tree.expand_row(path, False)

    def _on_selected(self, selection):
        if self._suppress:
            return
        model, it = selection.get_selected()
        if it is not None and model[it][self.COL_URI]:
            self.emit("navigate", model[it][self.COL_URI])

    def highlight(self, uri):
        """Select the row for ``uri`` without navigating."""
        found = []

        def visit(model, path, it):
            if model[it][self.COL_URI] == uri:
                found.append(path.copy())
                return True
            return False

        self.store.foreach(visit)
        self._suppress = True
        selection = self.tree.get_selection()
        if found:
            selection.select_path(found[0])
        else:
            selection.unselect_all()
        self._suppress = False


class TilePage(Gtk.ScrolledWindow):
    """Base for the Quick access and This PC pages."""

    __gsignals__ = {
        "navigate": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "open-file": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "context": (GObject.SignalFlags.RUN_FIRST, None, (object, object)),
    }

    def __init__(self):
        super().__init__()
        add_class(self, "tw-tile-page")
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.box.set_margin_start(16)
        self.box.set_margin_top(8)
        self.add(self.box)

    def section(self, title, count):
        expander = Gtk.Expander(expanded=True)
        head = Gtk.Box(spacing=8)
        head.pack_start(add_class(Gtk.Label(label="%s (%d)" % (title, count)), "tw-section-head"), False, False, 0)
        line = Gtk.Separator()
        line.set_valign(Gtk.Align.CENTER)
        head.pack_start(line, True, True, 0)
        expander.set_label_widget(head)
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=4, row_spacing=4)
        flow.set_max_children_per_line(8)
        flow.set_min_children_per_line(1)
        flow.set_homogeneous(True)
        expander.add(flow)
        self.box.pack_start(expander, False, False, 6)
        return flow

    def tile(self, icon, title, subtitle=None, on_open=None, usage=None, on_context=None):
        button = flat_button(css="tw-pc-tile")
        box = Gtk.Box(spacing=10)
        box.pack_start(icon_image(icon, 48), False, False, 0)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        texts.set_valign(Gtk.Align.CENTER)
        name = Gtk.Label(label=title, xalign=0)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        name.set_max_width_chars(26)
        texts.pack_start(name, False, False, 0)
        if usage is not None:
            free, size = usage
            bar = add_class(Gtk.LevelBar(), "tw-drive-bar")
            bar.set_min_value(0)
            bar.set_max_value(1)
            used = (size - free) / size if size else 0
            bar.set_value(used)
            if used > 0.9:
                add_class(bar, "full")
            bar.set_size_request(200, 14)
            texts.pack_start(bar, False, False, 0)
        if subtitle:
            sub = add_class(Gtk.Label(label=subtitle, xalign=0), "tw-dim")
            sub.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            sub.set_max_width_chars(30)
            texts.pack_start(sub, False, False, 0)
        box.pack_start(texts, True, True, 0)
        button.add(box)
        if on_open:
            button.connect("clicked", lambda *_: on_open())
        if on_context:
            button.connect("button-release-event", lambda _w, e: e.button == 3 and (on_context(e) or True))
        return button


class ThisPCPage(TilePage):
    def refresh(self):
        clear_children(self.box)
        folders = user_dirs()
        flow = self.section(_("Folders"), len(folders))
        for name, path, icon in folders:
            uri = Gio.File.new_for_path(path).get_uri()
            flow.add(self.tile(icon, name, None, lambda u=uri: self.emit("navigate", u),
                               on_context=lambda e, u=uri: self.emit("context", e, Gio.File.new_for_uri(u))))
        devs = drives()
        flow = self.section(_("Devices and drives"), len(devs))
        for name, location, icon, obj, free, size in devs:
            subtitle = (_("%s free of %s") % (human_size(free), human_size(size))) if size else None
            if location is not None:
                open_cb = (lambda u=location.get_uri(): self.emit("navigate", u))
            else:
                open_cb = (lambda v=obj: self._mount(v))
            flow.add(self.tile(icon, name, subtitle, open_cb, usage=(free, size) if size else None,
                               on_context=lambda e, o=obj, l=location: self.emit("context", e, (o, l))))
        from tenwin.explorer import network
        mounted = {d[1].get_uri() for d in devs if d[1] is not None}
        saved = [d for d in network.saved_drives() if d["uri"] not in mounted]
        if saved:
            flow = self.section(_("Network locations"), len(saved))
            for drive in saved:
                uri = drive["uri"]
                flow.add(self.tile("tenwin-network", drive["name"], Gio.File.new_for_uri(uri).get_parse_name(),
                                   lambda u=uri: self.emit("navigate", u),
                                   on_context=lambda e, u=uri: self.emit("context", e, ("network-drive", u))))
        self.show_all()

    def _mount(self, volume):
        op = Gtk.MountOperation()

        def done(vol, result):
            try:
                vol.mount_finish(result)
            except GLib.Error:
                return
            mount = vol.get_mount()
            if mount is not None:
                self.emit("navigate", mount.get_root().get_uri())

        volume.mount(Gio.MountMountFlags.NONE, op, None, done)


class QuickAccessPage(TilePage):
    def refresh(self):
        clear_children(self.box)
        folders = quick_access_folders()
        flow = self.section(_("Frequent folders"), len(folders))
        for path in folders:
            uri = Gio.File.new_for_path(path).get_uri()
            flow.add(self.tile("folder", os.path.basename(path) or path, os.path.dirname(path),
                               lambda u=uri: self.emit("navigate", u),
                               on_context=lambda e, u=uri: self.emit("context", e, Gio.File.new_for_uri(u))))
        manager = Gtk.RecentManager.get_default()
        items = [i for i in manager.get_items() if i.exists() and i.is_local()]
        items.sort(key=lambda i: -i.get_modified())
        items = items[:20]
        recent = self.section(_("Recent files"), len(items))
        recent.set_max_children_per_line(1)
        for item in items:
            path = Gio.File.new_for_uri(item.get_uri()).get_path() or item.get_uri()
            row = flat_button(css="tw-recent-row")
            box = Gtk.Box(spacing=10)
            box.pack_start(icon_image(item.get_gicon(), 16), False, False, 0)
            name = Gtk.Label(label=item.get_display_name(), xalign=0)
            name.set_size_request(320, -1)
            name.set_ellipsize(Pango.EllipsizeMode.END)
            box.pack_start(name, False, False, 0)
            loc = add_class(Gtk.Label(label=os.path.dirname(path), xalign=0), "tw-dim")
            loc.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            box.pack_start(loc, True, True, 0)
            row.add(box)
            row.connect("clicked", lambda _b, u=item.get_uri(): self.emit("open-file", u))
            recent.add(row)
        self.show_all()
