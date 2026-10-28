"""Snap Assist, Win+Up/Down quarter snapping and window arrangements.

The window geometry is invisible to Tenwin (wlr-foreign-toplevel has none),
so the shell remembers how it snapped each window. A window dragged away by
hand keeps its remembered state until it is snapped, maximised or restored
again.
"""

import logging

from gi.repository import Gdk, GLib, Gtk

from tenwin import session, wm
from tenwin.config import load_file
from tenwin.gtkutil import clear_children, set_class
from tenwin.shell.layer import Edge, Popup, taskbar_edge, taskbar_height
from tenwin.shell.switcher import window_card

log = logging.getLogger(__name__)


class Snapper:
    def __init__(self, shell):
        self.shell = shell
        self.wm = shell.wm
        self.states = {}
        self.assist = SnapAssist(shell, self)
        self._arranging = False
        self.wm.connect("window-changed", self._on_changed)
        self.wm.connect("window-removed", lambda _wm, w: self.states.pop(w.id, None))

    def _on_changed(self, _wm, window):
        if window.maximized:
            self.states[window.id] = "max"
        elif self.states.get(window.id) == "max":
            self.states.pop(window.id, None)

    def state(self, window):
        return self.states.get(window.id)

    # -- commands ---------------------------------------------------------------

    def snapped(self, side):
        """labwc already snapped the active window (Win+Left/Right)."""
        window = self.wm.active
        if window is None:
            return
        self.states[window.id] = side
        if self.shell.settings["snap.assist"]:
            # Wait until labwc has resized the window before covering the other half.
            GLib.timeout_add(120, lambda: self.assist.offer(window, side) and False)

    def snap(self, direction):
        window = self.wm.active
        if window is None:
            return
        step = wm.next_step(self.state(window), direction)
        if step is None:
            return
        if step == "maximize":
            if window.minimized:
                self.wm.activate(window)
            self.wm.send("maximize", window)
        elif step == "unmaximize":
            self.wm.send("unmaximize", window)
        elif step == "minimize":
            self.wm.minimize(window)
        else:
            self.place(window, step)

    def place(self, window, action):
        self.states[window.id] = wm.STATE_OF.get(action)
        self.wm.run_action(window, action)

    def arrange(self, kind):
        """Cascade ("cascade"), stack ("stack") or tile side by side ("side")."""
        if self._arranging:
            return
        windows = [w for w in self.wm.list(mru=True) if not w.minimized and not w.parent]
        if not windows:
            return
        windows.reverse()  # the most recently used window ends up on top / last
        boxes = wm.slot_boxes(kind, len(windows), self.usable_area())
        windows = windows[-len(boxes):]
        previous = self.wm.active
        self._arranging = True
        # The slot bindings carry pixel geometry, so they are rewritten each time.
        session.write_labwc_config(load_file(), boxes)
        session.reconfigure_labwc()

        def run():
            for index, window in enumerate(windows):
                self.states.pop(window.id, None)
                last = index == len(windows) - 1
                self.wm.run_action(window, wm.slot_name(index), finish if last else None)
            return GLib.SOURCE_REMOVE

        def finish(_ok):
            if previous is not None and previous is not self.wm.active:
                self.wm.activate(previous)
            self._arranging = False

        # labwc re-reads its configuration asynchronously after SIGHUP.
        GLib.timeout_add(300, run)

    def usable_area(self):
        """Current monitor without the taskbar, in layout coordinates."""
        monitor = self.shell.current_monitor
        if monitor is None:
            return (0, 0, 1280, 720)
        geo = monitor.get_geometry()
        bar = taskbar_height()
        top = taskbar_edge() == Edge.TOP
        return (geo.x, geo.y + (bar if top else 0), geo.width, geo.height - bar)


class SnapAssist(Popup):
    """After Win+Left/Right: pick the window for the other half of the screen."""

    def __init__(self, shell, snapper):
        super().__init__("tenwin-snapassist", anchors=(Edge.TOP, Edge.BOTTOM, Edge.RIGHT),
                         css="tw-popup tw-snapassist")
        self.shell = shell
        self.snapper = snapper
        self.windows = []
        self.cards = []
        self.index = 0
        self.side = "right"
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        self.flow = Gtk.FlowBox(homogeneous=True, column_spacing=16, row_spacing=16)
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        box.pack_start(self.flow, False, False, 0)
        events = Gtk.EventBox()
        events.get_style_context().add_class("tw-snapassist-dim")
        events.add(box)
        events.connect("button-release-event", self._on_background)
        self.add(events)

    def offer(self, snapped_window, side):
        others = [w for w in self.shell.wm.list(mru=True)
                  if w is not snapped_window and not w.parent
                  and self.snapper.state(w) not in (side,)]
        if not others:
            return
        self.side = "left" if side == "right" else "right"
        self.windows = others[:9]
        self.set_anchors((Edge.TOP, Edge.BOTTOM, Edge.LEFT if self.side == "left" else Edge.RIGHT))
        monitor = self.shell.current_monitor
        if monitor is not None:
            self.set_size_request(monitor.get_geometry().width // 2, -1)
        clear_children(self.flow)
        self.cards = [window_card(self.shell, w, (220, 140), self._choose) for w in self.windows]
        for card in self.cards:
            self.flow.add(card)
        self.flow.set_max_children_per_line(2 if len(self.cards) > 1 else 1)
        self.index = 0
        self.open_popup(monitor)
        self._highlight()

    def _highlight(self):
        for i, card in enumerate(self.cards):
            set_class(card, "selected", i == self.index)

    def _choose(self, window):
        self.close_popup()
        self.snapper.place(window, "edge-" + self.side)

    def _on_background(self, _widget, event):
        if event.button == 1:
            self.close_popup()
        return False

    def _on_key(self, widget, event):
        key = event.keyval
        if not self.windows or key == Gdk.KEY_Escape:
            self.close_popup()
        elif key in (Gdk.KEY_Right, Gdk.KEY_Down, Gdk.KEY_Tab):
            self.index = (self.index + 1) % len(self.windows)
            self._highlight()
        elif key in (Gdk.KEY_Left, Gdk.KEY_Up, Gdk.KEY_ISO_Left_Tab):
            self.index = (self.index - 1) % len(self.windows)
            self._highlight()
        elif key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            self._choose(self.windows[self.index])
        return True
