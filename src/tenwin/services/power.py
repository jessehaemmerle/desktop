"""Battery (UPower) and power profiles (power-profiles-daemon)."""

import logging

from gi.repository import Gio, GLib, GObject

log = logging.getLogger(__name__)

STATE_CHARGING = 1
STATE_DISCHARGING = 2
STATE_FULL = 4
STATE_PENDING_CHARGE = 5


def _proxy(bus_name, path, iface):
    try:
        return Gio.DBusProxy.new_for_bus_sync(Gio.BusType.SYSTEM, Gio.DBusProxyFlags.NONE, None,
                                              bus_name, path, iface, None)
    except GLib.Error as exc:
        log.info("%s unavailable: %s", bus_name, exc)
        return None


class Power(GObject.Object):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        super().__init__()
        self.battery = _proxy("org.freedesktop.UPower", "/org/freedesktop/UPower/devices/DisplayDevice",
                              "org.freedesktop.UPower.Device")
        if self.battery is not None:
            self.battery.connect("g-properties-changed", lambda *_: self.emit("changed"))
        self.profiles = _proxy("org.freedesktop.UPower.PowerProfiles", "/org/freedesktop/UPower/PowerProfiles",
                               "org.freedesktop.UPower.PowerProfiles")
        if self.profiles is not None and self.profiles.get_name_owner() is None:
            self.profiles = None
        if self.profiles is None:
            self.profiles = _proxy("net.hadess.PowerProfiles", "/net/hadess/PowerProfiles",
                                   "net.hadess.PowerProfiles")
            if self.profiles is not None and self.profiles.get_name_owner() is None:
                self.profiles = None
        if self.profiles is not None:
            self.profiles.connect("g-properties-changed", lambda *_: self.emit("changed"))

    def _prop(self, name, default=None):
        if self.battery is None:
            return default
        value = self.battery.get_cached_property(name)
        return value.unpack() if value is not None else default

    @property
    def has_battery(self):
        # Type 2 = battery
        return bool(self._prop("IsPresent", False)) and self._prop("Type", 0) == 2

    @property
    def percent(self):
        return int(round(self._prop("Percentage", 0.0)))

    @property
    def state(self):
        return self._prop("State", 0)

    @property
    def charging(self):
        return self.state in (STATE_CHARGING, STATE_FULL, STATE_PENDING_CHARGE)

    @property
    def time_to_empty(self):
        return int(self._prop("TimeToEmpty", 0))

    @property
    def time_to_full(self):
        return int(self._prop("TimeToFull", 0))

    def icon_name(self):
        level = max(0, min(100, int(round(self.percent / 10.0)) * 10))
        return "tenwin-battery-%d%s" % (level, "-charging" if self.charging else "")

    # -- profiles ------------------------------------------------------------

    @property
    def profile(self):
        if self.profiles is None:
            return None
        value = self.profiles.get_cached_property("ActiveProfile")
        return value.unpack() if value else None

    def available_profiles(self):
        if self.profiles is None:
            return []
        value = self.profiles.get_cached_property("Profiles")
        if value is None:
            return []
        return [p.get("Profile") for p in value.unpack()]

    def set_profile(self, name):
        if self.profiles is None:
            return
        try:
            self.profiles.call_sync("org.freedesktop.DBus.Properties.Set",
                                    GLib.Variant("(ssv)", (self.profiles.get_interface_name(), "ActiveProfile",
                                                           GLib.Variant("s", name))),
                                    Gio.DBusCallFlags.NONE, -1, None)
        except GLib.Error as exc:
            log.warning("cannot set power profile: %s", exc)
