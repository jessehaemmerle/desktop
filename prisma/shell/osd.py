"""Bildschirmanzeige für Lautstärke/Helligkeit und kurze Hinweise („Toasts“)."""

from __future__ import annotations

from gi.repository import GLib, Gtk

from . import util

HIDE_MS = 1600


class Osd:
    def __init__(self, app):
        self.window = util.layer_window(app, "osd", layer="overlay", anchors=("bottom",), margins={"bottom": 96})
        self.revealer = Gtk.Revealer()
        self.revealer.set_transition_type(Gtk.RevealerTransitionType.CROSSFADE)
        self.revealer.set_transition_duration(180)
        box = util.add_class(Gtk.Box(spacing=12), "island", "osd")
        box.set_margin_start(20)
        box.set_margin_end(20)
        box.set_margin_bottom(20)
        self.image = util.icon_image("audio-volume-high-symbolic", 20)
        self.level = Gtk.LevelBar()
        self.level.set_min_value(0)
        self.level.set_max_value(1)
        self.level.set_size_request(180, -1)
        self.level.set_valign(Gtk.Align.CENTER)
        self.text = util.label("", "tile-title")
        self.value = util.label("", "osd-value", xalign=1.0)
        for widget in (self.image, self.level, self.text, self.value):
            box.pack_start(widget, widget is self.level or widget is self.text, True, 0)
        self.revealer.add(box)
        self.window.add(self.revealer)
        self._source = 0

    def show_level(self, icon: str, fraction: float) -> None:
        util.set_icon(self.image, icon, 20)
        self.level.set_value(max(0.0, min(1.0, fraction)))
        self.value.set_text(f"{round(fraction * 100)}")
        self._present(level=True)

    def toast(self, icon: str, text: str) -> None:
        util.set_icon(self.image, icon, 20, "dialog-information-symbolic")
        self.text.set_text(text)
        self._present(level=False)

    def _present(self, level: bool) -> None:
        self.window.show_all()
        self.level.set_visible(level)
        self.value.set_visible(level)
        self.text.set_visible(not level)
        self.window.resize(1, 1)
        self.revealer.set_reveal_child(True)
        if self._source:
            GLib.source_remove(self._source)
        self._source = GLib.timeout_add(HIDE_MS if level else HIDE_MS + 900, self._hide)

    def _hide(self) -> bool:
        self._source = 0
        self.revealer.set_reveal_child(False)
        GLib.timeout_add(200, lambda: (self.window.hide() if not self._source else None) and False)
        return False
