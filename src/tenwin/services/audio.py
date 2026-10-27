"""Audio volume and devices via pactl (works with PipeWire and PulseAudio)."""

import json
import logging
import re
import shutil

from gi.repository import Gio, GLib, GObject

log = logging.getLogger(__name__)


def _percent(volume):
    """Average of the per-channel percentages in pactl's JSON volume dict."""
    values = []
    for channel in (volume or {}).values():
        match = re.match(r"(\d+)%", str(channel.get("value_percent", "")))
        if match:
            values.append(int(match.group(1)))
    return round(sum(values) / len(values)) if values else 0


class Device:
    def __init__(self, name, description, volume, muted):
        self.name = name
        self.description = description
        self.volume = volume
        self.muted = muted


class Audio(GObject.Object):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        super().__init__()
        self.available = bool(shutil.which("pactl"))
        self.sinks = []
        self.sources = []
        self.default_sink = None
        self.default_source = None
        self._refresh_id = 0
        self._subscribe = None
        if self.available:
            self.refresh()
            self._start_subscribe()

    # -- state ----------------------------------------------------------

    @property
    def sink(self):
        for dev in self.sinks:
            if dev.name == self.default_sink:
                return dev
        return self.sinks[0] if self.sinks else None

    @property
    def source(self):
        for dev in self.sources:
            if dev.name == self.default_source:
                return dev
        return None

    @property
    def volume(self):
        return self.sink.volume if self.sink else 0

    @property
    def muted(self):
        return self.sink.muted if self.sink else True

    def icon_name(self):
        if not self.available or self.sink is None:
            return "tenwin-volume-muted"
        if self.muted or self.volume == 0:
            return "tenwin-volume-muted"
        if self.volume < 34:
            return "tenwin-volume-low"
        if self.volume < 67:
            return "tenwin-volume-medium"
        return "tenwin-volume-high"

    # -- reading ----------------------------------------------------------

    def _run(self, args, callback=None):
        try:
            proc = Gio.Subprocess.new(["pactl"] + args,
                                      Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error as exc:
            log.warning("pactl: %s", exc)
            return

        def done(p, res):
            try:
                _ok, out, _err = p.communicate_utf8_finish(res)
            except GLib.Error:
                out = ""
            if callback:
                callback(out or "")

        proc.communicate_utf8_async(None, None, done)

    def refresh(self):
        pending = {"n": 4}
        data = {}

        def collect(key):
            def cb(out):
                data[key] = out
                pending["n"] -= 1
                if pending["n"] == 0:
                    self._apply(data)
            return cb

        self._run(["-f", "json", "list", "sinks"], collect("sinks"))
        self._run(["-f", "json", "list", "sources"], collect("sources"))
        self._run(["get-default-sink"], collect("default_sink"))
        self._run(["get-default-source"], collect("default_source"))

    def _apply(self, data):
        def devices(raw, skip_monitors=False):
            try:
                items = json.loads(raw or "[]")
            except ValueError:
                return []
            result = []
            for item in items:
                if skip_monitors and item.get("monitor_of_sink") not in (None, "", "n/a"):
                    continue
                result.append(Device(item.get("name", ""), item.get("description") or item.get("name", ""),
                                     _percent(item.get("volume")), bool(item.get("mute"))))
            return result

        self.sinks = devices(data.get("sinks"))
        self.sources = devices(data.get("sources"), skip_monitors=True)
        self.default_sink = (data.get("default_sink") or "").strip() or None
        self.default_source = (data.get("default_source") or "").strip() or None
        self.emit("changed")

    def _start_subscribe(self):
        try:
            self._subscribe = Gio.Subprocess.new(["pactl", "subscribe"], Gio.SubprocessFlags.STDOUT_PIPE)
        except GLib.Error:
            return
        stream = Gio.DataInputStream.new(self._subscribe.get_stdout_pipe())

        def on_line(s, res, _data):
            try:
                line, _n = s.read_line_finish_utf8(res)
            except GLib.Error:
                return
            if line is None:
                GLib.timeout_add_seconds(5, self._restart_subscribe)
                return
            if "sink" in line or "source" in line or "server" in line:
                self._queue_refresh()
            s.read_line_async(GLib.PRIORITY_DEFAULT, None, on_line, None)

        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, on_line, None)

    def _restart_subscribe(self):
        self._start_subscribe()
        return GLib.SOURCE_REMOVE

    def _queue_refresh(self):
        if self._refresh_id:
            return
        def run():
            self._refresh_id = 0
            self.refresh()
            return GLib.SOURCE_REMOVE
        self._refresh_id = GLib.timeout_add(80, run)

    # -- writing -----------------------------------------------------------

    def set_volume(self, percent):
        percent = max(0, min(100, int(percent)))
        if self.sink:
            self.sink.volume = percent
        self._run(["set-sink-volume", "@DEFAULT_SINK@", "%d%%" % percent])
        if percent > 0 and self.muted:
            self._run(["set-sink-mute", "@DEFAULT_SINK@", "0"])

    def change_volume(self, delta):
        self.set_volume(self.volume + delta)

    def toggle_mute(self):
        self._run(["set-sink-mute", "@DEFAULT_SINK@", "toggle"])

    def set_default_sink(self, name):
        self._run(["set-default-sink", name])

    def set_source_volume(self, percent):
        self._run(["set-source-volume", "@DEFAULT_SOURCE@", "%d%%" % max(0, min(100, int(percent)))])

    def toggle_source_mute(self):
        self._run(["set-source-mute", "@DEFAULT_SOURCE@", "toggle"])

    def set_default_source(self, name):
        self._run(["set-default-source", name])
