"""Wendet die Palette der aktiven Facette auf Shell, labwc-Fensterrahmen und GTK-Apps an."""

from __future__ import annotations

import os
from pathlib import Path

from gi.repository import Gdk, Gio, GLib, Gtk

from ..core import theme
from . import util


def labwc_theme_path() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "themes" / "Prisma" / "openbox-3" / "themerc"


class Styling:
    def __init__(self, hub):
        self.hub = hub
        self.palette: theme.Palette | None = None
        self.provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self.provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 10
        )
        self._labwc_pending = 0
        self._last_dark: bool | None = None

    def accent(self) -> str:
        appearance = self.hub.config["appearance"]
        if appearance.get("follow_facet_color", True):
            return self.hub.facet["color"]
        return appearance.get("accent") or "#4f8cff"

    def apply(self) -> None:
        dark = self.hub.dark
        self.palette = theme.make_palette(self.accent(), dark)
        try:
            self.provider.load_from_data(theme.shell_css(self.palette).encode("utf-8"))
        except GLib.Error as exc:
            print(f"prisma: CSS-Fehler: {exc.message}")
        Gtk.Settings.get_default().props.gtk_application_prefer_dark_theme = dark
        if self._last_dark is not dark:
            self._last_dark = dark
            self._apply_system_color_scheme(dark)
        self._schedule_labwc()

    # ---------------------------------------------------------------- labwc
    def _schedule_labwc(self) -> None:
        if self._labwc_pending:
            GLib.source_remove(self._labwc_pending)
        self._labwc_pending = GLib.timeout_add(250, self._write_labwc_theme)

    def _write_labwc_theme(self) -> bool:
        self._labwc_pending = 0
        if self.palette is None:
            return False
        path = labwc_theme_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            content = theme.labwc_themerc(self.palette)
            if not path.exists() or path.read_text() != content:
                path.write_text(content)
                if os.environ.get("LABWC_PID"):
                    util.spawn(["labwc", "--reconfigure"])
        except OSError as exc:
            print(f"prisma: labwc-Thema nicht schreibbar: {exc}")
        return False

    # ------------------------------------------------- System-Farbschema (Apps)
    def _apply_system_color_scheme(self, dark: bool) -> None:
        source = Gio.SettingsSchemaSource.get_default()
        if source is None or source.lookup("org.gnome.desktop.interface", True) is None:
            return
        settings = Gio.Settings.new("org.gnome.desktop.interface")
        keys = settings.props.settings_schema.list_keys()
        if "color-scheme" in keys:
            settings.set_string("color-scheme", "prefer-dark" if dark else "default")
        # GTK3-Apps kennen color-scheme nicht – passendes -dark-Thema wählen, falls vorhanden.
        current = settings.get_string("gtk-theme")
        base = current[:-5] if current.endswith("-dark") else current
        wanted = f"{base}-dark" if dark else base
        if wanted != current and (wanted == base or _theme_exists(wanted)):
            settings.set_string("gtk-theme", wanted)


def _theme_exists(name: str) -> bool:
    dirs = [os.path.expanduser("~/.themes"), os.path.expanduser("~/.local/share/themes")]
    dirs += [os.path.join(d, "themes") for d in GLib.get_system_data_dirs()]
    return any(os.path.isdir(os.path.join(d, name, "gtk-3.0")) for d in dirs)
