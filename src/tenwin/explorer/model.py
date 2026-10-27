"""Folder contents: asynchronous loading into a Gtk.ListStore."""

import math
import os

from gi.repository import Gio, GLib, GObject, Gtk

from tenwin.config import get_settings
from tenwin.gtkutil import format_datetime
from tenwin.i18n import _

ATTRS = ",".join([
    "standard::name", "standard::display-name", "standard::edit-name", "standard::icon",
    "standard::content-type", "standard::type", "standard::size", "standard::is-hidden",
    "standard::is-backup", "standard::is-symlink", "standard::target-uri", "time::modified",
    "time::created", "thumbnail::path", "trash::orig-path", "trash::deletion-date",
    "access::can-write", "access::can-rename", "access::can-delete", "access::can-trash",
])

# ListStore columns
COL_NAME, COL_FILE, COL_ICON, COL_IS_DIR, COL_SIZE, COL_SIZE_TEXT, COL_MTIME, COL_DATE_TEXT, \
    COL_TYPE_TEXT, COL_THUMB, COL_EXTRA, COL_SORT = range(12)

COLUMN_TYPES = (str, object, object, bool, GObject.TYPE_INT64, str, GObject.TYPE_INT64, str, str, object,
                str, str)


def size_text(size, is_dir):
    """Windows Explorer style: sizes in KB, rounded up."""
    if is_dir:
        return ""
    kb = int(math.ceil(size / 1024.0)) if size else 0
    text = "{:,}".format(kb)
    from tenwin.i18n import current_language
    if current_language() == "de":
        text = text.replace(",", ".")
    return "%s KB" % text


def type_text(info, is_dir):
    if is_dir:
        return _("File folder")
    ctype = info.get_content_type() or ""
    desc = Gio.content_type_get_description(ctype) if ctype else ""
    return desc or _("File")


def display_name(info, show_extensions):
    name = info.get_display_name() or info.get_name()
    if not show_extensions and info.get_file_type() != Gio.FileType.DIRECTORY:
        stem, ext = os.path.splitext(name)
        if stem and ext:
            return stem
    return name


class FolderModel(GObject.Object):
    """Loads a directory asynchronously; emits ``loaded`` and ``error``."""

    __gsignals__ = {
        "loaded": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__()
        self.store = Gtk.ListStore(*COLUMN_TYPES)
        self.location = None
        self.infos = []
        self.cancellable = None
        self.monitor = None
        self.sort_key = "name"
        self.sort_desc = False
        self._reload_id = 0
        self.is_trash = False

    def load(self, gfile):
        if self.cancellable is not None:
            self.cancellable.cancel()
        self.cancellable = Gio.Cancellable()
        self.location = gfile
        self.is_trash = gfile.get_uri_scheme() == "trash"
        self.infos = []
        self._start_monitor()
        gfile.enumerate_children_async(ATTRS, Gio.FileQueryInfoFlags.NONE, GLib.PRIORITY_DEFAULT,
                                       self.cancellable, self._on_enum, self.cancellable)

    def _start_monitor(self):
        if self.monitor is not None:
            self.monitor.cancel()
            self.monitor = None
        try:
            self.monitor = self.location.monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
            self.monitor.connect("changed", lambda *_: self._queue_reload())
        except GLib.Error:
            self.monitor = None

    def _queue_reload(self):
        if self._reload_id:
            return

        def run():
            self._reload_id = 0
            if self.location is not None:
                self.load(self.location)
            return GLib.SOURCE_REMOVE
        self._reload_id = GLib.timeout_add(300, run)

    def _on_enum(self, gfile, result, cancellable):
        try:
            enumerator = gfile.enumerate_children_finish(result)
        except GLib.Error as exc:
            if not cancellable.is_cancelled():
                self.emit("error", exc.message)
            return
        enumerator.next_files_async(200, GLib.PRIORITY_DEFAULT, cancellable, self._on_files, cancellable)

    def _on_files(self, enumerator, result, cancellable):
        try:
            infos = enumerator.next_files_finish(result)
        except GLib.Error as exc:
            if not cancellable.is_cancelled():
                self.emit("error", exc.message)
            return
        if cancellable.is_cancelled():
            return
        if infos:
            self.infos.extend(infos)
            enumerator.next_files_async(200, GLib.PRIORITY_DEFAULT, cancellable, self._on_files, cancellable)
        else:
            enumerator.close_async(GLib.PRIORITY_DEFAULT, None, None, None)
            self.refill()
            self.emit("loaded")

    def set_results(self, location, infos_with_parents):
        """Show search results: list of (parent Gio.File, Gio.FileInfo)."""
        if self.cancellable is not None:
            self.cancellable.cancel()
        self.location = location
        self.infos = infos_with_parents
        self.refill(search=True)
        self.emit("loaded")

    def refill(self, search=False):
        settings = get_settings()
        show_hidden = settings["explorer.show_hidden"]
        show_ext = settings["explorer.show_extensions"]
        rows = []
        for entry in self.infos:
            if isinstance(entry, tuple):
                parent, info = entry
            else:
                parent, info = self.location, entry
            if not show_hidden and (info.get_is_hidden() or info.get_is_backup()):
                continue
            is_dir = info.get_file_type() == Gio.FileType.DIRECTORY
            gfile = parent.get_child(info.get_name())
            if self.is_trash:
                extra = os.path.dirname(info.get_attribute_byte_string("trash::orig-path") or "")
                deletion = info.get_attribute_string("trash::deletion-date") or ""
                date_text = deletion.replace("T", " ")[:16]
                mtime = info.get_attribute_uint64("time::modified")
            else:
                extra = (parent.get_path() or parent.get_uri()) if search else ""
                mtime = info.get_attribute_uint64("time::modified")
                date_text = format_datetime(mtime) if mtime else ""
            size = info.get_size()
            thumb_path = info.get_attribute_byte_string("thumbnail::path")
            rows.append([display_name(info, show_ext), gfile, info.get_icon(), is_dir, size,
                         size_text(size, is_dir), mtime, date_text, type_text(info, is_dir),
                         thumb_path or None, extra, (info.get_display_name() or "").casefold()])
        key = self.sort_key
        if key == "size":
            rows.sort(key=lambda r: (not r[COL_IS_DIR], r[COL_SIZE], r[COL_SORT]))
        elif key == "type":
            rows.sort(key=lambda r: (not r[COL_IS_DIR], r[COL_TYPE_TEXT].casefold(), r[COL_SORT]))
        elif key == "modified":
            rows.sort(key=lambda r: (not r[COL_IS_DIR], r[COL_MTIME], r[COL_SORT]))
        else:
            rows.sort(key=lambda r: (not r[COL_IS_DIR], _natural(r[COL_SORT])))
        if self.sort_desc:
            dirs = [r for r in rows if r[COL_IS_DIR]]
            files = [r for r in rows if not r[COL_IS_DIR]]
            rows = list(reversed(dirs)) + list(reversed(files))
        self.store.clear()
        for row in rows:
            self.store.append(row)

    def set_sort(self, key, descending=None):
        if descending is None:
            descending = (not self.sort_desc) if key == self.sort_key else False
        self.sort_key = key
        self.sort_desc = descending
        self.refill()

    def stop(self):
        if self.cancellable is not None:
            self.cancellable.cancel()
        if self.monitor is not None:
            self.monitor.cancel()
            self.monitor = None


def _natural(text):
    """Natural sort: 'Bild 2' before 'Bild 10' (like Windows)."""
    import re
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", text)]
