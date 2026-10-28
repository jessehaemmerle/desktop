"""Preview pane (Alt+P) and details pane (Alt+Shift+P) of the Explorer."""

import os

from gi.repository import GdkPixbuf, Gio, GLib, Gtk, Pango

from tenwin.gtkutil import add_class, clear_children, human_size, icon_image
from tenwin.i18n import _, ngettext

TEXT_LIMIT = 256 * 1024
TEXT_LINES = 400
IMAGE_TYPES = ("image/",)
TEXT_TYPES = ("text/", "application/json", "application/xml", "application/x-shellscript",
              "application/javascript", "application/x-desktop", "application/toml", "application/yaml")


def is_text(content_type):
    return bool(content_type) and content_type.startswith(TEXT_TYPES)


def is_image(content_type):
    return bool(content_type) and content_type.startswith(IMAGE_TYPES)


def read_text(path, limit=TEXT_LIMIT, lines=TEXT_LINES):
    """Start of a text file for the preview, or None if it isn't text."""
    try:
        with open(path, "rb") as fh:
            data = fh.read(limit)
    except OSError:
        return None
    if b"\0" in data:
        return None
    text = data.decode("utf-8", errors="replace")
    return "\n".join(text.splitlines()[:lines])


def format_time(seconds):
    if not seconds:
        return ""
    return GLib.DateTime.new_from_unix_local(int(seconds)).format("%x %H:%M")


class SidePane(Gtk.Box):
    """Shows the preview or the details of the selection, depending on ``mode``."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        add_class(self, "tw-side-pane")
        self.set_size_request(260, -1)
        self.mode = "preview"
        self._cancel = None

    def show_selection(self, files, folder_count=None):
        """``files``: list of (Gio.File, display name, content type, is_dir, size, mtime)."""
        clear_children(self)
        if self._cancel is not None:
            self._cancel.cancel()
            self._cancel = None
        if self.mode == "preview":
            self._preview(files)
        else:
            self._details(files, folder_count)
        self.show_all()

    # -- preview -----------------------------------------------------------------

    def _message(self, text):
        label = add_class(Gtk.Label(label=text, wrap=True, justify=Gtk.Justification.CENTER), "tw-dim")
        label.set_valign(Gtk.Align.CENTER)
        label.set_vexpand(True)
        label.set_margin_start(16)
        label.set_margin_end(16)
        self.pack_start(label, True, True, 0)

    def _preview(self, files):
        if len(files) != 1:
            self._message(_("Select a file to preview.") if not files else _("No preview available."))
            return
        gfile, _name, ctype, is_dir, size, _mtime = files[0]
        path = gfile.get_path()
        if is_dir or path is None:
            self._message(_("No preview available."))
        elif is_image(ctype):
            self._image_preview(path)
        elif is_text(ctype) or Gio.content_type_is_a(ctype or "", "text/plain"):
            text = read_text(path)
            if text is None:
                self._message(_("No preview available."))
                return
            view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True)
            view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            view.get_buffer().set_text(text)
            add_class(view, "tw-preview-text")
            scroll = Gtk.ScrolledWindow()
            scroll.add(view)
            self.pack_start(scroll, True, True, 0)
        else:
            self._message(_("No preview available."))

    def _image_preview(self, path):
        width = max(200, self.get_allocated_width() - 24)
        image = Gtk.Image()
        image.set_valign(Gtk.Align.CENTER)
        image.set_vexpand(True)
        self.pack_start(image, True, True, 0)
        self._cancel = Gio.Cancellable()
        stream_file = Gio.File.new_for_path(path)

        def loaded(source, result, _data):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_stream_finish(result)
            except GLib.Error:
                if image.get_parent() is not None:
                    clear_children(self)
                    self._message(_("No preview available."))
                    self.show_all()
                return
            image.set_from_pixbuf(pixbuf)

        def opened(source, result, _data):
            try:
                stream = source.read_finish(result)
            except GLib.Error:
                return
            GdkPixbuf.Pixbuf.new_from_stream_at_scale_async(stream, width, width, True, self._cancel,
                                                            loaded, None)

        stream_file.read_async(GLib.PRIORITY_DEFAULT, self._cancel, opened, None)

    # -- details -------------------------------------------------------------------

    def _details(self, files, folder_count):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(16)
        self.pack_start(box, False, False, 0)
        if not files:
            if folder_count is not None:
                box.pack_start(add_class(Gtk.Label(label=ngettext("%d item", "%d items", folder_count)
                                                   % folder_count, xalign=0), "tw-details-title"), False, False, 0)
            return
        if len(files) > 1:
            box.pack_start(add_class(Gtk.Label(label=ngettext("%d item selected", "%d items selected", len(files))
                                               % len(files), xalign=0), "tw-details-title"), False, False, 0)
            total = sum(f[4] for f in files if not f[3])
            if total:
                self._row(box, _("Total size:"), human_size(total))
            return
        gfile, name, ctype, is_dir, size, mtime = files[0]
        icon = Gio.content_type_get_icon(ctype) if ctype else None
        big = icon_image("folder" if is_dir else icon, 96)
        big.set_halign(Gtk.Align.CENTER)
        box.pack_start(big, False, False, 6)
        title = add_class(Gtk.Label(label=name, xalign=0, wrap=True), "tw-details-title")
        title.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        box.pack_start(title, False, False, 0)
        kind = _("File folder") if is_dir else (Gio.content_type_get_description(ctype) if ctype else _("File"))
        box.pack_start(add_class(Gtk.Label(label=kind, xalign=0), "tw-dim"), False, False, 0)
        self._row(box, _("Date modified:"), format_time(mtime))
        if not is_dir:
            self._row(box, _("Size:"), human_size(size))
        path = gfile.get_path()
        if path:
            try:
                st = os.stat(path)
                created = getattr(st, "st_birthtime", None)
                if created:
                    self._row(box, _("Created:"), format_time(created))
            except OSError:
                pass
            if is_image(ctype):
                info = GdkPixbuf.Pixbuf.get_file_info(path)
                if info and info[0] is not None:
                    self._row(box, _("Dimensions:"), "%d × %d" % (info[1], info[2]))

    def _row(self, box, label, value):
        if not value:
            return
        row = Gtk.Box(spacing=8)
        row.pack_start(add_class(Gtk.Label(label=label, xalign=0), "tw-dim"), False, False, 0)
        val = Gtk.Label(label=value, xalign=0, selectable=True)
        val.set_ellipsize(Pango.EllipsizeMode.END)
        row.pack_start(val, True, True, 0)
        box.pack_start(row, False, False, 0)
