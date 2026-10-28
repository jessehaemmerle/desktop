"""Ease of Access in the shell: Magnifier (Win+Plus/Minus) and Narrator (Ctrl+Win+Enter).

labwc 0.7 cannot zoom the screen, so the magnifier shows an enlarged still
image of the screen that follows the mouse; Win+Plus takes a fresh picture.
With labwc 0.8 or newer the session binds labwc's own live magnifier instead.
"""

import logging
import os
import shutil
import tempfile

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk

from tenwin.config import get_settings
from tenwin.i18n import _
from tenwin.shell.layer import Edge, Layer, LayerWindow

log = logging.getLogger(__name__)

ALL_EDGES = (Edge.TOP, Edge.BOTTOM, Edge.LEFT, Edge.RIGHT)
STEP = 100     # percent per Win+Plus, as on Windows
MAX_ZOOM = 1600


def source_offset(pointer, size, zoom):
    """Left/top of the visible source area so the point under the pointer stays put."""
    return max(0.0, min(size - size / zoom, pointer * (1 - 1 / zoom)))


class Magnifier(LayerWindow):
    def __init__(self, shell):
        # exclusive=-1: cover the taskbar too, so the picture matches the screen.
        super().__init__("tenwin-magnifier", layer=Layer.OVERLAY, anchors=ALL_EDGES, keyboard="exclusive",
                         exclusive=-1)
        self.shell = shell
        self.settings = get_settings()
        self.zoom = 1.0
        self.pixbuf = None
        self.pointer = (0, 0)
        self.area = Gtk.DrawingArea()
        self.area.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_PRESS_MASK |
                             Gdk.EventMask.SCROLL_MASK)
        self.area.connect("draw", self._draw)
        self.area.connect("motion-notify-event", self._motion)
        self.area.connect("button-press-event", lambda *_: self.stop() or True)
        self.area.connect("scroll-event", self._scroll)
        self.add(self.area)
        self.connect("key-press-event", self._key)

    def zoom_in(self):
        if not self.get_visible():
            self.zoom = 1.0
            self._capture(lambda: self._set_zoom(max(2.0, self.settings["ease.magnifier_zoom"] / 100.0)))
        else:
            self._set_zoom(self.zoom + STEP / 100.0)

    def zoom_out(self):
        if self.get_visible():
            self._set_zoom(self.zoom - STEP / 100.0)

    def stop(self):
        self.hide()
        self.pixbuf = None

    def _set_zoom(self, zoom):
        self.zoom = max(1.0, min(MAX_ZOOM / 100.0, zoom))
        if self.zoom <= 1.0:
            self.stop()
            return
        if not self.get_visible():
            if self.shell.current_monitor is not None:
                self.set_monitor(self.shell.current_monitor)
            self.show_all()
        self.area.queue_draw()

    def _capture(self, then):
        """Screenshot of the current output with grim, then ``then()``."""
        if not shutil.which("grim"):
            log.warning("the magnifier needs grim")
            return
        fd, path = tempfile.mkstemp(prefix="tenwin-magnifier-", suffix=".png")
        os.close(fd)
        argv = ["grim"]
        monitor = self.shell.current_monitor
        output = self.shell.wm.output_name(monitor) if monitor is not None else None
        if output:
            argv += ["-o", output]
        try:
            proc = Gio.Subprocess.new(argv + [path], Gio.SubprocessFlags.NONE)
        except GLib.Error as exc:
            log.warning("magnifier: %s", exc)
            return

        def done(proc, result):
            try:
                proc.wait_check_finish(result)
                self.pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
            except GLib.Error as exc:
                log.warning("magnifier: %s", exc)
                self.pixbuf = None
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
            if self.pixbuf is not None:
                if monitor is not None:
                    geo = monitor.get_geometry()
                    self.pointer = (geo.width / 2, geo.height / 2)
                then()

        proc.wait_async(None, done)

    def _draw(self, _widget, cr):
        if self.pixbuf is None:
            return False
        width, height = self.area.get_allocated_width(), self.area.get_allocated_height()
        scale_x = self.pixbuf.get_width() / max(1, width)   # screenshot pixels per logical pixel
        zoom = self.zoom
        left = source_offset(self.pointer[0], width, zoom)
        top = source_offset(self.pointer[1], height, zoom)
        cr.scale(zoom / scale_x, zoom / scale_x)
        Gdk.cairo_set_source_pixbuf(cr, self.pixbuf, -left * scale_x, -top * scale_x)
        cr.paint()
        return False

    def _motion(self, _widget, event):
        self.pointer = (event.x, event.y)
        self.area.queue_draw()
        return False

    def _scroll(self, _widget, event):
        if event.state & Gdk.ModifierType.CONTROL_MASK:
            if event.direction == Gdk.ScrollDirection.UP:
                self.zoom_in()
            elif event.direction == Gdk.ScrollDirection.DOWN:
                self.zoom_out()
            return True
        return False

    def _key(self, _widget, event):
        if event.keyval in (Gdk.KEY_Escape,):
            self.stop()
        elif event.keyval in (Gdk.KEY_plus, Gdk.KEY_KP_Add, Gdk.KEY_equal):
            self.zoom_in()
        elif event.keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            self.zoom_out()
        return True


class Narrator:
    """Starts and stops the Orca screen reader."""

    def __init__(self, shell):
        self.shell = shell
        self.settings = get_settings()
        self._proc = None
        self.settings.connect("changed", self._on_settings)
        if self.settings["ease.narrator"]:
            self.start()

    @staticmethod
    def available():
        return shutil.which("orca") is not None

    def toggle(self):
        self.settings.set("ease.narrator", not self.settings["ease.narrator"])

    def _on_settings(self, _settings, keys):
        if "ease.narrator" in keys:
            (self.start if self.settings["ease.narrator"] else self.stop)()

    def start(self):
        if self._proc is not None:
            return
        if not self.available():
            self.shell.notifications.notify(_("Narrator"), 0, "tenwin-narrator", _("Narrator isn't installed"),
                                            _("Install the \"orca\" package to use the screen reader."), [],
                                            {"transient": True}, 6000)
            return
        try:
            self._proc = Gio.Subprocess.new(["orca", "--replace"], Gio.SubprocessFlags.NONE)
        except GLib.Error as exc:
            log.warning("cannot start orca: %s", exc)
            return
        self._proc.wait_async(None, self._ended)

    def stop(self):
        if self._proc is not None:
            self._proc.send_signal(15)

    def _ended(self, proc, result):
        try:
            proc.wait_finish(result)
        except GLib.Error:
            pass
        self._proc = None
