"""Game Bar (Win+G): screenshot, screen recording, audio and performance."""

import logging
import os
import shutil

from gi.repository import Gdk, Gio, GLib, Gtk

from tenwin.config import get_settings
from tenwin.gtkutil import add_class, flat_button, human_size, icon_image
from tenwin.i18n import _
from tenwin.shell.layer import Edge, Layer, LayerWindow, set_keyboard

log = logging.getLogger(__name__)

ALL_EDGES = (Edge.TOP, Edge.BOTTOM, Edge.LEFT, Edge.RIGHT)


def captures_dir(settings=None):
    settings = settings or get_settings()
    if settings["gaming.captures_dir"]:
        return settings["gaming.captures_dir"]
    videos = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_VIDEOS) or os.path.expanduser("~/Videos")
    return os.path.join(videos, _("Captures"))


def capture_name(extension):
    return GLib.DateTime.new_now_local().format("%Y-%m-%d %H-%M-%S") + extension


def can_record():
    return shutil.which("wf-recorder") is not None


class SystemStats:
    """CPU and memory usage without walking every process."""

    def __init__(self):
        self._prev = None

    def sample(self):
        from tenwin.taskmgr import procstat
        cpu = 0.0
        try:
            with open("/proc/stat", encoding="utf-8") as fh:
                times = procstat.parse_cpu_times(fh.read())["cpu"]
            if self._prev:
                busy, total = times[0] - self._prev[0], times[1] - self._prev[1]
                cpu = 100.0 * busy / total if total > 0 else 0.0
            self._prev = times
            with open("/proc/meminfo", encoding="utf-8") as fh:
                mem = procstat.parse_meminfo(fh.read())
        except (OSError, KeyError):
            return 0.0, 0, 0
        total = mem.get("MemTotal", 0)
        return cpu, total - mem.get("MemAvailable", 0), total


class RecordingIndicator(LayerWindow):
    """Small "recording" widget with a timer and a stop button."""

    def __init__(self, bar):
        super().__init__("tenwin-capture", layer=Layer.OVERLAY, anchors=(Edge.TOP, Edge.RIGHT),
                         keyboard="none", css="tw-surface")
        self.set_margins(top=60, right=24)
        box = add_class(Gtk.Box(spacing=8), "tw-gamebar-widget", "tw-capture-status")
        box.pack_start(add_class(Gtk.Label(label="●"), "tw-recording-dot"), False, False, 0)
        self.time = Gtk.Label(label="0:00")
        box.pack_start(self.time, False, False, 0)
        stop = flat_button(icon_image("tenwin-record", 16, symbolic=True), "tw-gamebar-button",
                           _("Stop recording (Win+Alt+R)"))
        stop.connect("clicked", lambda *_: bar.stop_recording())
        box.pack_start(stop, False, False, 0)
        self.add(box)

    def set_seconds(self, seconds):
        self.time.set_text("%d:%02d" % divmod(int(seconds), 60))


class GameBar(LayerWindow):
    def __init__(self, shell):
        super().__init__("tenwin-gamebar", layer=Layer.OVERLAY, anchors=ALL_EDGES, keyboard="none",
                         exclusive=-1, css="tw-gamebar")
        self.shell = shell
        self.settings = get_settings()
        self.stats = SystemStats()
        self._recorder = None
        self._record_path = None
        self._record_started = 0
        self._tick_id = 0
        self.indicator = RecordingIndicator(self)
        self._build()
        self.connect("key-press-event", self._on_key)

    def _build(self):
        events = add_class(Gtk.EventBox(), "tw-gamebar-dim")
        events.connect("button-release-event", lambda _w, e: e.button == 1 and self.close() and False)
        self.add(events)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        root.set_margin_top(24)
        events.add(root)

        top = add_class(Gtk.Box(spacing=4), "tw-gamebar-widget", "tw-gamebar-top")
        top.set_halign(Gtk.Align.CENTER)
        top.pack_start(icon_image("tenwin-game", 16, symbolic=True), False, False, 8)
        top.pack_start(Gtk.Label(label=_("Game Bar")), False, False, 0)
        self.clock = add_class(Gtk.Label(), "tw-gamebar-clock")
        top.pack_start(self.clock, False, False, 16)
        settings = flat_button(icon_image("tenwin-settings", 16, symbolic=True), "tw-gamebar-button", _("Settings"))
        settings.connect("clicked", lambda *_: (self.close(), self.shell.open_settings("game-bar")))
        top.pack_start(settings, False, False, 0)
        root.pack_start(top, False, False, 0)

        widgets = Gtk.Box(spacing=16)
        widgets.set_halign(Gtk.Align.START)
        widgets.set_margin_start(24)
        root.pack_start(widgets, False, False, 0)
        widgets.pack_start(self._capture_widget(), False, False, 0)
        widgets.pack_start(self._audio_widget(), False, False, 0)
        widgets.pack_start(self._performance_widget(), False, False, 0)

    def _panel(self, title):
        box = add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "tw-gamebar-widget")
        box.set_size_request(240, -1)
        box.pack_start(add_class(Gtk.Label(label=title, xalign=0), "tw-gamebar-title"), False, False, 0)
        return box

    def _capture_widget(self):
        box = self._panel(_("Capture"))
        row = Gtk.Box(spacing=8)
        shot = flat_button(icon_image("tenwin-snip", 16, symbolic=True), "tw-gamebar-button",
                           _("Take screenshot (Win+Alt+Print)"))
        shot.connect("clicked", lambda *_: self.screenshot())
        row.pack_start(shot, False, False, 0)
        self.record_button = flat_button(icon_image("tenwin-record", 16, symbolic=True), "tw-gamebar-button",
                                         _("Start recording (Win+Alt+R)"))
        self.record_button.connect("clicked", lambda *_: self.toggle_recording())
        self.record_button.set_sensitive(can_record())
        row.pack_start(self.record_button, False, False, 0)
        box.pack_start(row, False, False, 0)
        if not can_record():
            hint = add_class(Gtk.Label(label=_("Install wf-recorder to record the screen."), xalign=0, wrap=True),
                             "tw-dim")
            hint.set_max_width_chars(30)
            box.pack_start(hint, False, False, 0)
        link = flat_button(Gtk.Label(label=_("Show all captures"), xalign=0), "tw-ac-link")
        link.connect("clicked", lambda *_: self._open_captures())
        box.pack_start(link, False, False, 0)
        return box

    def _audio_widget(self):
        box = self._panel(_("Audio"))
        row = Gtk.Box(spacing=8)
        row.pack_start(icon_image("tenwin-volume-high", 16, symbolic=True), False, False, 0)
        self.volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.volume.set_draw_value(False)
        self.volume.connect("value-changed", lambda s: self._set_volume(s.get_value()))
        row.pack_start(self.volume, True, True, 0)
        box.pack_start(row, False, False, 0)
        self.mic = Gtk.CheckButton(label=_("Microphone muted"))
        self.mic.connect("toggled", lambda b: self._set_mic(b.get_active()))
        box.pack_start(self.mic, False, False, 0)
        return box

    def _performance_widget(self):
        box = self._panel(_("Performance"))
        self.cpu_label = add_class(Gtk.Label(xalign=0), "tw-gamebar-big")
        self.mem_label = add_class(Gtk.Label(xalign=0), "tw-gamebar-big")
        for caption, label in ((_("CPU"), self.cpu_label), (_("RAM"), self.mem_label)):
            row = Gtk.Box(spacing=8)
            row.pack_start(add_class(Gtk.Label(label=caption, xalign=0), "tw-dim"), False, False, 0)
            row.pack_end(label, False, False, 0)
            box.pack_start(row, False, False, 0)
        return box

    # -- show / hide ----------------------------------------------------------------

    def toggle(self):
        if not self.settings["gaming.game_bar"]:
            return
        if self.get_visible():
            self.close()
        else:
            self.open()

    def open(self):
        self.shell.close_popups()
        self._updating = True
        self.volume.set_value(self.shell.audio.volume)
        self.mic.set_active(self._mic_muted())
        self._updating = False
        if self.shell.current_monitor is not None:
            self.set_monitor(self.shell.current_monitor)
        set_keyboard(self, "exclusive")
        self.show_all()
        self._update()
        if not self._tick_id:
            self._tick_id = GLib.timeout_add(1000, self._update)

    def close(self):
        if self._tick_id and self._recorder is None:
            GLib.source_remove(self._tick_id)
            self._tick_id = 0
        self.hide()
        return False

    def _update(self):
        now = GLib.DateTime.new_now_local()
        self.clock.set_text(now.format("%H:%M" if self.settings["region.clock_24h"] else "%l:%M %p").strip())
        cpu, used, total = self.stats.sample()
        self.cpu_label.set_text("%d %%" % round(cpu))
        self.mem_label.set_text("%d %%  (%s)" % (round(100 * used / total) if total else 0, human_size(used)))
        if self._recorder is not None:
            self.indicator.set_seconds(GLib.get_monotonic_time() / 1e6 - self._record_started)
        if not self.get_visible() and self._recorder is None:
            self._tick_id = 0
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def _set_volume(self, value):
        if not getattr(self, "_updating", False):
            self.shell.audio.set_volume(int(value))

    def _set_mic(self, muted):
        if not getattr(self, "_updating", False):
            if self._mic_muted() != muted:
                self.shell.audio.toggle_source_mute()

    def _mic_muted(self):
        source = self.shell.audio.source
        return bool(source and source.muted)

    # -- captures --------------------------------------------------------------------

    def _open_captures(self):
        os.makedirs(captures_dir(self.settings), exist_ok=True)
        self.close()
        self.shell.command("explorer %s" % GLib.shell_quote(captures_dir(self.settings)))

    def screenshot(self):
        folder = captures_dir(self.settings)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, capture_name(".png"))
        self.close()

        def shoot():
            from tenwin.services import system
            system.run(["grim", path])
            GLib.timeout_add(600, lambda: self._notify(_("Screenshot saved"), path) and False)
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(250, shoot)  # let the overlay disappear first

    def toggle_recording(self):
        if self._recorder is None:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        if not can_record() or self._recorder is not None:
            return
        folder = captures_dir(self.settings)
        os.makedirs(folder, exist_ok=True)
        self._record_path = os.path.join(folder, capture_name(".mp4"))
        argv = ["wf-recorder", "-f", self._record_path]
        if self.shell.current_monitor is not None:
            output = self.shell.wm.output_name(self.shell.current_monitor)
            if output:
                argv += ["-o", output]
        try:
            self._recorder = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_SILENCE |
                                                Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error as exc:
            log.warning("cannot record: %s", exc)
            self._recorder = None
            return
        self._record_started = GLib.get_monotonic_time() / 1e6
        self._recorder.wait_async(None, self._recording_ended)
        self.close()
        self.indicator.set_seconds(0)
        self.indicator.show_all()
        if not self._tick_id:
            self._tick_id = GLib.timeout_add(1000, self._update)

    def stop_recording(self):
        if self._recorder is not None:
            self._recorder.send_signal(2)  # SIGINT finishes the file

    def _recording_ended(self, proc, result):
        try:
            proc.wait_finish(result)
        except GLib.Error:
            pass
        self._recorder = None
        self.indicator.hide()
        if self._record_path and os.path.exists(self._record_path):
            self._notify(_("Recording saved"), self._record_path)

    def _notify(self, summary, path):
        self.shell.notifications.notify(_("Game Bar"), 0, "tenwin-game", summary, path, [],
                                        {"transient": True}, 4000)
