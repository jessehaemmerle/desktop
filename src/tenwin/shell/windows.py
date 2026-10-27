"""Window list via the tenwin-toplevel helper (wlr-foreign-toplevel)."""

import json
import logging

from gi.repository import Gio, GLib, GObject

from tenwin import paths

log = logging.getLogger(__name__)


class Window(GObject.Object):
    def __init__(self, wid):
        super().__init__()
        self.id = wid
        self.title = ""
        self.app_id = ""
        self.maximized = False
        self.minimized = False
        self.activated = False
        self.fullscreen = False
        self.parent = 0
        self.outputs = []

    def update(self, data):
        changed = False
        for key in ("title", "app_id", "maximized", "minimized", "activated",
                    "fullscreen", "parent", "outputs"):
            if key in data and getattr(self, key) != data[key]:
                setattr(self, key, data[key])
                changed = True
        return changed

    def __repr__(self):
        return "<Window %d %r %r>" % (self.id, self.app_id, self.title)


class WindowManager(GObject.Object):
    """Tracks open windows and sends commands to them."""

    __gsignals__ = {
        "window-added": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "window-changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "window-removed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "active-changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self):
        super().__init__()
        self.windows = {}
        self.order = []        # stable order of appearance (taskbar)
        self.mru = []          # most recently used first (Alt+Tab)
        self.active = None
        self._proc = None
        self._stdin = None
        self._restarts = 0
        self._shown_desktop = None
        self.start()

    # -- helper process ----------------------------------------------------

    def start(self):
        helper = paths.helper("tenwin-toplevel")
        try:
            self._proc = Gio.Subprocess.new(
                [helper], Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE)
        except GLib.Error as exc:
            log.error("cannot start %s: %s", helper, exc)
            return
        self._stdin = self._proc.get_stdin_pipe()
        stream = Gio.DataInputStream.new(self._proc.get_stdout_pipe())
        self._read_next(stream)
        self._proc.wait_async(None, self._on_exit)

    def _read_next(self, stream):
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_line, stream)

    def _on_line(self, stream, result, _data):
        try:
            line, _length = stream.read_line_finish_utf8(result)
        except GLib.Error as exc:
            log.warning("toplevel helper: %s", exc)
            return
        if line is None:
            return
        try:
            self._handle(json.loads(line))
        except ValueError:
            log.warning("bad helper line: %r", line)
        self._read_next(stream)

    def _on_exit(self, proc, result):
        try:
            proc.wait_finish(result)
        except GLib.Error:
            pass
        for wid in list(self.windows):
            self._remove(wid)
        self._restarts += 1
        if self._restarts < 10:
            GLib.timeout_add_seconds(min(30, 2 ** self._restarts), self._restart)

    def _restart(self):
        self.start()
        return GLib.SOURCE_REMOVE

    def _send(self, command, window):
        if self._stdin is None or window is None:
            return
        try:
            self._stdin.write_all(("%s %d\n" % (command, window.id)).encode(), None)
            self._stdin.flush(None)
        except GLib.Error as exc:
            log.warning("cannot talk to toplevel helper: %s", exc)

    # -- events --------------------------------------------------------------

    def _handle(self, msg):
        ev = msg.get("ev")
        if ev == "update":
            wid = msg["id"]
            window = self.windows.get(wid)
            new = window is None
            if new:
                window = Window(wid)
                self.windows[wid] = window
                self.order.append(wid)
                self.mru.append(wid)
            window.update(msg)
            if new:
                self.emit("window-added", window)
            else:
                self.emit("window-changed", window)
            if window.activated and self.active is not window:
                self.active = window
                if wid in self.mru:
                    self.mru.remove(wid)
                self.mru.insert(0, wid)
                self._shown_desktop = None
                self.emit("active-changed", window)
            elif not window.activated and self.active is window:
                self.active = None
                self.emit("active-changed", None)
        elif ev == "closed":
            self._remove(msg["id"])
        elif ev == "ready":
            self._restarts = 0

    def _remove(self, wid):
        window = self.windows.pop(wid, None)
        if window is None:
            return
        for lst in (self.order, self.mru):
            if wid in lst:
                lst.remove(wid)
        if self.active is window:
            self.active = None
            self.emit("active-changed", None)
        self.emit("window-removed", window)

    # -- queries ------------------------------------------------------------

    def list(self, mru=False):
        ids = self.mru if mru else self.order
        return [self.windows[i] for i in ids if i in self.windows]

    def for_app(self, matcher):
        return [w for w in self.list() if matcher(w)]

    # -- actions ------------------------------------------------------------

    def activate(self, window):
        self._send("activate", window)

    def minimize(self, window):
        self._send("minimize", window)

    def close(self, window):
        self._send("close", window)

    def toggle(self, window):
        """Taskbar click: minimise the active window, otherwise activate it."""
        if window.activated and not window.minimized:
            self.minimize(window)
        else:
            self.activate(window)

    def maximize_active(self):
        if self.active is not None:
            if self.active.minimized:
                self.activate(self.active)
            self._send("maximize", self.active)

    def restore_or_minimize_active(self):
        window = self.active
        if window is None:
            return
        if window.maximized:
            self._send("unmaximize", window)
        elif window.fullscreen:
            self._send("unfullscreen", window)
        else:
            self.minimize(window)

    def minimize_all(self):
        for window in self.list():
            if not window.minimized:
                self.minimize(window)

    def toggle_show_desktop(self):
        """Win+D: minimise everything, a second press restores it."""
        if self._shown_desktop:
            restore = [self.windows[i] for i in self._shown_desktop if i in self.windows]
            self._shown_desktop = None
            for window in reversed(restore):
                self.activate(window)
            return
        visible = [w for w in self.list(mru=True) if not w.minimized]
        self._shown_desktop = [w.id for w in visible]
        for window in visible:
            self.minimize(window)
