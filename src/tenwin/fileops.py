"""File operations shared by the desktop and the Explorer.

Copy/move run in a worker thread and report progress to a Windows 10 style
dialog. Name conflicts are resolved with a "Replace or Skip Files" dialog.
"""

import os
import threading

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from tenwin.gtkutil import add_class, human_size
from tenwin.i18n import _, ngettext

GNOME_COPIED = "x-special/gnome-copied-files"


# ------------------------------------------------------------------ clipboard

_clip_store = {"uris": [], "cut": False}


def clipboard_set(paths_or_uris, cut=False):
    uris = [u if "://" in u else Gio.File.new_for_path(u).get_uri() for u in paths_or_uris]
    _clip_store["uris"] = uris
    _clip_store["cut"] = cut
    clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
    targets = [Gtk.TargetEntry.new(GNOME_COPIED, 0, 0), Gtk.TargetEntry.new("text/uri-list", 0, 1),
               Gtk.TargetEntry.new("UTF8_STRING", 0, 2), Gtk.TargetEntry.new("text/plain", 0, 3)]

    def get(_clip, selection, info, _data):
        if info == 0:
            payload = ("cut" if cut else "copy") + "\n" + "\n".join(uris)
            selection.set(Gdk.Atom.intern(GNOME_COPIED, False), 8, payload.encode())
        elif info == 1:
            selection.set_uris(uris)
        else:
            selection.set_text("\n".join(Gio.File.new_for_uri(u).get_path() or u for u in uris), -1)

    def clear(_clip, _data):
        pass

    try:
        clipboard.set_with_data(targets, get, clear, None)
    except TypeError:
        # Older PyGObject lacks set_with_data: fall back to plain text.
        clipboard.set_text("\n".join(uris), -1)
    clipboard.store()


def clipboard_get(callback):
    """callback(uris, cut) with the file URIs on the clipboard."""
    clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)

    def on_gnome(_clip, selection, _data):
        data = selection.get_data() if selection is not None else None
        if data:
            lines = data.decode(errors="replace").splitlines()
            if lines and lines[0] in ("copy", "cut"):
                callback([l for l in lines[1:] if l], lines[0] == "cut")
                return
        clipboard.request_uris(on_uris, None)

    def on_uris(_clip, uris, _data):
        if uris:
            callback(list(uris), False)
        elif _clip_store["uris"]:
            callback(list(_clip_store["uris"]), _clip_store["cut"])
        else:
            callback([], False)

    clipboard.request_contents(Gdk.Atom.intern(GNOME_COPIED, False), on_gnome, None)


def clipboard_has_files(callback):
    clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)

    def on_targets(_clip, atoms, _n, _data=None):
        names = {a.name() for a in (atoms or [])}
        callback(bool(names & {GNOME_COPIED, "text/uri-list"}) or bool(_clip_store["uris"]))

    clipboard.request_targets(on_targets, None)


# ------------------------------------------------------------------ helpers

def unique_name(directory, name):
    """'Neuer Ordner' -> 'Neuer Ordner (2)' if needed (Windows style)."""
    base, ext = os.path.splitext(name)
    if os.path.isdir(os.path.join(directory, name)):
        base, ext = name, ""
    candidate = name
    n = 2
    while os.path.lexists(os.path.join(directory, candidate)):
        candidate = "%s (%d)%s" % (base, n, ext)
        n += 1
    return candidate


def new_folder(directory):
    name = unique_name(directory, _("New folder"))
    os.mkdir(os.path.join(directory, name))
    return os.path.join(directory, name)


def new_text_file(directory):
    name = unique_name(directory, _("New Text Document") + ".txt")
    path = os.path.join(directory, name)
    with open(path, "x", encoding="utf-8"):
        pass
    return path


def valid_name(name):
    return bool(name) and name not in (".", "..") and "/" not in name and "\0" not in name


def rename(path, new_name):
    """Rename in place; raises OSError/ValueError with a user-facing message."""
    if not valid_name(new_name):
        raise ValueError(_("A file name can't contain the character /"))
    target = os.path.join(os.path.dirname(path), new_name)
    if os.path.lexists(target) and os.path.normcase(target) != os.path.normcase(path):
        raise ValueError(_("There is already a file with the same name in this location."))
    os.rename(path, target)
    return target


def trash(paths, parent=None):
    """Move to the recycle bin; returns paths that could not be trashed."""
    failed = []
    for path in paths:
        try:
            Gio.File.new_for_path(path).trash(None)
        except GLib.Error:
            failed.append(path)
    if failed and parent is not None:
        dialog = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.WARNING,
                                   buttons=Gtk.ButtonsType.YES_NO,
                                   text=_("These items can't be moved to the Recycle Bin."))
        dialog.format_secondary_text(_("Do you want to permanently delete them?"))
        if dialog.run() == Gtk.ResponseType.YES:
            delete_permanently(failed)
            failed = []
        dialog.destroy()
    return failed


def delete_permanently(paths):
    for path in paths:
        _delete_tree(Gio.File.new_for_path(path))


def _delete_tree(gfile):
    try:
        info = gfile.query_info("standard::type", Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, None)
        if info.get_file_type() == Gio.FileType.DIRECTORY:
            for child in gfile.enumerate_children("standard::name", Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
                                                  None):
                _delete_tree(gfile.get_child(child.get_name()))
        gfile.delete(None)
    except GLib.Error:
        pass


def confirm_delete(parent, count, permanent):
    if permanent:
        text = ngettext("Are you sure you want to permanently delete this item?",
                        "Are you sure you want to permanently delete these %d items?", count) % count
    else:
        return True
    dialog = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.WARNING,
                               buttons=Gtk.ButtonsType.YES_NO, text=text)
    dialog.set_title(_("Delete File") if count == 1 else _("Delete Multiple Items"))
    result = dialog.run() == Gtk.ResponseType.YES
    dialog.destroy()
    return result


# ------------------------------------------------------------------ copy / move

class Cancelled(Exception):
    pass


class FileOperation:
    """Copy or move ``sources`` (Gio.File) into ``destination`` directory."""

    def __init__(self, sources, destination, move=False, parent=None, on_done=None):
        self.sources = sources
        self.destination = destination
        self.move = move
        self.parent = parent
        self.on_done = on_done
        self.cancellable = Gio.Cancellable()
        self.total_bytes = 0
        self.done_bytes = 0
        self.current = ""
        self.policy = None          # None = ask, "replace", "skip"
        self.dialog = None
        self._answer = None
        self._answer_event = threading.Event()
        self.errors = []

    def start(self):
        self.dialog = ProgressDialog(self)
        GLib.timeout_add(500, self._show_dialog)
        threading.Thread(target=self._run, daemon=True).start()

    def _show_dialog(self):
        if self.dialog is not None and not self.cancellable.is_cancelled():
            self.dialog.show_all()
        return GLib.SOURCE_REMOVE

    # -- worker thread ---------------------------------------------------

    def _run(self):
        try:
            for src in self.sources:
                self.total_bytes += self._size(src)
            dest_dir = Gio.File.new_for_path(self.destination)
            for src in self.sources:
                if self.cancellable.is_cancelled():
                    raise Cancelled()
                target = dest_dir.get_child(src.get_basename())
                if src.equal(target):
                    if self.move:
                        continue
                    target = dest_dir.get_child(unique_name(self.destination, src.get_basename()))
                elif target.has_prefix(src):
                    self.errors.append(_("The destination folder is a subfolder of the source folder."))
                    continue
                self._transfer(src, target)
        except Cancelled:
            pass
        except GLib.Error as exc:
            self.errors.append(exc.message)
        GLib.idle_add(self._finish)

    def _size(self, gfile):
        try:
            info = gfile.query_info("standard::type,standard::size", Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
                                    None)
        except GLib.Error:
            return 0
        if info.get_file_type() == Gio.FileType.DIRECTORY:
            total = 0
            try:
                for child in gfile.enumerate_children("standard::name", Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
                                                      None):
                    total += self._size(gfile.get_child(child.get_name()))
            except GLib.Error:
                pass
            return total
        return info.get_size()

    def _transfer(self, src, target):
        if self.cancellable.is_cancelled():
            raise Cancelled()
        info = src.query_info("standard::type,standard::size", Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, None)
        is_dir = info.get_file_type() == Gio.FileType.DIRECTORY
        self.current = src.get_basename()
        if self.move:
            self._move(src, target, is_dir, info.get_size())
            return
        self._copy(src, target, is_dir, info.get_size())

    def _move(self, src, target, is_dir, size):
        """Move one item. Skipped conflicts leave the source untouched."""
        if self.cancellable.is_cancelled():
            raise Cancelled()
        self.current = src.get_basename()
        flags = Gio.FileCopyFlags.NOFOLLOW_SYMLINKS | Gio.FileCopyFlags.ALL_METADATA
        if is_dir:
            flags |= Gio.FileCopyFlags.NO_FALLBACK_FOR_MOVE
        try:
            src.move(target, flags, self.cancellable, None, None)
            self.done_bytes += self._size(target) if is_dir else size
            return
        except GLib.Error as exc:
            quark = Gio.io_error_quark()
            merge = (exc.matches(quark, Gio.IOErrorEnum.WOULD_MERGE) or
                     exc.matches(quark, Gio.IOErrorEnum.WOULD_RECURSE) or
                     exc.matches(quark, Gio.IOErrorEnum.NOT_SUPPORTED) or
                     (exc.matches(quark, Gio.IOErrorEnum.EXISTS) and is_dir))
            if not is_dir and exc.matches(quark, Gio.IOErrorEnum.EXISTS):
                if self._resolve_conflict(src, target, False):
                    src.move(target, flags | Gio.FileCopyFlags.OVERWRITE, self.cancellable, None, None)
                self.done_bytes += size
                return
            if not (is_dir and merge):
                raise
        # Directory onto an existing directory or across file systems:
        # move the children one by one and remove the source if it is empty.
        if not target.query_exists(None):
            target.make_directory(self.cancellable)
        for child in src.enumerate_children("standard::name,standard::type,standard::size",
                                            Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, self.cancellable):
            self._move(src.get_child(child.get_name()), target.get_child(child.get_name()),
                       child.get_file_type() == Gio.FileType.DIRECTORY, child.get_size())
        try:
            src.delete(None)  # only succeeds when nothing was skipped
        except GLib.Error:
            pass

    def _copy(self, src, target, is_dir, size):
        if is_dir:
            if not target.query_exists(None):
                target.make_directory(self.cancellable)
            elif not self._resolve_conflict(src, target, True):
                return
            for child in src.enumerate_children("standard::name", Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
                                                self.cancellable):
                self._copy_child(src.get_child(child.get_name()), target.get_child(child.get_name()))
            return
        flags = Gio.FileCopyFlags.NOFOLLOW_SYMLINKS | Gio.FileCopyFlags.ALL_METADATA
        if target.query_exists(None):
            if not self._resolve_conflict(src, target, False):
                self.done_bytes += size
                return
            flags |= Gio.FileCopyFlags.OVERWRITE
        start = self.done_bytes

        def progress(current, _total, *_args):
            self.done_bytes = start + current

        src.copy(target, flags, self.cancellable, progress, None)
        self.done_bytes = start + size

    def _copy_child(self, src, target):
        info = src.query_info("standard::type,standard::size", Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, None)
        self.current = src.get_basename()
        self._copy(src, target, info.get_file_type() == Gio.FileType.DIRECTORY, info.get_size())

    def _resolve_conflict(self, src, target, is_dir):
        """True to replace/merge, False to skip."""
        if is_dir:
            return True  # folders are merged, like Windows does after asking once
        if self.policy:
            return self.policy == "replace"
        self._answer_event.clear()
        GLib.idle_add(self._ask, src.get_basename())
        self._answer_event.wait()
        answer, remember = self._answer
        if answer == "cancel":
            self.cancellable.cancel()
            raise Cancelled()
        if remember:
            self.policy = answer
        return answer == "replace"

    # -- main thread ------------------------------------------------------

    def _ask(self, name):
        dialog = Gtk.Dialog(title=_("Replace or Skip Files"), transient_for=self.dialog or self.parent, modal=True)
        add_class(dialog, "tw-app-window")
        box = dialog.get_content_area()
        box.set_spacing(10)
        box.set_margin_start(20)
        box.set_margin_end(20)
        box.set_margin_top(16)
        head = Gtk.Label(xalign=0)
        head.set_markup("<big>%s</big>" % GLib.markup_escape_text(
            _("The destination already has a file named \"%s\"") % name))
        head.set_line_wrap(True)
        box.pack_start(head, False, False, 0)
        remember = Gtk.CheckButton(label=_("Do this for all conflicts"))
        box.pack_start(remember, False, False, 0)
        dialog.add_button(_("Skip this file"), 1)
        dialog.add_button(_("Replace the file in the destination"), 2)
        dialog.add_button(_("Cancel"), 3)
        dialog.show_all()
        response = dialog.run()
        choice = {1: "skip", 2: "replace"}.get(response, "cancel")
        self._answer = (choice, remember.get_active())
        dialog.destroy()
        self._answer_event.set()
        return GLib.SOURCE_REMOVE

    def _finish(self):
        if self.dialog is not None:
            self.dialog.destroy()
            self.dialog = None
        if self.errors:
            dialog = Gtk.MessageDialog(transient_for=self.parent, modal=True,
                                       message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK,
                                       text=_("Some items could not be copied."))
            dialog.format_secondary_text("\n".join(self.errors[:5]))
            dialog.run()
            dialog.destroy()
        if self.on_done:
            self.on_done()
        return GLib.SOURCE_REMOVE


class ProgressDialog(Gtk.Window):
    def __init__(self, op):
        super().__init__(title=_("Moving") if op.move else _("Copying"))
        add_class(self, "tw-app-window")
        self.op = op
        self.set_default_size(460, -1)
        self.set_resizable(False)
        if op.parent is not None:
            self.set_transient_for(op.parent)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(20)
        box.set_margin_end(20)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        count = len(op.sources)
        verb = ngettext("Moving %d item to", "Moving %d items to", count) if op.move else \
            ngettext("Copying %d item to", "Copying %d items to", count)
        title = Gtk.Label(label="%s %s" % (verb % count, os.path.basename(op.destination) or op.destination),
                          xalign=0)
        title.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        box.pack_start(title, False, False, 0)
        self.percent = Gtk.Label(xalign=0)
        self.percent.set_markup("<big>0 %</big>")
        box.pack_start(self.percent, False, False, 0)
        self.bar = Gtk.ProgressBar()
        box.pack_start(self.bar, False, False, 0)
        self.detail = add_class(Gtk.Label(xalign=0), "tw-dim")
        self.detail.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        box.pack_start(self.detail, False, False, 0)
        buttons = Gtk.Box()
        cancel = Gtk.Button(label=_("Cancel"))
        cancel.connect("clicked", lambda *_: op.cancellable.cancel())
        buttons.pack_end(cancel, False, False, 0)
        box.pack_start(buttons, False, False, 4)
        self.add(box)
        self.connect("delete-event", lambda *_: op.cancellable.cancel() or True)
        GLib.timeout_add(200, self._update)

    def _update(self):
        op = self.op
        if self.op.dialog is not self:
            return GLib.SOURCE_REMOVE
        fraction = (op.done_bytes / op.total_bytes) if op.total_bytes else 0.0
        fraction = max(0.0, min(1.0, fraction))
        self.bar.set_fraction(fraction)
        self.percent.set_markup("<big>%d %%</big>" % round(fraction * 100))
        self.detail.set_text("%s: %s   (%s / %s)" % (_("Name"), op.current, human_size(op.done_bytes),
                                                     human_size(op.total_bytes)))
        return GLib.SOURCE_CONTINUE


def paste_into(directory, parent=None, on_done=None):
    """Paste clipboard files into ``directory``."""
    def got(uris, cut):
        sources = [Gio.File.new_for_uri(u) for u in uris if u]
        if not sources:
            return
        FileOperation(sources, directory, move=cut, parent=parent, on_done=on_done).start()
        if cut:
            _clip_store["uris"] = []
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).clear()

    clipboard_get(got)
