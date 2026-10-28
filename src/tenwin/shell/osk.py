"""Touch keyboard (Windows 10 style) at the bottom of the screen.

It never takes keyboard focus; key presses go to the focused window through a
long-running ``tenwin-vkbd --stdin`` with the user's keyboard layout.
"""

import logging

from gi.repository import Gio, GLib, Gtk

from tenwin import paths
from tenwin.config import get_settings
from tenwin.gtkutil import clear_children, flat_button, icon_image, set_class
from tenwin.i18n import _
from tenwin.shell.layer import Edge, Layer, LayerWindow

log = logging.getLogger(__name__)

# evdev key codes (linux/input-event-codes.h)
KEY_BACKSPACE, KEY_TAB, KEY_ENTER, KEY_SPACE = 14, 15, 28, 57
KEY_LEFT, KEY_RIGHT, KEY_UP, KEY_DOWN = 105, 106, 103, 108
KEY_ESC = 1

# Letter rows per layout: (label, code). Labels are what the key types on that layout.
LETTERS = {
    "de": [
        [("q", 16), ("w", 17), ("e", 18), ("r", 19), ("t", 20), ("z", 21), ("u", 22), ("i", 23), ("o", 24),
         ("p", 25), ("ü", 26)],
        [("a", 30), ("s", 31), ("d", 32), ("f", 33), ("g", 34), ("h", 35), ("j", 36), ("k", 37), ("l", 38),
         ("ö", 39), ("ä", 40)],
        [("y", 44), ("x", 45), ("c", 46), ("v", 47), ("b", 48), ("n", 49), ("m", 50), (",", 51), (".", 52),
         ("-", 53)],
    ],
    "us": [
        [("q", 16), ("w", 17), ("e", 18), ("r", 19), ("t", 20), ("y", 21), ("u", 22), ("i", 23), ("o", 24),
         ("p", 25)],
        [("a", 30), ("s", 31), ("d", 32), ("f", 33), ("g", 34), ("h", 35), ("j", 36), ("k", 37), ("l", 38),
         ("'", 40)],
        [("z", 44), ("x", 45), ("c", 46), ("v", 47), ("b", 48), ("n", 49), ("m", 50), (",", 51), (".", 52),
         ("?", 53, "shift")],
    ],
}

# The "&123" view: (label, code, modifiers…)
SYMBOLS = {
    "de": [
        [("1", 2), ("2", 3), ("3", 4), ("4", 5), ("5", 6), ("6", 7), ("7", 8), ("8", 9), ("9", 10), ("0", 11)],
        [("@", 16, "altgr"), ("#", 43), ("€", 18, "altgr"), ("&", 7, "shift"), ("_", 53, "shift"),
         ("-", 53), ("(", 9, "shift"), (")", 10, "shift"), ("=", 11, "shift"), ("%", 6, "shift")],
        [('"', 3, "shift"), ("*", 27, "shift"), ("'", 43, "shift"), (":", 52, "shift"), ("/", 8, "shift"),
         ("!", 2, "shift"), ("?", 12, "shift"), ("+", 27), ("<", 86), (">", 86, "shift")],
    ],
    "us": [
        [("1", 2), ("2", 3), ("3", 4), ("4", 5), ("5", 6), ("6", 7), ("7", 8), ("8", 9), ("9", 10), ("0", 11)],
        [("@", 3, "shift"), ("#", 4, "shift"), ("$", 5, "shift"), ("&", 8, "shift"), ("_", 12, "shift"),
         ("-", 12), ("(", 10, "shift"), (")", 11, "shift"), ("=", 13), ("%", 6, "shift")],
        [('"', 40, "shift"), ("*", 9, "shift"), ("'", 40), (":", 39, "shift"), ("/", 53),
         ("!", 2, "shift"), ("?", 53, "shift"), ("+", 13, "shift"), ("<", 51, "shift"), (">", 52, "shift")],
    ],
}


def layout_name(settings=None):
    settings = settings or get_settings()
    first = (settings["input.keyboard_layouts"] or "us").split(",")[0].strip()
    return first if first in LETTERS else "us"


def tap_command(code, *mods):
    return " ".join(["tap", str(code)] + [m for m in mods if m]) + "\n"


class TouchKeyboard(LayerWindow):
    def __init__(self, shell):
        # Same layer as the taskbar, created later: labwc docks it above the taskbar.
        super().__init__("tenwin-osk", layer=Layer.TOP, anchors=(Edge.BOTTOM, Edge.LEFT, Edge.RIGHT),
                         keyboard="none", exclusive="auto", css="tw-surface")
        self.shell = shell
        self.settings = get_settings()
        self.shift = False
        self.caps = False
        self.symbols = False
        self._proc = None
        self._stdin = None
        self._layout = None
        frame = Gtk.Box()
        frame.get_style_context().add_class("tw-osk")
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.box.set_halign(Gtk.Align.CENTER)
        for side in ("top", "bottom"):
            getattr(self.box, "set_margin_" + side)(8)
        frame.pack_start(self.box, True, True, 0)
        self.add(frame)
        self.settings.connect("changed", self._on_settings)

    # -- helper -----------------------------------------------------------------

    def _ensure_helper(self):
        layout = layout_name(self.settings)
        if self._proc is not None and layout == self._layout:
            return True
        self._stop_helper()
        argv = [paths.helper("tenwin-vkbd"), "--layout", layout]
        if self.settings["input.keyboard_variant"]:
            argv += ["--variant", self.settings["input.keyboard_variant"]]
        try:
            self._proc = Gio.Subprocess.new(argv + ["--stdin"], Gio.SubprocessFlags.STDIN_PIPE)
        except GLib.Error as exc:
            log.warning("cannot start tenwin-vkbd: %s", exc)
            return False
        self._layout = layout
        self._stdin = self._proc.get_stdin_pipe()
        return True

    def _stop_helper(self):
        if self._stdin is not None:
            try:
                self._stdin.close(None)
            except GLib.Error:
                pass
        self._proc = self._stdin = None

    def send(self, code, *mods):
        if not self._ensure_helper():
            return
        try:
            self._stdin.write_all(tap_command(code, *mods).encode(), None)
            self._stdin.flush(None)
        except GLib.Error as exc:
            log.warning("touch keyboard: %s", exc)
            self._stop_helper()

    # -- layout ---------------------------------------------------------------------

    def _key(self, label, callback, width=1.0, css=None, icon=None):
        button = flat_button(css="tw-osk-key" + (" " + css if css else ""))
        button.set_size_request(int(56 * width), 48)
        if icon:
            button.add(icon_image(icon, 16, symbolic=True))
        else:
            button.add(Gtk.Label(label=label))
        button.connect("clicked", lambda *_: callback())
        return button

    def _build(self):
        clear_children(self.box)
        layout = layout_name(self.settings)
        rows = SYMBOLS[layout] if self.symbols else LETTERS[layout]
        upper = (self.shift or self.caps) and not self.symbols
        for index, keys in enumerate(rows):
            row = Gtk.Box(spacing=4)
            row.set_halign(Gtk.Align.CENTER)
            if index == 2 and not self.symbols:
                shift = self._key("", self._toggle_shift, 1.4, "mod", icon="tenwin-shift")
                set_class(shift, "on", self.shift or self.caps)
                row.pack_start(shift, False, False, 0)
            for entry in keys:
                label, code, mods = entry[0], entry[1], entry[2:]
                text = label.upper() if upper and label.isalpha() else label
                row.pack_start(self._key(text, lambda c=code, m=mods, l=label: self._type(c, m, l)), False, False, 0)
            if index == 0:
                row.pack_start(self._key("", lambda: self.send(KEY_BACKSPACE), 1.4, "mod", icon="tenwin-backspace"),
                               False, False, 0)
            elif index == 1:
                row.pack_start(self._key("", lambda: self.send(KEY_ENTER), 1.4, "mod accent", icon="tenwin-enter"),
                               False, False, 0)
            self.box.pack_start(row, False, False, 0)
        bottom = Gtk.Box(spacing=4)
        bottom.set_halign(Gtk.Align.CENTER)
        bottom.pack_start(self._key(_("abc") if self.symbols else "&123", self._toggle_symbols, 1.4, "mod"),
                          False, False, 0)
        bottom.pack_start(self._key(_("Tab"), lambda: self.send(KEY_TAB), 1.2, "mod"), False, False, 0)
        bottom.pack_start(self._key("", lambda: self.send(KEY_SPACE), 6.0), False, False, 0)
        for icon, code in (("tenwin-chevron-left", KEY_LEFT), ("tenwin-chevron-right", KEY_RIGHT)):
            bottom.pack_start(self._key("", lambda c=code: self.send(c), 1.0, "mod", icon=icon), False, False, 0)
        bottom.pack_start(self._key("", self.hide_keyboard, 1.2, "mod", icon="tenwin-keyboard-hide"),
                          False, False, 0)
        self.box.pack_start(bottom, False, False, 0)
        self.box.show_all()

    def _type(self, code, mods, label):
        mods = list(mods)
        if (self.shift or self.caps) and not self.symbols and label.isalpha():
            mods.append("shift")
        self.send(code, *mods)
        if self.shift and not self.caps:
            self.shift = False
            self._build()

    def _toggle_shift(self):
        # one tap: next letter upper case; two taps: caps lock; third: off
        if self.caps:
            self.caps = self.shift = False
        elif self.shift:
            self.caps = True
        else:
            self.shift = True
        self._build()

    def _toggle_symbols(self):
        self.symbols = not self.symbols
        self._build()

    # -- show/hide ----------------------------------------------------------------------

    def toggle(self):
        if self.get_visible():
            self.hide_keyboard()
        else:
            self.show_keyboard()

    def show_keyboard(self):
        self.shift = self.caps = self.symbols = False
        self._build()
        if self.shell.current_monitor is not None:
            self.set_monitor(self.shell.current_monitor)
        self.show_all()
        self._ensure_helper()

    def hide_keyboard(self):
        self.hide()

    def _on_settings(self, _settings, keys):
        if keys & {"input.keyboard_layouts", "input.keyboard_variant"}:
            self._stop_helper()
            if self.get_visible():
                self._build()

