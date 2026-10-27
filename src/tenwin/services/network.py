"""Network state and Wi-Fi via NetworkManager (libnm)."""

import logging

from gi.repository import GLib, GObject

log = logging.getLogger(__name__)

try:
    import gi
    gi.require_version("NM", "1.0")
    from gi.repository import NM
except (ImportError, ValueError):  # libnm typelib missing
    NM = None


class AccessPoint:
    def __init__(self, ssid, strength, secure, ap, active):
        self.ssid = ssid
        self.strength = strength
        self.secure = secure
        self.ap = ap
        self.active = active


def strength_icon(strength):
    if strength >= 75:
        return "tenwin-wifi-3"
    if strength >= 50:
        return "tenwin-wifi-2"
    if strength >= 25:
        return "tenwin-wifi-1"
    return "tenwin-wifi-0"


class Network(GObject.Object):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        super().__init__()
        self.client = None
        self._queued = 0
        if NM is None:
            return
        NM.Client.new_async(None, self._on_client)

    def _on_client(self, _src, result):
        try:
            self.client = NM.Client.new_finish(result)
        except GLib.Error as exc:
            log.warning("NetworkManager unavailable: %s", exc)
            return
        for signal in ("notify::state", "notify::primary-connection", "notify::wireless-enabled",
                       "device-added", "device-removed", "notify::networking-enabled",
                       "notify::active-connections"):
            self.client.connect(signal, self._queue)
        for device in self.client.get_devices():
            self._watch_device(device)
        self.client.connect("device-added", lambda _c, d: self._watch_device(d))
        self.emit("changed")

    def _watch_device(self, device):
        device.connect("state-changed", self._queue)
        if NM and isinstance(device, NM.DeviceWifi):
            device.connect("access-point-added", self._queue)
            device.connect("access-point-removed", self._queue)
            device.connect("notify::active-access-point", self._queue)

    def _queue(self, *_args):
        if self._queued:
            return
        def fire():
            self._queued = 0
            self.emit("changed")
            return GLib.SOURCE_REMOVE
        self._queued = GLib.timeout_add(150, fire)

    # -- state ----------------------------------------------------------

    @property
    def available(self):
        return self.client is not None and self.client.get_nm_running()

    def wifi_devices(self):
        if not self.available:
            return []
        return [d for d in self.client.get_devices() if isinstance(d, NM.DeviceWifi)]

    @property
    def has_wifi(self):
        return bool(self.wifi_devices())

    @property
    def wifi_enabled(self):
        return self.available and self.client.wireless_get_enabled()

    @property
    def airplane_mode(self):
        return self.available and not self.client.wireless_get_enabled() and self.has_wifi

    def primary(self):
        """(kind, name, strength) of the primary connection; kind is wifi|wired|none."""
        if not self.available:
            return ("none", "", 0)
        active = self.client.get_primary_connection()
        if active is None:
            return ("none", "", 0)
        ctype = active.get_connection_type() or ""
        if ctype == "802-11-wireless":
            strength = 0
            for device in active.get_devices():
                if isinstance(device, NM.DeviceWifi) and device.get_active_access_point():
                    strength = device.get_active_access_point().get_strength()
            return ("wifi", active.get_id(), strength)
        if ctype in ("802-3-ethernet", "pppoe"):
            return ("wired", active.get_id(), 100)
        return ("other", active.get_id(), 100)

    @property
    def connected(self):
        return self.primary()[0] != "none"

    def icon_name(self):
        kind, _name, strength = self.primary()
        if kind == "wifi":
            return strength_icon(strength)
        if kind in ("wired", "other"):
            return "tenwin-network-wired"
        if self.airplane_mode:
            return "tenwin-airplane"
        return "tenwin-network-offline"

    def access_points(self):
        result = {}
        for device in self.wifi_devices():
            active = device.get_active_access_point()
            for ap in device.get_access_points():
                ssid_bytes = ap.get_ssid()
                if ssid_bytes is None:
                    continue
                ssid = NM.utils_ssid_to_utf8(ssid_bytes.get_data())
                if not ssid:
                    continue
                secure = bool(ap.get_wpa_flags() or ap.get_rsn_flags() or
                              ap.get_flags() & getattr(NM, "80211ApFlags").PRIVACY)
                is_active = active is not None and active.get_bssid() == ap.get_bssid()
                previous = result.get(ssid)
                if previous is None or is_active or (not previous.active and ap.get_strength() > previous.strength):
                    result[ssid] = AccessPoint(ssid, ap.get_strength(), secure, (device, ap), is_active)
        return sorted(result.values(), key=lambda a: (not a.active, -a.strength, a.ssid.casefold()))

    # -- actions -------------------------------------------------------------

    def set_wifi_enabled(self, enabled):
        if self.available:
            self.client.dbus_set_property(NM.DBUS_PATH, NM.DBUS_INTERFACE, "WirelessEnabled",
                                          GLib.Variant("b", enabled), -1, None, None)

    def set_airplane_mode(self, enabled):
        self.set_wifi_enabled(not enabled)

    def request_scan(self):
        for device in self.wifi_devices():
            try:
                device.request_scan_async(None, None)
            except Exception:
                pass

    def _existing_connection(self, ssid):
        for conn in self.client.get_connections():
            setting = conn.get_setting_wireless()
            if setting is None or setting.get_ssid() is None:
                continue
            if NM.utils_ssid_to_utf8(setting.get_ssid().get_data()) == ssid:
                return conn
        return None

    def connect_ap(self, entry, password=None, callback=None):
        """Connect to an AccessPoint; callback(ok, message)."""
        device, ap = entry.ap
        existing = self._existing_connection(entry.ssid)

        def finish(client, res, activating_new):
            try:
                if activating_new:
                    client.add_and_activate_connection_finish(res)
                else:
                    client.activate_connection_finish(res)
                ok, msg = True, ""
            except GLib.Error as exc:
                ok, msg = False, exc.message
            if callback:
                callback(ok, msg)

        if existing is not None and not password:
            self.client.activate_connection_async(existing, device, ap.get_path(), None,
                                                  lambda c, r: finish(c, r, False))
            return
        connection = NM.SimpleConnection.new()
        if entry.secure and password:
            security = NM.SettingWirelessSecurity.new()
            security.set_property(NM.SETTING_WIRELESS_SECURITY_KEY_MGMT, "wpa-psk")
            security.set_property(NM.SETTING_WIRELESS_SECURITY_PSK, password)
            connection.add_setting(security)
        self.client.add_and_activate_connection_async(connection, device, ap.get_path(), None,
                                                      lambda c, r: finish(c, r, True))

    def disconnect_wifi(self):
        for device in self.wifi_devices():
            if device.get_active_connection() is not None:
                device.disconnect_async(None, None)

    def known(self, ssid):
        return self.available and self._existing_connection(ssid) is not None
