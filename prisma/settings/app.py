"""Prisma-Einstellungen – bearbeitet ``~/.config/prisma/config.json``; die Shell übernimmt Änderungen sofort."""

from __future__ import annotations

import copy
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .. import APP_ID, __version__  # noqa: E402
from ..core import config as cfg  # noqa: E402
from ..core import schedule  # noqa: E402

POLICIES = [("all", "Alle anzeigen"), ("important", "Nur Wichtiges"), ("silent", "Stumm (nur sammeln)")]
MODES = [("auto", "Automatisch nach Tageszeit"), ("light", "Immer hell"), ("dark", "Immer dunkel")]
DAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
FACET_ICONS = ["x-office-document-symbolic", "computer-symbolic", "applications-graphics-symbolic", "face-smile-symbolic",
               "applications-games-symbolic", "emblem-documents-symbolic", "media-optical-symbolic",
               "applications-science-symbolic", "applications-engineering-symbolic", "user-home-symbolic",
               "view-grid-symbolic"]
NEW_FACET_COLORS = ["#2fbf8f", "#f2c94c", "#ef5b7d", "#29b6d6", "#8c9eff"]
SHORTCUTS = [
    ("Super + Leertaste", "Kompass öffnen"),
    ("Super + 1 … 9", "Zu Facette wechseln"),
    ("Super + Tab", "Nächste Facette"),
    ("Super + Umschalt + 1 … 9", "Aktives Fenster in Facette verschieben"),
    ("Super + A", "Schnelleinstellungen"),
    ("Super + N", "Tagesüberblick und Benachrichtigungen"),
    ("Super + F", "Fokus-Session starten/beenden"),
    ("Super + D", "Nicht stören"),
    ("Super + L", "Bildschirm sperren"),
    ("Super + Eingabe", "Terminal"),
    ("Super + E", "Dateien"),
    ("Super + Q", "Fenster schließen"),
    ("Super + ↑ / ← / →", "Maximieren / links / rechts andocken"),
    ("Alt + Tab", "Fenster wechseln"),
    ("Druck / Umschalt + Druck", "Bildschirmfoto (ganz / Bereich)"),
]


def hex_to_rgba(value: str) -> Gdk.RGBA:
    rgba = Gdk.RGBA()
    rgba.parse(value)
    return rgba


def rgba_to_hex(rgba: Gdk.RGBA) -> str:
    return "#" + "".join(f"{round(c * 255):02x}" for c in (rgba.red, rgba.green, rgba.blue))


def all_apps() -> list[Gio.DesktopAppInfo]:
    apps = [a for a in Gio.AppInfo.get_all() if isinstance(a, Gio.DesktopAppInfo) and a.should_show()]
    return sorted(apps, key=lambda a: a.get_display_name().lower())


class SettingsWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Prisma-Einstellungen")
        self.set_default_size(760, 820)
        self.config = cfg.load()
        self._save_source = 0
        self.apps = all_apps()
        self.toasts = Adw.ToastOverlay()

        self.stack = Adw.ViewStack()
        header = Adw.HeaderBar()
        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)
        about = Gtk.Button(icon_name="help-about-symbolic", tooltip_text="Über Prisma")
        about.connect("clicked", lambda *_: self._about())
        header.pack_end(about)
        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(self.stack)
        bottom = Adw.ViewSwitcherBar(stack=self.stack)
        view.add_bottom_bar(bottom)
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        self.facet_page = Adw.PreferencesPage()
        self.stack.add_titled_with_icon(self.facet_page, "facets", "Facetten", "view-grid-symbolic")
        self.stack.add_titled_with_icon(self._automation_page(), "automation", "Automatik", "alarm-symbolic")
        self.stack.add_titled_with_icon(self._appearance_page(), "appearance", "Darstellung", "applications-graphics-symbolic")
        self.stack.add_titled_with_icon(self._focus_page(), "focus", "Fokus & Kompass", "system-search-symbolic")
        self.stack.add_titled_with_icon(self._shortcuts_page(), "keys", "Tastenkürzel", "input-keyboard-symbolic")
        self._facet_groups: list[Adw.PreferencesGroup] = []
        self._build_facets()

    # ------------------------------------------------------------ Speichern
    def changed(self) -> None:
        if self._save_source:
            GLib.source_remove(self._save_source)
        self._save_source = GLib.timeout_add(350, self._save)

    def _save(self) -> bool:
        self._save_source = 0
        cfg.save(cfg.normalize(copy.deepcopy(self.config)))
        return False

    def toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=text, timeout=2))

    # ------------------------------------------------------------ Facetten
    def _build_facets(self) -> None:
        for group in self._facet_groups:
            self.facet_page.remove(group)
        self._facet_groups = []

        intro = Adw.PreferencesGroup(
            title="Deine Facetten",
            description="Facetten sind Kontexte wie Arbeit oder Freizeit. Jede hat eigene Farbe, Apps und "
                        "Benachrichtigungsregeln. Fenster bleiben in der Facette, in der sie geöffnet wurden.",
        )
        add_row = Adw.ActionRow(title="Neue Facette anlegen", activatable=True)
        add_row.add_prefix(Gtk.Image(icon_name="list-add-symbolic"))
        add_row.connect("activated", lambda *_: self._add_facet())
        intro.add(add_row)
        self.facet_page.add(intro)
        self._facet_groups.append(intro)

        for index, facet in enumerate(self.config["facets"]):
            group = self._facet_group(index, facet)
            self.facet_page.add(group)
            self._facet_groups.append(group)

    def _facet_group(self, index: int, facet: dict) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title=f"{index + 1}. {facet['name']}", description=f"Super+{index + 1}")
        suffix = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        for icon, tip, delta in (("go-up-symbolic", "Nach oben", -1), ("go-down-symbolic", "Nach unten", 1)):
            button = Gtk.Button(icon_name=icon, tooltip_text=tip, css_classes=["flat"])
            button.set_sensitive(0 <= index + delta < len(self.config["facets"]))
            button.connect("clicked", lambda _b, d=delta: self._move_facet(index, d))
            suffix.append(button)
        delete = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Facette löschen", css_classes=["flat", "error"])
        delete.set_sensitive(len(self.config["facets"]) > 1)
        delete.connect("clicked", lambda *_: self._delete_facet(index))
        suffix.append(delete)
        group.set_header_suffix(suffix)

        name = Adw.EntryRow(title="Name", text=facet["name"])

        def on_name(row):
            facet["name"] = row.get_text().strip() or facet["name"]
            group.set_title(f"{index + 1}. {facet['name']}")
            self.changed()

        name.connect("changed", on_name)
        group.add(name)

        color_row = Adw.ActionRow(title="Farbe", subtitle="Färbt Leiste, Dock, Fensterrahmen und Hintergrund")
        color = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER)
        color.set_rgba(hex_to_rgba(facet["color"]))

        def on_color(button, _pspec):
            facet["color"] = rgba_to_hex(button.get_rgba())
            self.changed()

        color.connect("notify::rgba", on_color)
        color_row.add_suffix(color)
        group.add(color_row)

        icon_row = Adw.ComboRow(title="Symbol", model=Gtk.StringList.new([i.replace("-symbolic", "") for i in FACET_ICONS]))
        if facet.get("icon") in FACET_ICONS:
            icon_row.set_selected(FACET_ICONS.index(facet["icon"]))
        icon_row.connect("notify::selected", lambda row, _p: (facet.__setitem__("icon", FACET_ICONS[row.get_selected()]), self.changed()))
        group.add(icon_row)

        policy = Adw.ComboRow(title="Benachrichtigungen", subtitle="Was als Popup erscheinen darf",
                              model=Gtk.StringList.new([label for _key, label in POLICIES]))
        keys = [key for key, _label in POLICIES]
        policy.set_selected(keys.index(facet.get("notifications", "all")))
        policy.connect("notify::selected", lambda row, _p: (facet.__setitem__("notifications", keys[row.get_selected()]), self.changed()))
        group.add(policy)

        wallpaper = Adw.ActionRow(title="Hintergrundbild",
                                  subtitle=facet.get("wallpaper") or "Generativer Prisma-Verlauf in der Facettenfarbe")
        choose = Gtk.Button(icon_name="document-open-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Bild wählen", css_classes=["flat"])
        clear = Gtk.Button(icon_name="edit-clear-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Verlauf verwenden", css_classes=["flat"])
        choose.connect("clicked", lambda *_: self._choose_wallpaper(facet, wallpaper))
        clear.connect("clicked", lambda *_: (facet.__setitem__("wallpaper", None),
                                             wallpaper.set_subtitle("Generativer Prisma-Verlauf in der Facettenfarbe"),
                                             self.changed()))
        wallpaper.add_suffix(choose)
        wallpaper.add_suffix(clear)
        group.add(wallpaper)

        group.add(self._pins_row(facet))
        return group

    def _pins_row(self, facet: dict) -> Adw.ExpanderRow:
        expander = Adw.ExpanderRow(title="Apps im Dock", subtitle=f"{len(facet['pinned'])} angeheftet")
        by_id = {a.get_id()[:-8].lower(): a for a in self.apps if a.get_id()}

        def resolve(pin: str):
            for candidate in pin.split("|"):
                if candidate.lower() in by_id:
                    return by_id[candidate.lower()]
            return None

        rows: list[Gtk.Widget] = []

        def rebuild():
            for row in rows:
                expander.remove(row)
            rows.clear()
            for pin in list(facet["pinned"]):
                info = resolve(pin)
                row = Adw.ActionRow(title=info.get_display_name() if info else pin.split("|")[0],
                                    subtitle="" if info else "Nicht installiert – wird ausgeblendet")
                image = Gtk.Image(pixel_size=32)
                if info and info.get_icon():
                    image.set_from_gicon(info.get_icon())
                else:
                    image.set_from_icon_name("application-x-executable")
                row.add_prefix(image)
                remove = Gtk.Button(icon_name="list-remove-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"])
                remove.connect("clicked", lambda _b, p=pin: (facet["pinned"].remove(p), rebuild(), self.changed()))
                row.add_suffix(remove)
                expander.add_row(row)
                rows.append(row)
            add_row = Adw.ActionRow(title="App hinzufügen")
            names = Gtk.StringList.new([a.get_display_name() for a in self.apps])
            dropdown = Gtk.DropDown(model=names, valign=Gtk.Align.CENTER, enable_search=True)
            dropdown.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
            add = Gtk.Button(icon_name="list-add-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"])

            def on_add(*_):
                position = dropdown.get_selected()
                if position == Gtk.INVALID_LIST_POSITION:
                    return
                app_id = self.apps[position].get_id()[:-8]
                if app_id not in facet["pinned"]:
                    facet["pinned"].append(app_id)
                    rebuild()
                    self.changed()

            add.connect("clicked", on_add)
            add_row.add_suffix(dropdown)
            add_row.add_suffix(add)
            expander.add_row(add_row)
            rows.append(add_row)
            expander.set_subtitle(f"{len(facet['pinned'])} angeheftet")

        rebuild()
        return expander

    def _choose_wallpaper(self, facet: dict, row: Adw.ActionRow) -> None:
        dialog = Gtk.FileDialog(title="Hintergrundbild wählen")
        images = Gtk.FileFilter(name="Bilder")
        images.add_mime_type("image/*")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(images)
        dialog.set_filters(filters)

        def done(dlg, result):
            try:
                file = dlg.open_finish(result)
            except GLib.Error:
                return
            facet["wallpaper"] = file.get_path()
            row.set_subtitle(file.get_path())
            self.changed()

        dialog.open(self, None, done)

    def _add_facet(self) -> None:
        count = len(self.config["facets"])
        self.config["facets"].append({
            "id": f"facette-{count + 1}",
            "name": f"Facette {count + 1}",
            "icon": "view-grid-symbolic",
            "color": NEW_FACET_COLORS[count % len(NEW_FACET_COLORS)],
            "notifications": "all",
            "wallpaper": None,
            "pinned": [],
        })
        self.config = cfg.normalize(self.config)
        self._build_facets()
        self.changed()
        self.toast("Facette hinzugefügt")

    def _delete_facet(self, index: int) -> None:
        name = self.config["facets"][index]["name"]
        dialog = Adw.MessageDialog(transient_for=self, heading=f"„{name}“ löschen?",
                                   body="Offene Fenster dieser Facette wandern in die erste Facette.")
        dialog.add_response("cancel", "Abbrechen")
        dialog.add_response("delete", "Löschen")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

        def response(_dialog, answer):
            if answer == "delete":
                del self.config["facets"][index]
                self._build_facets()
                self.changed()

        dialog.connect("response", response)
        dialog.present()

    def _move_facet(self, index: int, delta: int) -> None:
        facets = self.config["facets"]
        target = index + delta
        if 0 <= target < len(facets):
            facets[index], facets[target] = facets[target], facets[index]
            self._build_facets()
            self.changed()

    # ------------------------------------------------------------ Automatik
    def _automation_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="Facetten nach Zeitplan",
                                     description="Prisma wechselt zu Beginn eines Zeitfensters automatisch die Facette. "
                                                 "Manuelle Wechsel bleiben bis zum nächsten Zeitfenster bestehen.")
        switch = Adw.SwitchRow(title="Automatisch wechseln", active=bool(self.config.get("auto_switch")))
        switch.connect("notify::active", lambda row, _p: (self.config.__setitem__("auto_switch", row.get_active()), self.changed()))
        group.add(switch)
        page.add(group)

        self.rules_group = Adw.PreferencesGroup(title="Regeln")
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Regel hinzufügen", css_classes=["flat"], valign=Gtk.Align.CENTER)
        add.connect("clicked", lambda *_: self._add_rule())
        self.rules_group.set_header_suffix(add)
        page.add(self.rules_group)
        self._rule_rows: list[Gtk.Widget] = []
        self._build_rules()
        return page

    def _build_rules(self) -> None:
        for row in self._rule_rows:
            self.rules_group.remove(row)
        self._rule_rows = []
        for index, rule in enumerate(self.config["rules"]):
            row = self._rule_row(index, rule)
            self.rules_group.add(row)
            self._rule_rows.append(row)
        if not self.config["rules"]:
            empty = Adw.ActionRow(title="Noch keine Regeln", subtitle="Mit + eine Regel anlegen, z. B. werktags 8–17 Uhr → Arbeit")
            self.rules_group.add(empty)
            self._rule_rows.append(empty)

    def _rule_row(self, index: int, rule: dict) -> Gtk.Widget:
        facets = self.config["facets"]
        row = Adw.ActionRow(title="Facette")
        dropdown = Gtk.DropDown(model=Gtk.StringList.new([f["name"] for f in facets]), valign=Gtk.Align.CENTER)
        ids = [f["id"] for f in facets]
        if rule.get("facet") in ids:
            dropdown.set_selected(ids.index(rule["facet"]))
        dropdown.connect("notify::selected", lambda d, _p: (rule.__setitem__("facet", ids[d.get_selected()]), self.changed()))
        row.add_prefix(dropdown)

        days = Gtk.Box(css_classes=["linked"], valign=Gtk.Align.CENTER)
        active_days = set(rule.get("days", range(7)))
        for day_index, day in enumerate(DAYS):
            toggle = Gtk.ToggleButton(label=day, active=day_index in active_days)

            def on_toggle(button, d=day_index):
                current = set(rule.get("days", range(7)))
                if button.get_active():
                    current.add(d)
                else:
                    current.discard(d)
                rule["days"] = sorted(current)
                self.changed()

            toggle.connect("toggled", on_toggle)
            days.append(toggle)
        row.add_suffix(days)

        for key, default in (("from", "08:00"), ("to", "17:00")):
            entry = Gtk.Entry(text=rule.get(key, default), max_width_chars=5, width_chars=5, valign=Gtk.Align.CENTER)

            def on_time(widget, k=key):
                try:
                    schedule.parse_hm(widget.get_text())
                except ValueError:
                    widget.add_css_class("error")
                    return
                widget.remove_css_class("error")
                rule[k] = widget.get_text().strip()
                self.changed()

            entry.connect("changed", on_time)
            row.add_suffix(entry)
        remove = Gtk.Button(icon_name="user-trash-symbolic", css_classes=["flat"], valign=Gtk.Align.CENTER)
        remove.connect("clicked", lambda *_: (self.config["rules"].pop(index), self._build_rules(), self.changed()))
        row.add_suffix(remove)
        return row

    def _add_rule(self) -> None:
        self.config["rules"].append({"facet": self.config["facets"][0]["id"], "days": [0, 1, 2, 3, 4],
                                     "from": "08:00", "to": "17:00"})
        self._build_rules()
        self.changed()

    # ------------------------------------------------------------ Darstellung
    def _appearance_page(self) -> Adw.PreferencesPage:
        a = self.config["appearance"]
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="Hell und Dunkel",
                                     description="Im automatischen Modus folgt Prisma – und mit ihm deine Apps – der Tageszeit.")
        mode = Adw.ComboRow(title="Erscheinungsbild", model=Gtk.StringList.new([label for _k, label in MODES]))
        keys = [k for k, _label in MODES]
        mode.set_selected(keys.index(a.get("mode", "auto")))
        mode.connect("notify::selected", lambda row, _p: (a.__setitem__("mode", keys[row.get_selected()]), self.changed()))
        group.add(mode)
        for key, title in (("light_from", "Hell ab"), ("dark_from", "Dunkel ab")):
            row = Adw.EntryRow(title=title, text=a.get(key, ""))

            def on_change(widget, k=key):
                try:
                    schedule.parse_hm(widget.get_text())
                except ValueError:
                    return
                a[k] = widget.get_text().strip()
                self.changed()

            row.connect("changed", on_change)
            group.add(row)
        page.add(group)

        shell = Adw.PreferencesGroup(title="Shell")
        size = Adw.SpinRow.new_with_range(24, 96, 2)
        size.set_title("Symbolgröße im Dock")
        size.set_value(a.get("dock_icon_size", 44))
        size.connect("notify::value", lambda row, _p: (a.__setitem__("dock_icon_size", int(row.get_value())), self.changed()))
        shell.add(size)
        for key, title, subtitle in (
            ("follow_facet_color", "Akzent folgt der Facette", "Sonst wird überall die feste Akzentfarbe genutzt"),
            ("greeting", "Begrüßung auf dem Schreibtisch", "Tageszeit-Gruß, Datum und aktive Facette"),
            ("clock_seconds", "Sekunden in der Uhr", ""),
        ):
            row = Adw.SwitchRow(title=title, subtitle=subtitle, active=bool(a.get(key)))
            row.connect("notify::active", lambda r, _p, k=key: (a.__setitem__(k, r.get_active()), self.changed()))
            shell.add(row)
        accent_row = Adw.ActionRow(title="Feste Akzentfarbe")
        accent = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER)
        accent.set_rgba(hex_to_rgba(a.get("accent", "#4f8cff")))
        accent.connect("notify::rgba", lambda b, _p: (a.__setitem__("accent", rgba_to_hex(b.get_rgba())), self.changed()))
        accent_row.add_suffix(accent)
        shell.add(accent_row)
        page.add(shell)
        return page

    # ------------------------------------------------------------ Fokus & Kompass
    def _focus_page(self) -> Adw.PreferencesPage:
        f, k = self.config["focus"], self.config["kompass"]
        page = Adw.PreferencesPage()
        focus = Adw.PreferencesGroup(title="Fokus-Sessions",
                                     description="Während einer Session werden Benachrichtigungen gesammelt und danach als Rückblick gezeigt.")
        for key, title, low, high in (("work_minutes", "Fokuszeit (Minuten)", 5, 180),
                                      ("break_minutes", "Pause (Minuten)", 0, 60)):
            row = Adw.SpinRow.new_with_range(low, high, 5 if key == "work_minutes" else 1)
            row.set_title(title)
            row.set_value(f.get(key, 25))
            row.connect("notify::value", lambda r, _p, kk=key: (f.__setitem__(kk, int(r.get_value())), self.changed()))
            focus.add(row)
        allow = Adw.EntryRow(title="Diese Apps dürfen trotzdem stören (Komma-getrennt)", text=", ".join(f.get("allow_apps", [])))
        allow.connect("changed", lambda r: (f.__setitem__("allow_apps", [x.strip() for x in r.get_text().split(",") if x.strip()]), self.changed()))
        focus.add(allow)
        page.add(focus)

        kompass = Adw.PreferencesGroup(title="Kompass")
        web = Adw.EntryRow(title="Websuche ({query} = Suchbegriff)", text=k.get("web_search", ""))
        web.connect("changed", lambda r: (k.__setitem__("web_search", r.get_text().strip()), self.changed()))
        kompass.add(web)
        files = Adw.SwitchRow(title="Dateien im Persönlichen Ordner durchsuchen", active=bool(k.get("index_files", True)))
        files.connect("notify::active", lambda r, _p: (k.__setitem__("index_files", r.get_active()), self.changed()))
        kompass.add(files)
        page.add(kompass)

        general = Adw.PreferencesGroup(title="Allgemein")
        name = Adw.EntryRow(title="Anzeigename für die Begrüßung", text=self.config.get("user_name", ""))
        name.connect("changed", lambda r: (self.config.__setitem__("user_name", r.get_text().strip()), self.changed()))
        general.add(name)
        terminal = Adw.EntryRow(title="Terminal (leer = automatisch)", text=self.config.get("terminal", ""))
        terminal.connect("changed", lambda r: (self.config.__setitem__("terminal", r.get_text().strip()), self.changed()))
        general.add(terminal)
        page.add(general)
        return page

    # ------------------------------------------------------------ Tastenkürzel
    def _shortcuts_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="Tastenkürzel",
                                     description="Anpassbar in ~/.config/prisma/labwc/rc.xml (danach „prisma-msg reload“ bzw. neu anmelden).")
        for keys, action in SHORTCUTS:
            row = Adw.ActionRow(title=action)
            row.add_suffix(Gtk.Label(label=keys, css_classes=["dim-label", "monospace"]))
            group.add(row)
        page.add(group)
        return page

    def _about(self) -> None:
        about = Adw.AboutWindow(
            transient_for=self,
            application_name="Prisma",
            application_icon="preferences-desktop-display",
            version=__version__,
            developer_name="Prisma-Projekt",
            license_type=Gtk.License.GPL_3_0,
            comments="Eine kontextbewusste Desktop-Umgebung für Ubuntu-basierte Distributionen.",
        )
        about.present()


class SettingsApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID + ".Settings", flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self) -> None:
        # Ohne Settings-Portal meldet GTK eine DPI von -1 – libadwaita rechnet dann Breiten zu 0.
        settings = Gtk.Settings.get_default()
        if settings.props.gtk_xft_dpi <= 0:
            settings.props.gtk_xft_dpi = 96 * 1024
        window = self.get_active_window() or SettingsWindow(self)
        window.present()


def main() -> int:
    return SettingsApp().run(sys.argv[:1])


if __name__ == "__main__":
    sys.exit(main())
