"""Kompass – eine einzige Eingabe für Apps, Dateien, Rechnen, Facetten, Befehle und mehr."""

from __future__ import annotations

from gi.repository import Gdk, Gtk

from ..core import colors
from . import util
from .overlay import Overlay
from .providers import PREFIXES, Providers


def facet_badge(facet: dict) -> Gtk.Widget:
    """Farbiges Quadrat mit Anfangsbuchstaben – unabhängig vom Icon-Thema."""
    badge = util.label(facet["name"][:1].upper(), "facet-badge", xalign=0.5)
    badge.set_valign(Gtk.Align.CENTER)
    css = Gtk.CssProvider()
    fg = colors.readable_on(facet["color"])
    css.load_from_data(f"label {{ background-color: {facet['color']}; color: {fg}; }}".encode())
    badge.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_USER + 20)
    return badge


class ResultRow(Gtk.ListBoxRow):
    def __init__(self, result):
        super().__init__()
        self.result = result
        util.add_class(self, "kompass-row")
        box = Gtk.Box(spacing=12)
        glyph = result.extra.get("glyph")
        facet = result.extra.get("facet")
        if glyph:
            icon = util.label(glyph, "kompass-big", xalign=0.5)
            icon.set_size_request(34, 34)
        elif facet:
            icon = facet_badge(facet)
        else:
            icon = util.icon_image(result.icon, 34 if not result.big else 30)
        box.pack_start(icon, False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        text.set_valign(Gtk.Align.CENTER)
        if glyph:
            title_text = result.title.split("   ", 1)[-1]
        else:
            title_text = result.title
        title = util.label(title_text, "kompass-big" if result.big else "kompass-title", ellipsize=True)
        text.pack_start(title, False, False, 0)
        if result.subtitle:
            text.pack_start(util.label(result.subtitle, "kompass-sub", ellipsize=True), False, False, 0)
        box.pack_start(text, True, True, 0)
        box.pack_end(util.label("↵", "kompass-enter"), False, False, 0)
        box.pack_end(util.label(result.kind, "kompass-kind"), False, False, 0)
        self.add(box)


class Kompass(Overlay):
    def __init__(self, app, hub, services):
        super().__init__(app, "kompass", layer="overlay", cover_bars=True, valign=Gtk.Align.START,
                         margins={"top": 140}, dim=True, keyboard="exclusive",
                         transition=Gtk.RevealerTransitionType.CROSSFADE)
        self.hub = hub
        self.providers = Providers(app, hub, services)
        util.add_class(self.card, "kompass")

        entry_row = util.add_class(Gtk.Box(spacing=10), "kompass-entry-row")
        entry_row.pack_start(util.icon_image("system-search-symbolic", 22), False, False, 0)
        self.entry = Gtk.Entry()
        util.add_class(self.entry, "kompass-entry")
        self.entry.set_placeholder_text("Suchen, rechnen, starten …")
        self.entry.set_has_frame(False)
        self.entry.connect("changed", lambda *_: self.update())
        self.entry.connect("activate", lambda *_: self.activate_selected())
        entry_row.pack_start(self.entry, True, True, 0)
        self.facet_hint = util.label("", "kompass-kind")
        entry_row.pack_end(self.facet_hint, False, False, 0)
        self.card.pack_start(entry_row, False, False, 0)

        self.section = util.label("VORSCHLÄGE", "kompass-section")
        self.card.pack_start(self.section, False, False, 0)
        self.list = Gtk.ListBox()
        util.add_class(self.list, "kompass-list")
        self.list.set_selection_mode(Gtk.SelectionMode.BROWSE)
        self.list.set_activate_on_single_click(True)
        self.list.connect("row-activated", lambda _l, row: self._run(row.result))
        self.card.pack_start(self.list, False, False, 0)
        self.empty = util.label("Nichts gefunden – Enter sucht im Web", "kompass-sub", xalign=0.5)
        self.empty.set_margin_top(18)
        self.empty.set_margin_bottom(18)
        self.card.pack_start(self.empty, False, False, 0)

        footer = util.add_class(Gtk.Box(), "kompass-footer")
        for prefix, title in PREFIXES.items():
            chip = Gtk.Button()
            util.add_class(chip, "chip")
            chip_box = Gtk.Box(spacing=5)
            chip_box.pack_start(util.label(prefix, "chip-key"), False, False, 0)
            chip_box.pack_start(util.label(title), False, False, 0)
            chip.add(chip_box)
            chip.connect("clicked", lambda _b, p=prefix: self._set_prefix(p))
            footer.pack_start(chip, False, False, 0)
        footer.pack_end(util.label("↑↓ wählen  ·  ↵ öffnen  ·  Esc schließen", "kompass-kind"), False, False, 0)
        self.card.pack_start(footer, False, False, 0)

    # ------------------------------------------------------------ Steuerung
    def open(self, text: str = "") -> None:
        self.providers.warm_up()
        self.show()
        self.entry.set_text(text)
        self.entry.set_position(-1)
        self.update()

    def on_show(self) -> None:
        facet = self.hub.facet
        self.facet_hint.set_text(f"◆ {facet['name']}")
        monitor_height = 900
        display = Gdk.Display.get_default()
        monitor = display.get_monitor_at_window(self.window.get_window()) if self.window.get_window() else display.get_monitor(0)
        if monitor is not None:
            monitor_height = monitor.get_geometry().height
        self.holder.set_margin_top(max(60, int(monitor_height * 0.16)))
        self.entry.grab_focus()

    def _set_prefix(self, prefix: str) -> None:
        text = self.entry.get_text()
        if text[:1] in PREFIXES:
            text = text[1:].lstrip()
        self.entry.set_text(f"{prefix} {text}" if text else prefix + " ")
        self.entry.grab_focus()
        self.entry.set_position(-1)

    def update(self) -> None:
        text = self.entry.get_text()
        results = self.providers.query(text)
        util.clear(self.list)
        for result in results:
            self.list.add(ResultRow(result))
        self.list.show_all()
        first = self.list.get_row_at_index(0)
        if first is not None:
            self.list.select_row(first)
        self.section.set_visible(not text.strip())
        self.empty.set_visible(not results)
        self.empty.set_no_show_all(True)
        self.list.set_visible(bool(results))

    def on_key(self, event) -> bool:
        key = event.keyval
        if key in (Gdk.KEY_Down, Gdk.KEY_Tab) or (key == Gdk.KEY_n and event.state & Gdk.ModifierType.CONTROL_MASK):
            self._move(1)
            return True
        if key in (Gdk.KEY_Up, Gdk.KEY_ISO_Left_Tab) or (key == Gdk.KEY_p and event.state & Gdk.ModifierType.CONTROL_MASK):
            self._move(-1)
            return True
        if event.state & Gdk.ModifierType.MOD1_MASK and Gdk.KEY_1 <= key <= Gdk.KEY_9:
            row = self.list.get_row_at_index(key - Gdk.KEY_1)
            if row is not None:
                self._run(row.result)
            return True
        return False

    def _move(self, delta: int) -> None:
        row = self.list.get_selected_row()
        index = (row.get_index() if row else -1) + delta
        count = len(self.list.get_children())
        if count:
            target = self.list.get_row_at_index(index % count)
            self.list.select_row(target)
            target.grab_focus()
            self.entry.grab_focus_without_selecting()

    def activate_selected(self) -> None:
        row = self.list.get_selected_row()
        if row is not None:
            self._run(row.result)

    def _run(self, result) -> None:
        if result.action is None:
            return
        if result.key:
            self.hub.frecency.record(result.key)
        if not result.keep_open:
            self.hide()
        result.action()
