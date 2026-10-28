"""Colour palette and CSS loading for all Tenwin UIs.

CSS files in ``data/css`` are ``string.Template`` files; ``$name`` placeholders
are filled from :func:`palette`. Each process calls :func:`install` once and
the CSS is regenerated whenever an ``appearance.*`` setting changes.
"""

import colorsys
import logging
import string

from tenwin import paths
from tenwin.config import get_settings

log = logging.getLogger(__name__)

FONT_FAMILY = '"Selawik", "Segoe UI", "Noto Sans", "Ubuntu", sans-serif'


def hex_to_rgb(value):
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return tuple(int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c * 255))) for c in rgb)


def shade(color, lightness_delta):
    """Shift the HLS lightness of ``color`` by ``lightness_delta`` (-1..1)."""
    r, g, b = hex_to_rgb(color)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = max(0.0, min(1.0, l + lightness_delta))
    return rgb_to_hex(colorsys.hls_to_rgb(h, l, s))


def luminance(color):
    def channel(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in hex_to_rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def rgba(color, alpha):
    r, g, b = hex_to_rgb(color)
    return "rgba(%d,%d,%d,%.3f)" % (round(r * 255), round(g * 255), round(b * 255), alpha)


# High contrast themes (Ease of Access): (background, text, selection, selection text, links, light?)
CONTRAST = {
    "contrast-black": ("#000000", "#ffffff", "#1aebff", "#000000", "#ffff00", False),
    "contrast-1": ("#000000", "#ffff00", "#00ffff", "#000000", "#8080ff", False),
    "contrast-2": ("#000000", "#00ff00", "#0000ff", "#ffffff", "#ffff00", False),
    "contrast-white": ("#ffffff", "#000000", "#37006e", "#ffffff", "#00009f", True),
}


def contrast_overrides(name):
    """Palette entries that replace the normal colours in a high contrast theme."""
    bg, fg, sel, sel_fg, link, _light = CONTRAST[name]
    keys = {}
    keys.update({"sh_fg": fg, "sh_fg_dim": fg, "sh_fg_disabled": fg, "app_fg": fg, "app_fg_dim": fg})
    keys.update({
        "accent": sel, "accent_fg": sel_fg, "accent_light1": sel, "accent_light2": sel, "accent_light3": sel,
        "accent_dark1": sel, "accent_dark2": sel, "accent_dark3": sel,
        "accent_a20": sel, "accent_a40": sel,
        "sh_hover": sel, "sh_press": sel, "sh_border": fg, "sh_divider": fg, "sh_field": bg,
        "sh_field_hover": bg, "sh_card": bg, "sh_card_hover": bg, "sh_qa_off": bg, "sh_qa_off_hover": sel,
        "sh_menu_bg": bg, "sh_menu_hover": sel,
        "taskbar_bg": bg, "panel_bg": bg, "panel_solid": bg, "toast_bg": bg, "tile_bg": bg,
        "tile_hover_border": sel,
        "app_bg": bg, "app_bg_alt": bg, "app_border": fg, "app_divider": fg, "app_hover": sel,
        "app_select": sel, "app_select_hover": sel, "app_select_border": fg, "app_ribbon": bg,
        "app_tab_active": bg, "app_field": bg, "app_field_border": fg, "app_button": bg,
        "app_button_hover": sel, "app_button_border": fg, "app_nav_bg": bg, "app_card": bg,
        "app_card_hover": sel, "app_link": link, "app_settings_bg": bg, "app_settings_nav": bg,
    })
    return keys


def palette(settings=None):
    s = settings or get_settings()
    accent = s["appearance.accent"]
    shell_dark = s["appearance.shell_mode"] == "dark"
    app_dark = s["appearance.app_mode"] == "dark"
    transparent = s["appearance.transparency"]
    on_surfaces = s["appearance.accent_on_surfaces"]
    accent_fg = "#000000" if luminance(accent) > 0.4 else "#ffffff"

    p = {
        "font": FONT_FAMILY,
        "accent": accent,
        "accent_fg": accent_fg,
        "accent_light1": shade(accent, 0.10),
        "accent_light2": shade(accent, 0.20),
        "accent_light3": shade(accent, 0.30),
        "accent_dark1": shade(accent, -0.08),
        "accent_dark2": shade(accent, -0.16),
        "accent_dark3": shade(accent, -0.24),
        "accent_a20": rgba(accent, 0.20),
        "accent_a40": rgba(accent, 0.40),
    }

    if shell_dark:
        base_taskbar, base_panel, fg = "#101010", "#1f1f1f", "#ffffff"
        p.update({
            "sh_fg": fg, "sh_fg_dim": "#a6a6a6", "sh_fg_disabled": "#6d6d6d",
            "sh_hover": "rgba(255,255,255,0.10)", "sh_press": "rgba(255,255,255,0.18)",
            "sh_border": "rgba(255,255,255,0.12)", "sh_divider": "#3a3a3a",
            "sh_field": "#2b2b2b", "sh_field_hover": "#333333",
            "sh_card": "#2b2b2b", "sh_card_hover": "#3a3a3a",
            "sh_qa_off": "#3b3b3b", "sh_qa_off_hover": "#4a4a4a",
            "sh_menu_bg": "#2b2b2b", "sh_menu_hover": "#414141",
            "sh_icon_filter": "1",
        })
    else:
        base_taskbar, base_panel, fg = "#eeeeee", "#e6e6e6", "#000000"
        p.update({
            "sh_fg": fg, "sh_fg_dim": "#5d5d5d", "sh_fg_disabled": "#a0a0a0",
            "sh_hover": "rgba(0,0,0,0.08)", "sh_press": "rgba(0,0,0,0.15)",
            "sh_border": "rgba(0,0,0,0.12)", "sh_divider": "#cccccc",
            "sh_field": "#ffffff", "sh_field_hover": "#f5f5f5",
            "sh_card": "#f2f2f2", "sh_card_hover": "#ffffff",
            "sh_qa_off": "#d6d6d6", "sh_qa_off_hover": "#c8c8c8",
            "sh_menu_bg": "#f2f2f2", "sh_menu_hover": "#dadada",
            "sh_icon_filter": "0",
        })

    if on_surfaces:
        base_taskbar = shade(accent, -0.15)
        base_panel = shade(accent, -0.08)
        p["sh_fg"] = "#ffffff" if luminance(base_panel) < 0.45 else "#000000"

    alpha_taskbar = 0.85 if transparent else 1.0
    alpha_panel = 0.95 if transparent else 1.0
    p.update({
        "taskbar_bg": rgba(base_taskbar, alpha_taskbar),
        "panel_bg": rgba(base_panel, alpha_panel),
        "panel_solid": base_panel,
        "toast_bg": rgba(base_panel, 0.96 if transparent else 1.0),
        "tile_bg": accent,
        "tile_hover_border": "rgba(255,255,255,0.45)" if shell_dark else "rgba(0,0,0,0.35)",
    })

    if app_dark:
        p.update({
            "app_bg": "#191919", "app_bg_alt": "#202020", "app_fg": "#ffffff",
            "app_fg_dim": "#a0a0a0", "app_border": "#2b2b2b", "app_divider": "#3a3a3a",
            "app_hover": "#2a2a2a", "app_select": "#777777", "app_select_hover": "#8a8a8a",
            "app_select_border": "#999999", "app_ribbon": "#2b2b2b",
            "app_tab_active": "#191919", "app_field": "#2b2b2b",
            "app_field_border": "#666666", "app_button": "#333333",
            "app_button_hover": "#454545", "app_button_border": "#5a5a5a",
            "app_nav_bg": "#191919", "app_card": "#2b2b2b", "app_card_hover": "#3a3a3a",
            "app_link": shade(accent, 0.25), "app_settings_bg": "#000000",
            "app_settings_nav": "#1f1f1f",
        })
    else:
        p.update({
            "app_bg": "#ffffff", "app_bg_alt": "#f5f6f7", "app_fg": "#000000",
            "app_fg_dim": "#6d6d6d", "app_border": "#e5e5e5", "app_divider": "#dadbdc",
            "app_hover": "#e5f3ff", "app_select": "#cce8ff", "app_select_hover": "#d9ecff",
            "app_select_border": "#99d1ff", "app_ribbon": "#f5f6f7",
            "app_tab_active": "#f5f6f7", "app_field": "#ffffff",
            "app_field_border": "#d9d9d9", "app_button": "#e1e1e1",
            "app_button_hover": "#e5f1fb", "app_button_border": "#adadad",
            "app_nav_bg": "#ffffff", "app_card": "#f2f2f2", "app_card_hover": "#e6e6e6",
            "app_link": shade(accent, -0.08), "app_settings_bg": "#ffffff",
            "app_settings_nav": "#f2f2f2",
        })
    contrast = s.get("appearance.contrast")
    if contrast in CONTRAST:
        p.update(contrast_overrides(contrast))
    return p


def render_css(name, settings=None):
    path = paths.DATA_DIR / "css" / ("%s.css" % name)
    template = string.Template(path.read_text(encoding="utf-8"))
    return template.safe_substitute(palette(settings))


_providers = {}


def install(*names):
    """Load ``common.css`` plus the given CSS templates and keep them updated."""
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gdk, Gtk

    names = ("common",) + tuple(n for n in names if n != "common")
    screen = Gdk.Screen.get_default()
    _register_icon_dir()

    def reload(*_args):
        for name in names:
            provider = _providers.get(name)
            if provider is None:
                provider = Gtk.CssProvider()
                _providers[name] = provider
                Gtk.StyleContext.add_provider_for_screen(
                    screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            try:
                provider.load_from_data(render_css(name).encode("utf-8"))
            except Exception as exc:  # GLib.Error on CSS syntax problems
                log.error("CSS %s: %s", name, exc)
        gtk_settings = Gtk.Settings.get_default()
        if gtk_settings is not None:
            gtk_settings.set_property(
                "gtk-application-prefer-dark-theme",
                get_settings()["appearance.app_mode"] == "dark")

    def on_changed(_settings, keys):
        if any(k.startswith("appearance.") for k in keys):
            reload()

    reload()
    get_settings().connect("changed", on_changed)


def _register_icon_dir():
    if not paths.DEV_MODE:
        return
    from gi.repository import Gtk
    theme = Gtk.IconTheme.get_default()
    if theme is not None:
        theme.prepend_search_path(str(paths.ICON_DIR))
