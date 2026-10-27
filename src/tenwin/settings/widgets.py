"""Windows 10 Settings style building blocks."""

import shutil

from gi.repository import GLib, Gtk, Pango

from tenwin.config import get_settings
from tenwin.gtkutil import add_class, flat_button, icon_image
from tenwin.i18n import _
from tenwin.services import system


class Page(Gtk.Box):
    """Vertical page with a title; helpers append Win10 style controls."""

    def __init__(self, title):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        add_class(self, "tw-set-page")
        self.set_margin_start(32)
        self.set_margin_end(32)
        self.set_margin_top(18)
        self.set_margin_bottom(32)
        self.set_halign(Gtk.Align.START)
        self.set_size_request(560, -1)
        self.pack_start(add_class(Gtk.Label(label=title, xalign=0), "tw-h1"), False, False, 6)
        self.settings = get_settings()

    def add(self, widget, spacing=0):
        self.pack_start(widget, False, False, spacing)
        return widget

    def section(self, title):
        return self.add(add_class(Gtk.Label(label=title, xalign=0), "tw-h2", "tw-set-section"), 10)

    def text(self, text, dim=True):
        label = Gtk.Label(label=text, xalign=0, wrap=True)
        label.set_max_width_chars(70)
        label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        if dim:
            add_class(label, "tw-dim")
        return self.add(label)

    def caption(self, text):
        return self.add(add_class(Gtk.Label(label=text, xalign=0), "tw-set-caption"), 4)

    def toggle(self, title, key=None, getter=None, setter=None, description=None):
        """A Win10 toggle: caption, then switch + 'On'/'Off'."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.pack_start(add_class(Gtk.Label(label=title, xalign=0), "tw-set-caption"), False, False, 0)
        if description:
            desc = add_class(Gtk.Label(label=description, xalign=0, wrap=True), "tw-dim")
            desc.set_max_width_chars(70)
            box.pack_start(desc, False, False, 0)
        row = Gtk.Box(spacing=10)
        switch = Gtk.Switch()
        state = Gtk.Label(xalign=0)
        value = bool(self.settings[key]) if key else bool(getter() if getter else False)
        switch.set_active(value)
        state.set_text(_("On") if value else _("Off"))

        def changed(sw, _pspec):
            on = sw.get_active()
            state.set_text(_("On") if on else _("Off"))
            if key:
                self.settings.set(key, on)
            if setter:
                setter(on)

        switch.connect("notify::active", changed)
        row.pack_start(switch, False, False, 0)
        row.pack_start(state, False, False, 0)
        box.pack_start(row, False, False, 0)
        self.add(box, 6)
        return switch

    def check(self, title, key=None, getter=None, setter=None):
        button = Gtk.CheckButton(label=title)
        button.set_active(bool(self.settings[key]) if key else bool(getter()))

        def toggled(b):
            if key:
                self.settings.set(key, b.get_active())
            if setter:
                setter(b.get_active())

        button.connect("toggled", toggled)
        return self.add(button, 2)

    def combo(self, title, options, key=None, getter=None, setter=None, width=260):
        """options: list of (value, label)."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        if title:
            box.pack_start(add_class(Gtk.Label(label=title, xalign=0), "tw-set-caption"), False, False, 0)
        combo = Gtk.ComboBoxText()
        combo.set_size_request(width, -1)
        combo.set_halign(Gtk.Align.START)
        for value, label in options:
            combo.append(str(value), label)
        current = self.settings[key] if key else (getter() if getter else None)
        if current is not None:
            combo.set_active_id(str(current))

        def changed(c):
            value_id = c.get_active_id()
            if value_id is None:
                return
            value = next((v for v, _l in options if str(v) == value_id), value_id)
            if key:
                self.settings.set(key, value)
            if setter:
                setter(value)

        combo.connect("changed", changed)
        box.pack_start(combo, False, False, 0)
        self.add(box, 6)
        return combo

    def slider(self, title, lo, hi, step, key=None, getter=None, setter=None, fmt=None, width=300):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        if title:
            box.pack_start(add_class(Gtk.Label(label=title, xalign=0), "tw-set-caption"), False, False, 0)
        row = Gtk.Box(spacing=10)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
        scale.set_size_request(width, -1)
        scale.set_draw_value(False)
        value_label = Gtk.Label()
        current = self.settings[key] if key else (getter() if getter else lo)
        scale.set_value(current)
        value_label.set_text(fmt(current) if fmt else str(int(current)))
        pending = {"id": 0}

        def changed(s):
            value = s.get_value()
            value_label.set_text(fmt(value) if fmt else str(int(round(value))))
            if pending["id"]:
                GLib.source_remove(pending["id"])

            def commit():
                pending["id"] = 0
                v = int(round(value)) if float(step).is_integer() else round(value, 2)
                if key:
                    self.settings.set(key, v)
                if setter:
                    setter(v)
                return False
            pending["id"] = GLib.timeout_add(200, commit)

        scale.connect("value-changed", changed)
        row.pack_start(scale, False, False, 0)
        row.pack_start(value_label, False, False, 0)
        box.pack_start(row, False, False, 0)
        self.add(box, 6)
        return scale

    def radios(self, title, options, key=None, getter=None, setter=None):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        if title:
            box.pack_start(add_class(Gtk.Label(label=title, xalign=0), "tw-set-caption"), False, False, 0)
        current = self.settings[key] if key else (getter() if getter else None)
        group = None
        for value, label in options:
            radio = Gtk.RadioButton.new_with_label_from_widget(group, label)
            group = group or radio
            radio.set_active(value == current)

            def toggled(r, v=value):
                if not r.get_active():
                    return
                if key:
                    self.settings.set(key, v)
                if setter:
                    setter(v)

            radio.connect("toggled", toggled)
            box.pack_start(radio, False, False, 0)
        self.add(box, 6)
        return box

    def link(self, text, callback):
        button = flat_button(Gtk.Label(label=text, xalign=0), "tw-link")
        button.set_halign(Gtk.Align.START)
        button.connect("clicked", lambda *_: callback())
        return self.add(button, 2)

    def button(self, text, callback, accent=False):
        button = Gtk.Button(label=text)
        add_class(button, "tw-accent-button" if accent else "tw-gray-button")
        button.set_halign(Gtk.Align.START)
        button.connect("clicked", lambda *_: callback())
        return self.add(button, 6)

    def tool_link(self, text, *commands):
        """Link that starts the first installed external tool."""
        for argv in commands:
            if shutil.which(argv[0]):
                return self.link(text, lambda a=argv: system.run(a))
        return None

    def info_rows(self, rows):
        grid = Gtk.Grid(column_spacing=28, row_spacing=8)
        for i, (label, value) in enumerate(rows):
            grid.attach(add_class(Gtk.Label(label=label, xalign=0, yalign=0), "tw-dim"), 0, i, 1, 1)
            val = Gtk.Label(label=value, xalign=0, selectable=True, wrap=True)
            val.set_max_width_chars(48)
            grid.attach(val, 1, i, 1, 1)
        return self.add(grid, 4)


def nav_row(icon, title):
    row = Gtk.ListBoxRow()
    box = add_class(Gtk.Box(spacing=16), "tw-set-nav-row")
    box.pack_start(icon_image(icon, 16, symbolic=True), False, False, 0)
    box.pack_start(Gtk.Label(label=title, xalign=0), True, True, 0)
    row.add(box)
    return row
