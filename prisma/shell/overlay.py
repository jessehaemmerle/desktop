"""Vollflächige, transparente Layer-Fenster für Kompass und Panels.

Ein Klick außerhalb der Karte oder Escape schließt das Overlay.
"""

from __future__ import annotations

from gi.repository import Gdk, GLib, Gtk

from . import util


class Overlay:
    def __init__(self, app, name: str, *, layer: str = "top", cover_bars: bool = False,
                 halign=Gtk.Align.CENTER, valign=Gtk.Align.START, margins: dict | None = None,
                 dim: bool = False, keyboard: str = "exclusive",
                 transition=Gtk.RevealerTransitionType.SLIDE_DOWN):
        self.app = app
        self.keyboard = keyboard
        self.window = util.layer_window(app, name, layer=layer, anchors=("top", "bottom", "left", "right"),
                                        exclusive=-1 if cover_bars else 0, keyboard="none")
        self.events = Gtk.EventBox()
        self.events.set_above_child(False)
        self.backdrop = Gtk.Box()
        if dim:
            util.add_class(self.backdrop, "backdrop")
        # Kein Gtk.Revealer: der würde den Kartenschatten abschneiden. Animation per CSS-Klasse.
        self.holder = Gtk.Box()
        self.holder.set_halign(halign)
        self.holder.set_valign(valign)
        self.holder.set_hexpand(True)
        for edge, value in (margins or {}).items():
            getattr(self.holder, f"set_margin_{edge}")(value)
        self.card = util.add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "card", "overlay-card")
        if transition == Gtk.RevealerTransitionType.CROSSFADE:
            util.add_class(self.card, "fade-only")
        self.holder.pack_start(self.card, True, True, 0)
        self.backdrop.pack_start(self.holder, True, True, 0)
        self.events.add(self.backdrop)
        self.window.add(self.events)
        self.events.connect("button-press-event", self._on_press)
        self.window.connect("key-press-event", self._on_key)
        self._hide_source = 0
        self.visible = False
        self.on_visibility = None  # Callback(overlay, sichtbar)

    def _on_press(self, _widget, event) -> bool:
        alloc = self.card.get_allocation()
        ok, x, y = self.card.translate_coordinates(self.events, 0, 0)
        inside = ok and x <= event.x <= x + alloc.width and y <= event.y <= y + alloc.height
        if not inside:
            self.hide()
            return True
        return False

    def _on_key(self, _widget, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.hide()
            return True
        return self.on_key(event)

    def on_key(self, event) -> bool:  # für Unterklassen
        return False

    def on_show(self) -> None:  # für Unterklassen
        pass

    def show(self) -> None:
        if self._hide_source:
            GLib.source_remove(self._hide_source)
            self._hide_source = 0
        self.visible = True
        util.set_keyboard(self.window, self.keyboard)
        self.window.show_all()
        self.on_show()
        GLib.timeout_add(16, lambda: util.add_class(self.card, "shown") and False)
        util.add_class(self.backdrop, "shown")
        self.window.present()
        if self.on_visibility:
            self.on_visibility(self, True)

    def hide(self) -> None:
        if not self.visible:
            return
        self.visible = False
        util.toggle_class(self.card, "shown", False)
        util.toggle_class(self.backdrop, "shown", False)
        util.set_keyboard(self.window, "none")
        if self.on_visibility:
            self.on_visibility(self, False)
        self._hide_source = GLib.timeout_add(210, self._finish_hide)

    def _finish_hide(self) -> bool:
        self._hide_source = 0
        if not self.visible:
            self.window.hide()
        return False

    def toggle(self) -> None:
        if self.visible:
            self.hide()
        else:
            self.show()
