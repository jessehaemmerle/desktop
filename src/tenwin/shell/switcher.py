"""Alt+Tab, Task View (Win+Tab) and detection of a lone Win key press.

labwc 0.7 cannot bind key releases, so the shell grabs the keyboard with an
(invisible) layer surface and watches the modifier state until the modifier
is released. See docs/adr/0001-architektur.md.
"""

from gi.repository import Gdk, GLib, Gtk, Pango

from tenwin.gtkutil import add_class, clear_children, flat_button, icon_image, set_class
from tenwin.i18n import _
from tenwin.shell.layer import Edge, Layer, LayerWindow

ALL_EDGES = (Edge.TOP, Edge.BOTTOM, Edge.LEFT, Edge.RIGHT)


def modifier_held(mask):
    keymap = Gdk.Keymap.get_for_display(Gdk.Display.get_default())
    return bool(keymap.get_modifier_state() & mask)


class ModifierWatcher:
    """Calls ``on_release`` once ``mask`` is no longer held by the user.

    The modifier state is only reliable once our surface has keyboard focus,
    so the owner calls :meth:`focused` from its focus-in handler.
    """

    def __init__(self, mask, on_release):
        self.mask = mask
        self.on_release = on_release
        self.active = False
        self._sid = 0
        self._check_id = 0
        self._fallback_id = 0
        self._keymap = Gdk.Keymap.get_for_display(Gdk.Display.get_default())

    def start(self, fallback_ms=600):
        self.stop()
        self.active = True
        self._sid = self._keymap.connect("state-changed", self._check)
        self._fallback_id = GLib.timeout_add(fallback_ms, self._on_fallback)

    def focused(self):
        if self.active and not self._check_id:
            self._check_id = GLib.timeout_add(30, self._on_check)

    def stop(self):
        self.active = False
        if self._sid:
            self._keymap.disconnect(self._sid)
            self._sid = 0
        for attr in ("_check_id", "_fallback_id"):
            tid = getattr(self, attr)
            if tid:
                GLib.source_remove(tid)
                setattr(self, attr, 0)

    def _on_check(self):
        self._check_id = 0
        self._check()
        return GLib.SOURCE_REMOVE

    def _on_fallback(self):
        # Without keyboard focus we may never learn about the release.
        self._fallback_id = 0
        self._check()
        return GLib.SOURCE_REMOVE

    def _check(self, *_args):
        if self.active and not modifier_held(self.mask):
            self.stop()
            self.on_release()


class SuperKey(LayerWindow):
    """Invisible 1×1 surface that waits for the Win key to be released."""

    def __init__(self, shell):
        super().__init__("tenwin-superkey", layer=Layer.OVERLAY, anchors=(Edge.TOP, Edge.LEFT),
                         keyboard="exclusive")
        self.shell = shell
        self.set_size_request(1, 1)
        self.connect("draw", self._draw)
        self.connect("key-press-event", self._on_key)
        self.watcher = ModifierWatcher(Gdk.ModifierType.MOD4_MASK | Gdk.ModifierType.SUPER_MASK,
                                       self._released)
        self.connect("focus-in-event", lambda *_: self.watcher.focused() or False)
        self.pending = False

    def _draw(self, _widget, cr):
        cr.set_operator(0)
        cr.paint()
        return True

    def press(self):
        if self.shell.start_menu.is_open():
            self.shell.start_menu.close_popup()
            return
        self.pending = True
        self.show_all()
        self.watcher.start()

    def cancel(self):
        if self.pending:
            self.pending = False
            self.watcher.stop()
            self.hide()

    def _released(self):
        if not self.pending:
            return
        self.pending = False
        self.hide()
        self.shell.toggle_popup(self.shell.start_menu)

    def _on_key(self, _widget, event):
        # Any other key while Win is held is a shortcut, not a Start press.
        if event.keyval not in (Gdk.KEY_Super_L, Gdk.KEY_Super_R, Gdk.KEY_Meta_L, Gdk.KEY_Meta_R):
            self.cancel()
        return True


def window_card(shell, window, thumb_size, on_click, on_close=None):
    info = shell.apps.for_window(window.app_id)
    icon = info.get_icon() if info is not None else None
    title = window.title or (info.get_display_name() if info else window.app_id)
    button = flat_button(css="tw-switch-card")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    head = Gtk.Box(spacing=6)
    head.pack_start(icon_image(icon, 16), False, False, 0)
    label = add_class(Gtk.Label(label=title, xalign=0), "tw-switch-title")
    label.set_ellipsize(Pango.EllipsizeMode.END)
    label.set_max_width_chars(28)
    head.pack_start(label, True, True, 0)
    close = None
    if on_close is not None:
        close = flat_button(icon_image("tenwin-close", 12, symbolic=True), "tw-card-close", _("Close"))
        close.connect("clicked", lambda *_: on_close(window))
        close.set_opacity(0.0)
        head.pack_end(close, False, False, 0)
    box.pack_start(head, False, False, 0)
    thumb = add_class(Gtk.Box(), "tw-switch-thumb")
    thumb.set_size_request(*thumb_size)
    big = icon_image(icon, 96 if thumb_size[0] > 220 else 64)
    big.set_valign(Gtk.Align.CENTER)
    thumb.pack_start(big, True, True, 0)
    box.pack_start(thumb, False, False, 0)
    button.add(box)
    button.connect("clicked", lambda *_: on_click(window))
    if close is not None:
        button.connect("enter-notify-event", lambda *_: close.set_opacity(1.0) or False)
        button.connect("leave-notify-event", lambda *_: close.set_opacity(0.0) or False)
    return button


class AltTab(LayerWindow):
    def __init__(self, shell):
        super().__init__("tenwin-alttab", layer=Layer.OVERLAY, anchors=(), keyboard="exclusive")
        self.shell = shell
        self.windows = []
        self.cards = []
        self.index = 0
        self.flow = Gtk.FlowBox(homogeneous=True)
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow.set_max_children_per_line(6)
        self.flow.set_min_children_per_line(1)
        frame = add_class(Gtk.Box(), "tw-switcher")
        frame.pack_start(self.flow, True, True, 0)
        self.add(frame)
        self.connect("key-press-event", self._on_key)
        self.watcher = ModifierWatcher(Gdk.ModifierType.MOD1_MASK, self._commit)
        self.connect("focus-in-event", lambda *_: self.watcher.focused() or False)

    @property
    def active(self):
        return self.get_visible()

    def step(self, delta):
        if not self.active:
            self.windows = self.shell.wm.list(mru=True)
            if len(self.windows) < 1:
                return
            self.index = 0
            self._build()
            self.show_all()
            self.watcher.start(fallback_ms=1500)
        self.index = (self.index + delta) % len(self.windows)
        self._highlight()

    def _build(self):
        clear_children(self.flow)
        self.cards = []
        for window in self.windows:
            card = window_card(self.shell, window, (200, 130), self._choose)
            self.cards.append(card)
            self.flow.add(card)
        per_line = min(6, max(1, len(self.windows)))
        self.flow.set_max_children_per_line(per_line)
        self.flow.set_min_children_per_line(per_line)

    def _highlight(self):
        for i, card in enumerate(self.cards):
            set_class(card, "selected", i == self.index)

    def _choose(self, window):
        self.index = self.windows.index(window)
        self._commit()

    def _commit(self):
        self.watcher.stop()
        target = self.windows[self.index] if self.windows else None
        self.hide()
        if target is not None:
            self.shell.wm.activate(target)

    def cancel(self):
        self.watcher.stop()
        self.hide()

    def _on_key(self, _widget, event):
        key = event.keyval
        if key == Gdk.KEY_Escape:
            self.cancel()
        elif key in (Gdk.KEY_Right, Gdk.KEY_Tab):
            self.step(1)
        elif key in (Gdk.KEY_Left, Gdk.KEY_ISO_Left_Tab):
            self.step(-1)
        elif key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._commit()
        elif key == Gdk.KEY_Delete and self.windows:
            self.shell.wm.close(self.windows[self.index])
        return True


class TaskView(LayerWindow):
    def __init__(self, shell):
        super().__init__("tenwin-taskview", layer=Layer.OVERLAY, anchors=ALL_EDGES, keyboard="exclusive")
        self.shell = shell
        self.cards = []
        self.windows = []
        self.index = 0
        root = add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "tw-taskview")
        self.add(root)
        self.events = Gtk.EventBox()
        self.events.connect("button-release-event", self._on_background)
        root.pack_start(self.events, True, True, 0)
        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        center.set_valign(Gtk.Align.CENTER)
        center.set_halign(Gtk.Align.CENTER)
        self.events.add(center)
        self.flow = Gtk.FlowBox(homogeneous=True, column_spacing=24, row_spacing=24)
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow.set_max_children_per_line(4)
        self.flow.set_halign(Gtk.Align.CENTER)
        center.pack_start(self.flow, False, False, 0)
        self.empty = add_class(Gtk.Label(label=_("No open windows")), "tw-taskview-empty")
        center.pack_start(self.empty, False, False, 0)
        strip = add_class(Gtk.Box(), "tw-desktop-strip")
        hint = add_class(Gtk.Label(label=_("Switch desktops: Ctrl+Win+Left/Right · "
                                           "Move window: Ctrl+Win+Shift+Left/Right")), "tw-taskview-hint")
        strip.pack_start(hint, True, True, 0)
        root.pack_end(strip, False, False, 0)
        self.connect("key-press-event", self._on_key)

    def toggle(self):
        if self.get_visible():
            self.hide()
        else:
            self.open()

    def open(self):
        self.shell.close_popups()
        self.shell.notifications.hide_toasts()
        clear_children(self.flow)
        self.windows = self.shell.wm.list(mru=True)
        self.cards = [window_card(self.shell, w, (280, 180), self._activate, self._close) for w in self.windows]
        for card in self.cards:
            self.flow.add(card)
        self.flow.set_min_children_per_line(min(4, max(1, len(self.cards))))
        self.empty.set_visible(not self.windows)
        self.empty.set_no_show_all(True)
        self.index = 0
        if self.shell.current_monitor is not None:
            self.set_monitor(self.shell.current_monitor)
        self.show_all()
        self._highlight()

    def _highlight(self):
        for i, card in enumerate(self.cards):
            set_class(card, "selected", i == self.index)

    def _activate(self, window):
        self.hide()
        self.shell.wm.activate(window)

    def _close(self, window):
        self.shell.wm.close(window)
        GLib.timeout_add(250, lambda: self.get_visible() and self.open() and False)

    def _on_background(self, _widget, event):
        if event.button == 1:
            self.hide()
        return False

    def _on_key(self, _widget, event):
        key = event.keyval
        if key == Gdk.KEY_Escape:
            self.hide()
        elif not self.windows:
            return True
        elif key in (Gdk.KEY_Right, Gdk.KEY_Tab):
            self.index = (self.index + 1) % len(self.windows)
            self._highlight()
        elif key in (Gdk.KEY_Left, Gdk.KEY_ISO_Left_Tab):
            self.index = (self.index - 1) % len(self.windows)
            self._highlight()
        elif key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            self._activate(self.windows[self.index])
        elif key == Gdk.KEY_Delete:
            self._close(self.windows[self.index])
        return True
