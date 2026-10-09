"""Systemdienste: Lautstärke, Helligkeit, Netzwerk, Bluetooth, Akku, Medien, Nachtlicht."""

from __future__ import annotations

import os
import signal

from gi.repository import Gio, GLib, GObject

from ..core import parsers
from . import util


class Service(GObject.Object):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}


class Audio(Service):
    STEP = 0.05

    def __init__(self):
        super().__init__()
        self.volume = 0.0
        self.muted = False
        self.available = util.has("wpctl") or util.has("pactl")
        self._subscribe()
        self.refresh()
        GLib.timeout_add_seconds(10, lambda: self.refresh() or True)

    def _subscribe(self) -> None:
        """``pactl subscribe`` liefert Änderungen sofort (auch per Tastatur oder anderer App)."""
        if not util.has("pactl"):
            return
        try:
            proc = Gio.Subprocess.new(["pactl", "subscribe"], Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error:
            return
        stream = Gio.DataInputStream.new(proc.get_stdout_pipe())
        self._sub = proc
        self._pending = 0

        def on_line(source, result):
            try:
                line, _len = source.read_line_finish_utf8(result)
            except GLib.Error:
                return
            if line is None:
                return
            if "sink" in line and not self._pending:
                self._pending = GLib.timeout_add(80, self._debounced_refresh)
            source.read_line_async(GLib.PRIORITY_DEFAULT, None, on_line)

        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, on_line)

    def _debounced_refresh(self) -> bool:
        self._pending = 0
        self.refresh()
        return False

    def refresh(self) -> None:
        if util.has("wpctl"):
            util.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], self._parsed_wpctl)
        elif util.has("pactl"):
            util.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                     lambda out: util.run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"],
                                          lambda mute: self._set(parsers.parse_pactl_volume(out or "", mute or ""))))

    def _parsed_wpctl(self, out) -> None:
        self._set(parsers.parse_wpctl_volume(out or ""))

    def _set(self, result) -> None:
        if result is None:
            return
        volume, muted = result
        if abs(volume - self.volume) > 1e-3 or muted != self.muted:
            self.volume, self.muted = volume, muted
            self.emit("changed")

    def set_volume(self, value: float) -> None:
        value = max(0.0, min(1.0, value))
        self.volume = value
        if util.has("wpctl"):
            util.run(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{value:.2f}"], lambda _o: self.refresh())
        elif util.has("pactl"):
            util.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{round(value * 100)}%"], lambda _o: self.refresh())

    def step(self, direction: int) -> None:
        if self.muted and direction > 0:
            self.toggle_mute()
        self.set_volume(round((self.volume + direction * self.STEP) / self.STEP) * self.STEP)
        self.emit("changed")

    def toggle_mute(self) -> None:
        self.muted = not self.muted
        if util.has("wpctl"):
            util.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"], lambda _o: self.refresh())
        elif util.has("pactl"):
            util.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"], lambda _o: self.refresh())
        self.emit("changed")

    @property
    def icon(self) -> str:
        return parsers.volume_icon(self.volume, self.muted)


class Brightness(Service):
    def __init__(self):
        super().__init__()
        self.level: float | None = None
        self.refresh()

    @property
    def available(self) -> bool:
        return self.level is not None

    def refresh(self) -> None:
        util.run(["brightnessctl", "-m", "-c", "backlight", "info"], self._parsed)

    def _parsed(self, out) -> None:
        level = parsers.parse_brightnessctl(out or "")
        if level is not None and level != self.level:
            self.level = level
            self.emit("changed")

    def set_level(self, value: float) -> None:
        value = max(0.02, min(1.0, value))
        self.level = value
        util.run(["brightnessctl", "-q", "-c", "backlight", "set", f"{round(value * 100)}%"])

    def step(self, direction: int) -> None:
        if self.level is not None:
            self.set_level(self.level + direction * 0.05)
            self.emit("changed")


class Network(Service):
    def __init__(self):
        super().__init__()
        self.info = {"kind": "none", "connected": False, "name": ""}
        self.signal: int | None = None
        self.wifi_enabled = True
        self.available = util.has("nmcli")
        if self.available:
            self.refresh()
            GLib.timeout_add_seconds(6, lambda: self.refresh() or True)

    def refresh(self) -> None:
        util.run(["nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "device"], self._devices)
        util.run(["nmcli", "radio", "wifi"], self._radio)

    def _devices(self, out) -> None:
        info = parsers.parse_nmcli_devices(out or "")
        if info["kind"] == "wifi" and info["connected"]:
            util.run(["nmcli", "-t", "-f", "ACTIVE,SIGNAL", "dev", "wifi"], lambda o: self._signal(info, o))
        else:
            self._update(info, None)

    def _signal(self, info, out) -> None:
        self._update(info, parsers.parse_wifi_signal(out or ""))

    def _radio(self, out) -> None:
        enabled = (out or "").strip() in ("enabled", "aktiviert")
        if enabled != self.wifi_enabled:
            self.wifi_enabled = enabled
            self.emit("changed")

    def _update(self, info, signal_strength) -> None:
        if info != self.info or signal_strength != self.signal:
            self.info, self.signal = info, signal_strength
            self.emit("changed")

    def toggle_wifi(self) -> None:
        self.wifi_enabled = not self.wifi_enabled
        util.run(["nmcli", "radio", "wifi", "on" if self.wifi_enabled else "off"], lambda _o: self.refresh())
        self.emit("changed")

    @property
    def icon(self) -> str:
        if self.info["kind"] != "ethernet" and not self.wifi_enabled:
            return "network-wireless-disabled-symbolic"
        return parsers.network_icon(self.info, self.signal)

    @property
    def label(self) -> str:
        if self.info["connected"]:
            return self.info["name"] or ("Kabel" if self.info["kind"] == "ethernet" else "WLAN")
        if not self.wifi_enabled:
            return "Aus"
        return "Nicht verbunden"


class Bluetooth(Service):
    def __init__(self):
        super().__init__()
        self.powered: bool | None = None
        self.refresh()

    @property
    def available(self) -> bool:
        return self.powered is not None

    def refresh(self) -> None:
        if util.has("bluetoothctl") and util.has("timeout"):
            util.run(["timeout", "2", "bluetoothctl", "show"], self._parsed)

    def _parsed(self, out) -> None:
        powered = parsers.parse_bluetoothctl_show(out or "")
        if powered != self.powered:
            self.powered = powered
            self.emit("changed")

    def toggle(self) -> None:
        if self.powered is None:
            return
        self.powered = not self.powered
        util.run(["timeout", "4", "bluetoothctl", "power", "on" if self.powered else "off"], lambda _o: self.refresh())
        self.emit("changed")


class Battery(Service):
    def __init__(self):
        super().__init__()
        self.state = parsers.read_battery()
        GLib.timeout_add_seconds(30, self._poll)

    def _poll(self) -> bool:
        state = parsers.read_battery()
        if state != self.state:
            self.state = state
            self.emit("changed")
        return True

    @property
    def available(self) -> bool:
        return self.state is not None

    @property
    def icon(self) -> str:
        if not self.state:
            return "battery-missing-symbolic"
        return parsers.battery_icon(self.state["percent"], self.state["charging"])


class NightLight(Service):
    """Schaltet wlsunset/gammastep – sofern installiert."""

    def __init__(self):
        super().__init__()
        self.tool = next((t for t in ("wlsunset", "gammastep") if util.has(t)), None)
        self._pid: int | None = None

    @property
    def available(self) -> bool:
        return self.tool is not None

    @property
    def enabled(self) -> bool:
        return self._pid is not None

    def toggle(self) -> None:
        if self._pid is not None:
            try:
                os.kill(self._pid, signal.SIGTERM)
            except OSError:
                pass
            self._pid = None
        elif self.tool:
            argv = ["wlsunset", "-T", "4001", "-t", "3400", "-S", "00:00", "-s", "00:01"] if self.tool == "wlsunset" \
                else ["gammastep", "-O", "3600"]
            try:
                pid, *_ = GLib.spawn_async(argv, flags=GLib.SpawnFlags.SEARCH_PATH | GLib.SpawnFlags.DO_NOT_REAP_CHILD
                                           | GLib.SpawnFlags.STDOUT_TO_DEV_NULL | GLib.SpawnFlags.STDERR_TO_DEV_NULL)
                self._pid = pid
                GLib.child_watch_add(GLib.PRIORITY_DEFAULT, pid, self._exited)
            except GLib.Error:
                self._pid = None
        self.emit("changed")

    def _exited(self, pid, _status) -> None:
        GLib.spawn_close_pid(pid)
        if self._pid == pid:
            self._pid = None
            self.emit("changed")


class Media(Service):
    """MPRIS-Mediensteuerung (Spotify, Firefox, VLC, …)."""

    PREFIX = "org.mpris.MediaPlayer2."

    def __init__(self):
        super().__init__()
        self.players: dict[str, Gio.DBusProxy] = {}
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error:
            self.bus = None
            return
        self.bus.signal_subscribe(
            "org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged", "/org/freedesktop/DBus",
            None, Gio.DBusSignalFlags.NONE, self._owner_changed,
        )
        self.bus.call(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames",
            None, GLib.VariantType("(as)"), Gio.DBusCallFlags.NONE, -1, None, self._listed,
        )

    def _listed(self, bus, result) -> None:
        try:
            (names,) = bus.call_finish(result).unpack()
        except GLib.Error:
            return
        for name in names:
            if name.startswith(self.PREFIX):
                self._add(name)

    def _owner_changed(self, _conn, _sender, _path, _iface, _signal, params) -> None:
        name, _old, new = params.unpack()
        if not name.startswith(self.PREFIX):
            return
        if new:
            self._add(name)
        elif name in self.players:
            del self.players[name]
            self.emit("changed")

    def _add(self, name: str) -> None:
        def ready(_source, result):
            try:
                proxy = Gio.DBusProxy.new_finish(result)
            except GLib.Error:
                return
            proxy.connect("g-properties-changed", lambda *_: self.emit("changed"))
            self.players[name] = proxy
            self.emit("changed")

        Gio.DBusProxy.new(self.bus, Gio.DBusProxyFlags.NONE, None, name, "/org/mpris/MediaPlayer2",
                          "org.mpris.MediaPlayer2.Player", None, ready)

    def _status(self, proxy) -> str:
        value = proxy.get_cached_property("PlaybackStatus")
        return value.unpack() if value is not None else "Stopped"

    def current(self) -> Gio.DBusProxy | None:
        ranked = sorted(self.players.values(), key=lambda p: {"Playing": 0, "Paused": 1}.get(self._status(p), 2))
        for proxy in ranked:
            if self._status(proxy) in ("Playing", "Paused"):
                return proxy
        return None

    def info(self) -> dict | None:
        proxy = self.current()
        if proxy is None:
            return None
        meta = proxy.get_cached_property("Metadata")
        meta = meta.unpack() if meta is not None else {}
        artist = meta.get("xesam:artist") or []
        if isinstance(artist, str):
            artist = [artist]
        name = proxy.get_name()[len(self.PREFIX):].split(".")[0]
        return {
            "title": meta.get("xesam:title") or name.capitalize(),
            "artist": ", ".join(artist),
            "art": meta.get("mpris:artUrl") or "",
            "playing": self._status(proxy) == "Playing",
            "player": name,
        }

    def _call(self, method: str) -> None:
        proxy = self.current()
        if proxy is not None:
            proxy.call(method, None, Gio.DBusCallFlags.NONE, -1, None, None)

    def play_pause(self) -> None:
        self._call("PlayPause")

    def next(self) -> None:
        self._call("Next")

    def previous(self) -> None:
        self._call("Previous")


class Services:
    def __init__(self):
        self.audio = Audio()
        self.brightness = Brightness()
        self.network = Network()
        self.bluetooth = Bluetooth()
        self.battery = Battery()
        self.nightlight = NightLight()
        self.media = Media()
