"""Network locations (SMB & co. via GVfs) and ISO images (via udisks)."""

import logging
import re
import shutil
from urllib.parse import quote

from gi.repository import Gio, GLib, Gtk

from tenwin.config import get_settings
from tenwin.i18n import _

log = logging.getLogger(__name__)

REMOTE_SCHEMES = ("smb", "sftp", "ftp", "ftps", "dav", "davs", "afp", "nfs", "ssh")
DISC_IMAGES = (".iso", ".img")


def unc_to_uri(text):
    r"""``\\server\share\dir`` (Windows notation) or a URI -> a GVfs URI."""
    text = text.strip()
    if text.startswith("\\\\") or text.startswith("//"):
        parts = [p for p in re.split(r"[\\/]+", text) if p]
        return "smb://" + "/".join(quote(p) for p in parts)
    if "://" not in text and text:
        return "smb://" + quote(text.strip("/"), safe="/")
    return text


def is_remote(uri):
    return uri.split(":", 1)[0].lower() in REMOTE_SCHEMES


def ensure_mounted(gfile, parent, callback):
    """Mount the volume that holds ``gfile`` if needed; ``callback(error or None)``."""
    try:
        gfile.find_enclosing_mount(None)
        callback(None)
        return
    except GLib.Error as exc:
        if not exc.matches(Gio.io_error_quark(), Gio.IOErrorEnum.NOT_MOUNTED):
            callback(None)  # let the folder model report anything else
            return
    operation = Gtk.MountOperation(parent=parent)

    def done(source, result, _data):
        try:
            source.mount_enclosing_volume_finish(result)
            callback(None)
        except GLib.Error as exc:
            if exc.matches(Gio.io_error_quark(), Gio.IOErrorEnum.ALREADY_MOUNTED):
                callback(None)
            else:
                callback(exc.message)

    gfile.mount_enclosing_volume(Gio.MountMountFlags.NONE, operation, None, done, None)


def saved_drives():
    return [d for d in get_settings()["explorer.network_drives"]
            if isinstance(d, dict) and d.get("uri")]


def save_drive(name, uri):
    drives = [d for d in saved_drives() if d["uri"] != uri]
    drives.append({"name": name, "uri": uri})
    get_settings().set("explorer.network_drives", drives)


def remove_drive(uri):
    get_settings().set("explorer.network_drives", [d for d in saved_drives() if d["uri"] != uri])


def map_drive_dialog(parent):
    """"Map network drive": returns (name, uri) or None."""
    dialog = Gtk.Dialog(title=_("Map Network Drive"), transient_for=parent, modal=True)
    dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
    dialog.add_button(_("Finish"), Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.OK)
    area = dialog.get_content_area()
    area.set_spacing(8)
    for side in ("start", "end", "top", "bottom"):
        getattr(area, "set_margin_" + side)(16)
    area.pack_start(Gtk.Label(label=_("What network folder would you like to map?"), xalign=0),
                    False, False, 0)
    grid = Gtk.Grid(column_spacing=8, row_spacing=8)
    grid.attach(Gtk.Label(label=_("Folder:"), xalign=0), 0, 0, 1, 1)
    folder = Gtk.Entry(activates_default=True, width_chars=36, placeholder_text="\\\\server\\share")
    grid.attach(folder, 1, 0, 1, 1)
    grid.attach(Gtk.Label(label=_("Name:"), xalign=0), 0, 1, 1, 1)
    name = Gtk.Entry(activates_default=True)
    grid.attach(name, 1, 1, 1, 1)
    area.pack_start(grid, False, False, 0)
    hint = Gtk.Label(label=_("Example: \\\\server\\share, smb://server/share or sftp://user@host/path"),
                     xalign=0)
    hint.get_style_context().add_class("dim-label")
    area.pack_start(hint, False, False, 0)
    dialog.show_all()
    result = None
    while dialog.run() == Gtk.ResponseType.OK:
        uri = unc_to_uri(folder.get_text())
        if uri:
            label = name.get_text().strip() or Gio.File.new_for_uri(uri).get_parse_name()
            result = (label, uri)
            break
    dialog.destroy()
    return result


# -- disc images ------------------------------------------------------------------

def is_disc_image(path):
    return bool(path) and path.lower().endswith(DISC_IMAGES)


def can_mount_images():
    return shutil.which("udisksctl") is not None


def mount_image(path, callback):
    """Attach a disc image read-only and mount it; ``callback(mount_path, error)``."""

    def run(argv, then):
        try:
            proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)
        except GLib.Error as exc:
            callback(None, exc.message)
            return

        def finished(proc, result):
            try:
                _ok, out, _err = proc.communicate_utf8_finish(result)
            except GLib.Error as exc:
                callback(None, exc.message)
                return
            if proc.get_exit_status() != 0:
                callback(None, (out or "").strip() or _("The disc image could not be mounted."))
                return
            then(out or "")

        proc.communicate_utf8_async(None, None, finished)

    def attached(out):
        match = re.search(r"(/dev/loop\d+)", out)
        if not match:
            callback(None, out.strip())
            return
        run(["udisksctl", "mount", "--no-user-interaction", "-b", match.group(1)], mounted)

    def mounted(out):
        match = re.search(r" at (/.+?)\.?$", out.strip())
        callback(match.group(1) if match else None, None if match else out.strip())

    run(["udisksctl", "loop-setup", "--no-user-interaction", "-r", "-f", path], attached)


def burn_tool():
    for name in ("brasero", "xfburn", "k3b"):
        if shutil.which(name):
            return name
    return None
