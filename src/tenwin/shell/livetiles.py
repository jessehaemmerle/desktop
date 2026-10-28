"""Live tile contents for the Start menu (offline sources only)."""

import os
import random

from gi.repository import GdkPixbuf, GLib, Gtk, Pango

from tenwin.gtkutil import add_class

CALENDAR_APPS = {"org.gnome.Calendar.desktop", "gnome-calendar.desktop"}
PHOTO_APPS = {"org.gnome.Loupe.desktop", "org.gnome.eog.desktop", "eog.desktop",
              "org.gnome.Shotwell.desktop", "shotwell.desktop", "org.gnome.Photos.desktop"}
FILE_APPS = {"org.tenwin.Explorer.desktop"}
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff")
MAX_PICTURES = 300


def pictures_dir():
    return GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) or os.path.expanduser("~/Pictures")


def find_pictures(directory=None, limit=MAX_PICTURES):
    """Image files in the Pictures folder and its direct subfolders."""
    directory = directory or pictures_dir()
    found = []
    try:
        entries = sorted(os.scandir(directory), key=lambda e: e.name)
    except OSError:
        return found
    subdirs = []
    for entry in entries:
        if entry.name.startswith("."):
            continue
        if entry.is_dir(follow_symlinks=False):
            subdirs.append(entry.path)
        elif entry.name.lower().endswith(IMAGE_EXTENSIONS):
            found.append(entry.path)
    for sub in subdirs:
        if len(found) >= limit:
            break
        try:
            found += [e.path for e in os.scandir(sub)
                      if not e.name.startswith(".") and e.name.lower().endswith(IMAGE_EXTENSIONS)]
        except OSError:
            pass
    return found[:limit]


def cover_pixbuf(path, width, height):
    """The picture scaled to cover width×height and cropped in the centre."""
    info = GdkPixbuf.Pixbuf.get_file_info(path)
    if not info or info[0] is None:
        return None
    src_w, src_h = info[1], info[2]
    if src_w <= 0 or src_h <= 0:
        return None
    scale = max(width / src_w, height / src_h)
    w, h = max(width, int(src_w * scale + 0.5)), max(height, int(src_h * scale + 0.5))
    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, w, h, False)
    x, y = (pixbuf.get_width() - width) // 2, (pixbuf.get_height() - height) // 2
    return pixbuf.new_subpixbuf(max(0, x), max(0, y), min(width, pixbuf.get_width()),
                                min(height, pixbuf.get_height()))


def kind_for(tile, info):
    """Which live content a tile shows: "calendar", "photos", "recent" or None."""
    if tile.get("live") is False:
        return None
    if info is not None:
        app_id = info.get_id()
        if app_id in CALENDAR_APPS:
            return "calendar"
        if app_id in PHOTO_APPS:
            return "photos"
        if app_id in FILE_APPS and tile.get("size") in ("wide", "large"):
            return "recent"
    elif tile.get("path") and os.path.realpath(tile["path"]) == os.path.realpath(pictures_dir()):
        return "photos"
    return None


class PhotoTile(Gtk.Image):
    """Slide show of the user's pictures; ``advance`` is called by the Start menu."""

    def __init__(self, width, height, pictures):
        super().__init__()
        self.width, self.height = width, height
        self.pictures = pictures
        self.advance()

    def advance(self):
        for _attempt in range(3):
            if not self.pictures:
                return False
            path = random.choice(self.pictures)
            try:
                pixbuf = cover_pixbuf(path, self.width, self.height)
            except GLib.Error:
                pixbuf = None
            if pixbuf is not None:
                self.set_from_pixbuf(pixbuf)
                return True
        return False


def calendar_widget():
    now = GLib.DateTime.new_now_local()
    center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    center.set_valign(Gtk.Align.CENTER)
    center.pack_start(Gtk.Label(label=now.format("%A")), False, False, 0)
    center.pack_start(add_class(Gtk.Label(label=str(now.get_day_of_month())), "tw-tile-big"), False, False, 0)
    return center


def recent_widget(limit=3):
    """Names of recently used files (for the File Explorer tile)."""
    items = sorted(Gtk.RecentManager.get_default().get_items(),
                   key=lambda i: i.get_modified(), reverse=True)[:limit]
    if not items:
        return None
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    box.set_valign(Gtk.Align.START)
    box.set_margin_top(8)
    box.set_margin_start(8)
    box.set_margin_end(8)
    for item in items:
        label = add_class(Gtk.Label(label=item.get_display_name(), xalign=0), "tw-tile-line")
        label.set_ellipsize(Pango.EllipsizeMode.END)
        box.pack_start(label, False, False, 0)
    return box
