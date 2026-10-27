"""Volume/brightness overlay in the top-left corner (Windows 10 style)."""

from gi.repository import GLib, Gtk

from tenwin.gtkutil import add_class, icon_image, set_icon
from tenwin.shell.layer import Edge, Layer, LayerWindow


class OSD(LayerWindow):
    def __init__(self, shell):
        super().__init__("tenwin-osd", layer=Layer.OVERLAY, anchors=(Edge.TOP, Edge.LEFT), css="tw-surface tw-popup")
        self.shell = shell
        self.set_margins(top=58, left=56)
        box = add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10), "tw-osd")
        self.value = Gtk.Label()
        box.pack_start(self.value, False, False, 0)
        self.bar = Gtk.LevelBar(orientation=Gtk.Orientation.VERTICAL)
        self.bar.set_inverted(True)
        self.bar.set_min_value(0)
        self.bar.set_max_value(100)
        self.bar.set_halign(Gtk.Align.CENTER)
        box.pack_start(self.bar, False, False, 0)
        self.icon = icon_image("tenwin-volume-high", 16, symbolic=True)
        box.pack_start(self.icon, False, False, 0)
        self.add(box)
        self._hide_id = 0

    def show_level(self, icon_name, percent):
        percent = max(0, min(100, int(percent)))
        self.value.set_text(str(percent))
        self.bar.set_value(percent)
        set_icon(self.icon, icon_name, 16, symbolic=True)
        if self.shell.current_monitor is not None:
            self.set_monitor(self.shell.current_monitor)
        self.show_all()
        if self._hide_id:
            GLib.source_remove(self._hide_id)
        self._hide_id = GLib.timeout_add(1600, self._hide)

    def _hide(self):
        self._hide_id = 0
        self.hide()
        return GLib.SOURCE_REMOVE
