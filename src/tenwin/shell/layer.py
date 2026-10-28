"""Layer-shell windows: panels, popups and the invisible click catcher."""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell

from tenwin.config import get_settings
from tenwin.gtkutil import add_class, enable_rgba

Edge = GtkLayerShell.Edge
Layer = GtkLayerShell.Layer
KeyboardMode = getattr(GtkLayerShell, "KeyboardMode", None)


def set_keyboard(window, mode):
    """mode: 'none' | 'exclusive' | 'on_demand' (falls back for old versions)."""
    if KeyboardMode is not None and hasattr(GtkLayerShell, "set_keyboard_mode"):
        value = {"none": KeyboardMode.NONE, "exclusive": KeyboardMode.EXCLUSIVE,
                 "on_demand": getattr(KeyboardMode, "ON_DEMAND", KeyboardMode.EXCLUSIVE)}[mode]
        GtkLayerShell.set_keyboard_mode(window, value)
    else:
        GtkLayerShell.set_keyboard_interactivity(window, mode != "none")


class LayerWindow(Gtk.Window):
    def __init__(self, namespace, layer=Layer.TOP, anchors=(), monitor=None,
                 keyboard="none", exclusive=0, css=None):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        enable_rgba(self)
        self.set_decorated(False)
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, namespace)
        GtkLayerShell.set_layer(self, layer)
        for edge in (Edge.TOP, Edge.BOTTOM, Edge.LEFT, Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, edge in anchors)
        if monitor is not None:
            GtkLayerShell.set_monitor(self, monitor)
        if exclusive == "auto":
            GtkLayerShell.auto_exclusive_zone_enable(self)
        else:
            GtkLayerShell.set_exclusive_zone(self, exclusive)
        set_keyboard(self, keyboard)
        if css:
            add_class(self, *css.split())

    def set_anchors(self, anchors):
        for edge in (Edge.TOP, Edge.BOTTOM, Edge.LEFT, Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, edge in anchors)

    def set_margins(self, top=0, bottom=0, left=0, right=0):
        GtkLayerShell.set_margin(self, Edge.TOP, top)
        GtkLayerShell.set_margin(self, Edge.BOTTOM, bottom)
        GtkLayerShell.set_margin(self, Edge.LEFT, left)
        GtkLayerShell.set_margin(self, Edge.RIGHT, right)

    def set_monitor(self, monitor):
        GtkLayerShell.set_monitor(self, monitor)


class ClickCatcher(LayerWindow):
    """Transparent full-screen surface below popups; a click closes them."""

    def __init__(self, on_click):
        super().__init__("tenwin-catcher", layer=Layer.TOP,
                         anchors=(Edge.TOP, Edge.BOTTOM, Edge.LEFT, Edge.RIGHT))
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.TOUCH_MASK)
        self.connect("draw", self._draw)
        self.connect("button-press-event", lambda *_: on_click() or True)
        self.connect("touch-event", lambda *_: on_click() or True)

    def _draw(self, _widget, cr):
        cr.set_source_rgba(0, 0, 0, 0)
        cr.set_operator(0)  # CAIRO_OPERATOR_CLEAR
        cr.paint()
        return False


class Popup(LayerWindow):
    """A flyout (Start menu, Info-Center, …). Only one is open at a time."""

    manager = None  # set by the shell: has .popup_opened(p) / .popup_closed(p)

    def __init__(self, namespace, anchors, keyboard="exclusive", css="tw-popup", catch_clicks=True):
        super().__init__(namespace, layer=Layer.OVERLAY, anchors=anchors, keyboard=keyboard, css=css)
        self.catch_clicks = catch_clicks
        self.connect("key-press-event", self._on_key)
        self.connect("delete-event", lambda *_: self.close_popup() or True)
        self._anim_id = 0

    def _on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close_popup()
            return True
        return False

    def is_open(self):
        return self.get_visible()

    def open_popup(self, monitor=None):
        if monitor is not None:
            self.set_monitor(monitor)
        if Popup.manager:
            Popup.manager.popup_opened(self)
        self.on_open()
        self.show_all()
        self.present()
        self.after_show()

    def close_popup(self):
        if not self.get_visible():
            return
        self.hide()
        self.on_close()
        if Popup.manager:
            Popup.manager.popup_closed(self)

    def toggle_popup(self, monitor=None):
        if self.is_open():
            self.close_popup()
        else:
            self.open_popup(monitor)

    # hooks
    def on_open(self):
        pass

    def after_show(self):
        pass

    def on_close(self):
        pass


def taskbar_height():
    settings = get_settings()
    if settings["tablet.mode"]:
        return 48  # bigger touch targets
    return 30 if settings["taskbar.small_icons"] else 40


def taskbar_edge():
    return Edge.TOP if get_settings()["taskbar.position"] == "top" else Edge.BOTTOM


def idle(func, *args):
    GLib.idle_add(lambda: func(*args) and False)
