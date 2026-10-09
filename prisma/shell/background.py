"""Generativer „Prisma“-Hintergrund: Lichtfelder in der Facettenfarbe, weich überblendet."""

from __future__ import annotations

import math
import os
import time
from datetime import datetime

import cairo
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango, PangoCairo

from ..core import colors, schedule
from ..core.theme import wallpaper_stops
from . import util
from .dates import long_date

FADE_SECONDS = 0.9


def _rgb(hex_color: str):
    return colors.hex_to_rgb(hex_color)


def draw_scene(cr, width: int, height: int, stops: dict) -> None:
    gradient = cairo.LinearGradient(0, 0, width * 0.3, height)
    gradient.add_color_stop_rgb(0, *_rgb(stops["top"]))
    gradient.add_color_stop_rgb(1, *_rgb(stops["bottom"]))
    cr.set_source(gradient)
    cr.paint()

    size = max(width, height)
    fields = ((0.18, 0.22, 0.75), (0.86, 0.30, 0.65), (0.55, 1.05, 0.80))
    for (fx, fy, radius), color, strength in zip(fields, stops["glow"], stops["strength"]):
        r, g, b = _rgb(color)
        radial = cairo.RadialGradient(width * fx, height * fy, 0, width * fx, height * fy, size * radius)
        radial.add_color_stop_rgba(0, r, g, b, strength)
        radial.add_color_stop_rgba(0.55, r, g, b, strength * 0.35)
        radial.add_color_stop_rgba(1, r, g, b, 0)
        cr.set_source(radial)
        cr.paint()

    # Zwei weiche Lichtbahnen – das „Prisma“
    for offset, alpha in ((0.0, 0.06), (0.09, 0.04)):
        cr.save()
        beam = cairo.LinearGradient(0, 0, width, height)
        beam.add_color_stop_rgba(0, 1, 1, 1, 0)
        beam.add_color_stop_rgba(0.5, 1, 1, 1, alpha)
        beam.add_color_stop_rgba(1, 1, 1, 1, 0)
        cr.move_to(width * (0.30 + offset), 0)
        cr.line_to(width * (0.42 + offset), 0)
        cr.line_to(width * (0.78 + offset), height)
        cr.line_to(width * (0.58 + offset), height)
        cr.close_path()
        cr.set_source(beam)
        cr.fill()
        cr.restore()


class Background:
    def __init__(self, app, hub, monitor: Gdk.Monitor):
        self.hub = hub
        self.window = util.layer_window(app, "background", layer="background",
                                        anchors=("top", "bottom", "left", "right"), exclusive=-1, monitor=monitor)
        self.area = Gtk.DrawingArea()
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.area.connect("draw", self._draw)
        self.area.connect("button-press-event", self._clicked)
        self.window.add(self.area)
        self._current = self._stops()
        self._previous = None
        self._fade_start = 0.0
        self._image_cache: tuple | None = None
        self._handlers = [
            hub.connect("theme-changed", lambda *_: self._crossfade()),
            hub.connect("config-changed", lambda *_: self.area.queue_draw()),
            hub.connect("focus-changed", lambda *_: self._focus_changed()),
        ]
        self._phase = hub.focus.phase
        self._minute = GLib.timeout_add_seconds(60, lambda: self.area.queue_draw() or True)
        self.window.show_all()

    def destroy(self) -> None:
        for handler in self._handlers:
            self.hub.disconnect(handler)
        GLib.source_remove(self._minute)
        self.window.destroy()

    def _focus_changed(self) -> None:
        # Nur beim Phasenwechsel neu zeichnen, nicht bei jedem Sekundentick.
        if self.hub.focus.phase != self._phase:
            self._phase = self.hub.focus.phase
            self.area.queue_draw()

    def _stops(self) -> dict:
        return wallpaper_stops(self.hub.facet["color"], self.hub.dark)

    def _crossfade(self) -> None:
        new = self._stops()
        if new == self._current:
            self.area.queue_draw()
            return
        self._previous, self._current = self._current, new
        self._fade_start = time.monotonic()
        GLib.timeout_add(16, self._animate)

    def _animate(self) -> bool:
        self.area.queue_draw()
        if time.monotonic() - self._fade_start >= FADE_SECONDS:
            self._previous = None
            return False
        return True

    def _clicked(self, _widget, event) -> bool:
        if event.button == 3:
            self.hub.app.activate_action("kompass", None)
            return True
        return False

    # ------------------------------------------------------------- Zeichnen
    def _wallpaper(self, width: int, height: int):
        path = self.hub.facet.get("wallpaper")
        if not path:
            return None
        path = os.path.expanduser(path)
        key = (path, width, height)
        if self._image_cache and self._image_cache[0] == key:
            return self._image_cache[1]
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
        except GLib.Error:
            self._image_cache = (key, None)
            return None
        scale = max(width / pixbuf.get_width(), height / pixbuf.get_height())
        w, h = math.ceil(pixbuf.get_width() * scale), math.ceil(pixbuf.get_height() * scale)
        scaled = pixbuf.scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR)
        self._image_cache = (key, (scaled, (width - w) / 2, (height - h) / 2))
        return self._image_cache[1]

    def _draw(self, widget, cr) -> bool:
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        image = self._wallpaper(width, height)
        if image is not None:
            pixbuf, x, y = image
            Gdk.cairo_set_source_pixbuf(cr, pixbuf, x, y)
            cr.paint()
        else:
            if self._previous is not None:
                draw_scene(cr, width, height, self._previous)
                progress = min(1.0, (time.monotonic() - self._fade_start) / FADE_SECONDS)
                eased = 1 - (1 - progress) ** 3
                cr.push_group()
                draw_scene(cr, width, height, self._current)
                cr.pop_group_to_source()
                cr.paint_with_alpha(eased)
            else:
                draw_scene(cr, width, height, self._current)
        if self.hub.config["appearance"].get("greeting", True):
            self._draw_greeting(widget, cr, width, height, on_image=image is not None)
        return False

    def _draw_greeting(self, widget, cr, width: int, height: int, on_image: bool) -> None:
        now = datetime.now()
        light_text = self.hub.dark or on_image
        fg = (1, 1, 1) if light_text else (0.08, 0.09, 0.12)
        accent = _rgb(colors.lighten(self.hub.facet["color"], 0.35) if light_text else colors.darken(self.hub.facet["color"], 0.2))
        x = 56
        base_y = height - 150

        def text(markup_text: str, font: str, rgb, alpha: float, y: float) -> float:
            layout = PangoCairo.create_layout(cr)
            layout.set_font_description(Pango.FontDescription.from_string(font))
            layout.set_text(markup_text, -1)
            _ink, logical = layout.get_pixel_extents()
            top = y - logical.height
            if on_image:
                cr.set_source_rgba(0, 0, 0, 0.35)
                cr.move_to(x + 1, top + 2)
                PangoCairo.show_layout(cr, layout)
            cr.set_source_rgba(*rgb, alpha)
            cr.move_to(x, top)
            PangoCairo.show_layout(cr, layout)
            return top

        y = text(long_date(now), "Inter 15", fg, 0.72, base_y)
        y = text(schedule.greeting(now, self.hub.user_name()), "Inter Display Bold 40", fg, 0.92, y - 2)
        label = self.hub.facet["name"].upper()
        if self.hub.in_focus:
            label += "  ·  FOKUS"
        text(label, "Inter Heavy 12", accent, 0.95, y - 6)


class Backgrounds:
    """Ein Hintergrund pro Monitor – reagiert auf an-/abgesteckte Bildschirme."""

    def __init__(self, app, hub):
        self.app, self.hub = app, hub
        self.items: list[Background] = []
        display = Gdk.Display.get_default()
        display.connect("monitor-added", lambda *_: GLib.idle_add(self.rebuild))
        display.connect("monitor-removed", lambda *_: GLib.idle_add(self.rebuild))
        self.rebuild()

    def rebuild(self) -> bool:
        for item in self.items:
            item.destroy()
        display = Gdk.Display.get_default()
        self.items = [Background(self.app, self.hub, display.get_monitor(i)) for i in range(display.get_n_monitors())]
        return False
