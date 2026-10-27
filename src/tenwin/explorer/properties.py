"""File properties dialog (General / Permissions)."""

import grp
import os
import pwd
import stat
import threading

from gi.repository import Gio, GLib, Gtk, Pango

from tenwin import fileops
from tenwin.gtkutil import add_class, format_datetime, human_size, icon_image
from tenwin.i18n import _, ngettext


def _bytes_text(n):
    text = "{:,}".format(n)
    from tenwin.i18n import current_language
    if current_language() == "de":
        text = text.replace(",", ".")
    return text


class PropertiesDialog(Gtk.Window):
    def __init__(self, files, parent=None):
        super().__init__()
        add_class(self, "tw-app-window", "tw-properties")
        self.files = files
        self.set_default_size(380, 500)
        self.set_resizable(False)
        if parent is not None:
            self.set_transient_for(parent)
        single = len(files) == 1
        self.info = None
        if single:
            try:
                self.info = files[0].query_info("*", Gio.FileQueryInfoFlags.NONE, None)
            except GLib.Error:
                self.info = None
        title = (self.info.get_display_name() if self.info else files[0].get_basename()) if single else \
            ngettext("%d item", "%d items", len(files)) % len(files)
        self.set_title(_("%s Properties") % title)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        notebook = Gtk.Notebook()
        notebook.set_margin_start(8)
        notebook.set_margin_end(8)
        notebook.set_margin_top(8)
        notebook.append_page(self._general(single), Gtk.Label(label=_("General")))
        if single and files[0].get_path():
            notebook.append_page(self._permissions(), Gtk.Label(label=_("Security")))
        box.pack_start(notebook, True, True, 0)

        buttons = Gtk.Box(spacing=8)
        buttons.set_margin_top(10)
        buttons.set_margin_bottom(10)
        buttons.set_margin_end(10)
        for label, cb in ((_("Apply"), self.apply), (_("Cancel"), self.destroy), (_("OK"), self.ok)):
            button = Gtk.Button(label=label)
            button.set_size_request(80, -1)
            button.connect("clicked", lambda _b, c=cb: c())
            buttons.pack_end(button, False, False, 0)
        box.pack_start(buttons, False, False, 0)
        self.add(box)
        self.show_all()

    # -- General ------------------------------------------------------------

    def _grid(self):
        grid = Gtk.Grid(column_spacing=20, row_spacing=8)
        grid.set_margin_start(14)
        grid.set_margin_end(14)
        grid.set_margin_top(14)
        grid.set_margin_bottom(14)
        self._row = 0
        return grid

    def _add(self, grid, label, value_widget):
        grid.attach(Gtk.Label(label=label, xalign=0, yalign=0), 0, self._row, 1, 1)
        grid.attach(value_widget, 1, self._row, 1, 1)
        self._row += 1

    def _sep(self, grid):
        grid.attach(Gtk.Separator(margin_top=4, margin_bottom=4), 0, self._row, 2, 1)
        self._row += 1

    def _value(self, text):
        label = Gtk.Label(label=text, xalign=0, selectable=True)
        label.set_line_wrap(True)
        label.set_line_wrap_mode(Pango.WrapMode.CHAR)
        label.set_max_width_chars(34)
        return label

    def _general(self, single):
        grid = self._grid()
        files = self.files
        info = self.info
        icon = info.get_icon() if info else "text-x-generic"
        top = Gtk.Box(spacing=14)
        top.pack_start(icon_image(icon if single else "edit-copy", 32), False, False, 0)
        self.name_entry = Gtk.Entry(text=(info.get_display_name() if info else files[0].get_basename())
                                    if single else "")
        self.name_entry.set_sensitive(single and bool(files[0].get_path()))
        self.name_entry.set_hexpand(True)
        top.pack_start(self.name_entry, True, True, 0)
        grid.attach(top, 0, self._row, 2, 1)
        self._row += 1
        self._sep(grid)

        is_dir = bool(info) and info.get_file_type() == Gio.FileType.DIRECTORY
        if single and info:
            ctype = info.get_content_type() or ""
            desc = _("File folder") if is_dir else (Gio.content_type_get_description(ctype) or _("File"))
            self._add(grid, _("Type of file:") if not is_dir else _("Type:"), self._value(desc))
            if not is_dir:
                app = Gio.AppInfo.get_default_for_type(ctype, False) if ctype else None
                opens = Gtk.Box(spacing=8)
                opens.pack_start(Gtk.Label(label=app.get_display_name() if app else _("(unknown)"), xalign=0),
                                 True, True, 0)
                change = Gtk.Button(label=_("Change..."))
                change.connect("clicked", lambda *_: self._choose_app(ctype))
                opens.pack_end(change, False, False, 0)
                self._add(grid, _("Opens with:"), opens)
            self._sep(grid)
            parent = files[0].get_parent()
            self._add(grid, _("Location:"), self._value(parent.get_path() or parent.get_uri() if parent else ""))
        self.size_label = self._value(_("Calculating…"))
        self.disk_label = None
        self._add(grid, _("Size:"), self.size_label)
        if is_dir or not single:
            self.contains_label = self._value("")
            self._add(grid, _("Contains:"), self.contains_label)
        else:
            self.contains_label = None
        self._sep(grid)
        if single and info:
            created = info.get_attribute_uint64("time::created")
            if created:
                self._add(grid, _("Created:"), self._value(format_datetime(created)))
            modified = info.get_attribute_uint64("time::modified")
            if modified:
                self._add(grid, _("Modified:"), self._value(format_datetime(modified)))
            accessed = info.get_attribute_uint64("time::access")
            if accessed:
                self._add(grid, _("Accessed:"), self._value(format_datetime(accessed)))
            self._sep(grid)
            attrs = Gtk.Box(spacing=14)
            self.readonly = Gtk.CheckButton(label=_("Read-only"))
            path = files[0].get_path()
            self.readonly.set_active(bool(path) and not os.access(path, os.W_OK))
            self.readonly.set_sensitive(bool(path) and not is_dir)
            self._readonly_initial = self.readonly.get_active()
            attrs.pack_start(self.readonly, False, False, 0)
            hidden = Gtk.CheckButton(label=_("Hidden"))
            hidden.set_active(info.get_is_hidden())
            hidden.set_sensitive(False)
            hidden.set_tooltip_text(_("On Linux, files whose names start with a dot are hidden."))
            attrs.pack_start(hidden, False, False, 0)
            self._add(grid, _("Attributes:"), attrs)
        else:
            self.readonly = None
        threading.Thread(target=self._compute_size, daemon=True).start()
        return grid

    def _compute_size(self):
        total, nfiles, ndirs = 0, 0, 0
        for gfile in self.files:
            path = gfile.get_path()
            if path is None:
                continue
            if os.path.isdir(path) and not os.path.islink(path):
                ndirs += 0 if len(self.files) == 1 else 1
                for root, dirs, names in os.walk(path):
                    ndirs += len(dirs)
                    for name in names:
                        nfiles += 1
                        try:
                            total += os.lstat(os.path.join(root, name)).st_size
                        except OSError:
                            pass
            else:
                nfiles += 1
                try:
                    total += os.lstat(path).st_size
                except OSError:
                    pass
        GLib.idle_add(self._show_size, total, nfiles, ndirs)

    def _show_size(self, total, nfiles, ndirs):
        self.size_label.set_text(_("%s (%s bytes)") % (human_size(total), _bytes_text(total)))
        if self.contains_label is not None:
            self.contains_label.set_text(_("%s, %s") % (ngettext("%d File", "%d Files", nfiles) % nfiles,
                                                        ngettext("%d Folder", "%d Folders", ndirs) % ndirs))
        return False

    def _choose_app(self, ctype):
        dialog = Gtk.AppChooserDialog.new_for_content_type(self, Gtk.DialogFlags.MODAL, ctype)
        if dialog.run() == Gtk.ResponseType.OK:
            app = dialog.get_app_info()
            if app is not None:
                try:
                    app.set_as_default_for_type(ctype)
                except GLib.Error:
                    pass
        dialog.destroy()

    # -- Permissions --------------------------------------------------------

    def _permissions(self):
        grid = self._grid()
        path = self.files[0].get_path()
        try:
            st = os.lstat(path)
        except OSError:
            return grid
        self.mode = st.st_mode
        try:
            owner = pwd.getpwuid(st.st_uid).pw_name
        except KeyError:
            owner = str(st.st_uid)
        try:
            group = grp.getgrgid(st.st_gid).gr_name
        except KeyError:
            group = str(st.st_gid)
        self._add(grid, _("Owner:"), self._value(owner))
        self._add(grid, _("Group:"), self._value(group))
        self._sep(grid)
        table = Gtk.Grid(column_spacing=18, row_spacing=6)
        for col, text in enumerate((_("Read"), _("Write"), _("Execute")), start=1):
            table.attach(Gtk.Label(label=text), col, 0, 1, 1)
        self.perm_checks = {}
        rows = ((_("Owner"), (stat.S_IRUSR, stat.S_IWUSR, stat.S_IXUSR)),
                (_("Group"), (stat.S_IRGRP, stat.S_IWGRP, stat.S_IXGRP)),
                (_("Others"), (stat.S_IROTH, stat.S_IWOTH, stat.S_IXOTH)))
        can_change = st.st_uid == os.getuid()
        for row, (label, bits) in enumerate(rows, start=1):
            table.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
            for col, bit in enumerate(bits, start=1):
                check = Gtk.CheckButton()
                check.set_active(bool(st.st_mode & bit))
                check.set_sensitive(can_change)
                check.set_halign(Gtk.Align.CENTER)
                table.attach(check, col, row, 1, 1)
                self.perm_checks[bit] = check
        grid.attach(table, 0, self._row, 2, 1)
        self._row += 1
        if not can_change:
            note = add_class(Gtk.Label(label=_("Only the owner can change permissions."), xalign=0), "tw-dim")
            grid.attach(note, 0, self._row, 2, 1)
        return grid

    # -- apply ------------------------------------------------------------

    def apply(self):
        if len(self.files) != 1 or not self.files[0].get_path():
            return True
        path = self.files[0].get_path()
        try:
            current = stat.S_IMODE(os.lstat(path).st_mode)
            mode = current
            for bit, check in getattr(self, "perm_checks", {}).items():
                mode = (mode | bit) if check.get_active() else (mode & ~bit)
            # "Read-only" on the General tab wins when it was changed.
            if self.readonly is not None and self.readonly.get_active() != self._readonly_initial:
                mode = (mode & ~stat.S_IWUSR) if self.readonly.get_active() else (mode | stat.S_IWUSR)
                self._readonly_initial = self.readonly.get_active()
            if mode != current and not os.path.islink(path):
                os.chmod(path, mode)
            new_name = self.name_entry.get_text().strip()
            if new_name and new_name != os.path.basename(path):
                new_path = fileops.rename(path, new_name)
                self.files = [Gio.File.new_for_path(new_path)]
        except (OSError, ValueError) as exc:
            dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.ERROR,
                                       buttons=Gtk.ButtonsType.OK, text=str(exc))
            dialog.run()
            dialog.destroy()
            return False
        return True

    def ok(self):
        if self.apply():
            self.destroy()
