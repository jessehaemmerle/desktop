"""Bluetooth adapter power via BlueZ."""

import logging

from gi.repository import Gio, GLib, GObject

log = logging.getLogger(__name__)


class Bluetooth(GObject.Object):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        super().__init__()
        self.adapter = None
        try:
            self.manager = Gio.DBusObjectManagerClient.new_for_bus_sync(
                Gio.BusType.SYSTEM, Gio.DBusObjectManagerClientFlags.NONE, "org.bluez", "/",
                None, None, None)
        except GLib.Error as exc:
            log.info("BlueZ unavailable: %s", exc)
            self.manager = None
            return
        self.manager.connect("object-added", lambda *_: self._find())
        self.manager.connect("object-removed", lambda *_: self._find())
        self.manager.connect("interface-proxy-properties-changed", lambda *_: self.emit("changed"))
        self._find()

    def _find(self):
        self.adapter = None
        if self.manager is None:
            return
        for obj in self.manager.get_objects():
            iface = obj.get_interface("org.bluez.Adapter1")
            if iface is not None:
                self.adapter = iface
                break
        self.emit("changed")

    @property
    def available(self):
        return self.adapter is not None

    @property
    def powered(self):
        if self.adapter is None:
            return False
        value = self.adapter.get_cached_property("Powered")
        return bool(value.unpack()) if value is not None else False

    def set_powered(self, on):
        if self.adapter is None:
            return
        self.adapter.call("org.freedesktop.DBus.Properties.Set",
                          GLib.Variant("(ssv)", ("org.bluez.Adapter1", "Powered", GLib.Variant("b", on))),
                          Gio.DBusCallFlags.NONE, -1, None, None)
