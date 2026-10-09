"""Erzeugt Farbpaletten, das GTK-CSS der Shell und das labwc-Fensterthema.

Alles wird aus *einer* Akzentfarbe (der aktiven Facette) und dem Hell/Dunkel-Modus
abgeleitet – so färbt ein Facettenwechsel die gesamte Oberfläche konsistent um.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from string import Template

from . import colors


@dataclass(frozen=True)
class Palette:
    dark: bool
    accent: str
    accent_fg: str
    bg: str
    fg: str
    surface: str  # rgba() – Inseln und Panels
    surface_solid: str
    surface_hi: str
    hover: str
    border: str
    fg_dim: str
    accent_soft: str
    accent_glow: str
    shadow: str
    titlebar: str
    titlebar_inactive: str

    def as_dict(self) -> dict:
        return asdict(self)


def make_palette(accent: str, dark: bool) -> Palette:
    if dark:
        bg = colors.mix("#101218", accent, 0.07)
        fg = "#eef0f6"
        # Akzent bei zu wenig Kontrast zum dunklen Grund aufhellen.
        while colors.contrast(accent, bg) < 3.0 and colors.luminance(accent) < 0.9:
            accent = colors.lighten(accent, 0.12)
        surface_solid = colors.mix(bg, "#ffffff", 0.035)
        return Palette(
            dark=True,
            accent=accent,
            accent_fg=colors.readable_on(accent),
            bg=bg,
            fg=fg,
            surface=colors.rgba(surface_solid, 0.94),
            surface_solid=surface_solid,
            surface_hi=colors.mix(bg, "#ffffff", 0.09),
            hover=colors.rgba("#ffffff", 0.08),
            border=colors.rgba("#ffffff", 0.09),
            fg_dim=colors.rgba(fg, 0.62),
            accent_soft=colors.rgba(accent, 0.22),
            accent_glow=colors.rgba(accent, 0.45),
            shadow="rgba(0, 0, 0, 0.42)",
            titlebar=colors.mix(bg, accent, 0.10),
            titlebar_inactive=colors.mix(bg, "#ffffff", 0.03),
        )
    bg = colors.mix("#f5f6fa", accent, 0.04)
    fg = "#1a1c23"
    while colors.contrast(accent, bg) < 3.0 and colors.luminance(accent) > 0.05:
        accent = colors.darken(accent, 0.12)
    surface_solid = colors.mix(bg, "#ffffff", 0.6)
    return Palette(
        dark=False,
        accent=accent,
        accent_fg=colors.readable_on(accent),
        bg=bg,
        fg=fg,
        surface=colors.rgba(surface_solid, 0.95),
        surface_solid=surface_solid,
        surface_hi=colors.mix(bg, "#000000", 0.05),
        hover=colors.rgba("#000000", 0.06),
        border=colors.rgba("#000000", 0.08),
        fg_dim=colors.rgba(fg, 0.60),
        accent_soft=colors.rgba(accent, 0.16),
        accent_glow=colors.rgba(accent, 0.35),
        shadow="rgba(20, 24, 40, 0.18)",
        titlebar=colors.mix(bg, accent, 0.07),
        titlebar_inactive=colors.mix(bg, "#ffffff", 0.4),
    )


def wallpaper_stops(accent: str, dark: bool) -> dict:
    """Farben für den generativen „Prisma“-Hintergrund (Basis + drei Lichtfelder)."""
    if dark:
        base_top = colors.mix("#0b0d14", accent, 0.10)
        base_bottom = colors.mix("#05060a", accent, 0.05)
        glow = (
            colors.shift_hue(accent, 0, 1.0, 0.95),
            colors.shift_hue(accent, -38, 0.9, 0.85),
            colors.shift_hue(accent, 42, 0.85, 0.9),
        )
        strength = (0.55, 0.40, 0.35)
    else:
        base_top = colors.mix("#f7f8fc", accent, 0.10)
        base_bottom = colors.mix("#e9ecf5", accent, 0.16)
        glow = (
            colors.lighten(colors.shift_hue(accent, 0, 0.8), 0.15),
            colors.lighten(colors.shift_hue(accent, -38, 0.7), 0.25),
            colors.lighten(colors.shift_hue(accent, 42, 0.7), 0.25),
        )
        strength = (0.50, 0.42, 0.38)
    return {"top": base_top, "bottom": base_bottom, "glow": glow, "strength": strength}


_CSS = Template(
    r"""
/* ---- Prisma Shell – automatisch generiert ---- */
* {
  font-family: "Inter", "Cantarell", "Ubuntu", sans-serif;
  -gtk-icon-shadow: none;
  text-shadow: none;
}
window.prisma-layer, window.prisma-layer > * { background: transparent; }
window.prisma-layer { color: $fg; }

label { color: $fg; }
.dim { color: $fg_dim; }
.accent-text { color: $accent; }

button {
  background: transparent; background-image: none; border: none; box-shadow: none;
  color: $fg; border-radius: 12px; padding: 4px 8px; min-height: 0; min-width: 0;
  transition: background-color 160ms ease, color 160ms ease;
}
button:hover { background-color: $hover; }
button:active, button:checked { background-color: $accent_soft; }
button image { color: $fg; }

/* ---------- Inseln (gemeinsame Bausteine) ---------- */
.island {
  background-color: $surface;
  border: 1px solid $border;
  border-radius: 999px;
  box-shadow: 0 3px 10px $shadow;
  padding: 3px;
}
.card {
  background-color: $surface;
  border: 1px solid $border;
  border-radius: 22px;
  box-shadow: 0 18px 48px $shadow;
}

/* ---------- Horizont (obere Leiste) ---------- */
.bar-button { border-radius: 999px; padding: 4px 12px; }
.bar-button label { font-weight: 600; font-size: 13px; }
.prisma-logo { color: $accent; font-size: 15px; font-weight: 800; }
.facet-chip { border-radius: 999px; padding: 4px 8px; }
.facet-dot {
  min-width: 10px; min-height: 10px; border-radius: 999px;
  transition: all 220ms ease;
}
.facet-chip.active { background-color: $accent_soft; }
.facet-chip.active .facet-dot { box-shadow: 0 0 0 3px $accent_glow; }
.facet-name { font-weight: 700; font-size: 13px; margin-left: 7px; }
.clock { font-weight: 700; font-size: 13px; font-feature-settings: "tnum"; }
.clock-date { color: $fg_dim; font-weight: 500; font-size: 13px; margin-right: 6px; }
.status-icon { color: $fg; -gtk-icon-style: symbolic; }
.status-text { font-size: 12px; font-weight: 600; font-feature-settings: "tnum"; }
.badge {
  background-color: $accent; color: $accent_fg; border-radius: 999px;
  font-size: 10px; font-weight: 800; min-width: 16px; min-height: 16px; padding: 0 4px;
}
.focus-chip { background-color: $accent; border-radius: 999px; padding: 4px 12px; }
.focus-chip label, .focus-chip image { color: $accent_fg; font-weight: 800; }
.focus-chip.break { background-color: #3cc48a; }

/* ---------- Insel-Dock ---------- */
.dock { padding: 6px 8px; border-radius: 26px; }
.dock-item { padding: 4px; border-radius: 16px; }
.dock-item image { -gtk-icon-transform: scale(1); transition: -gtk-icon-transform 180ms ease; }
.dock-item:hover image { -gtk-icon-transform: scale(1.14); }
.dock-item:hover { background-color: transparent; }
.dock-item.launching image { -gtk-icon-transform: scale(0.85); }
.dock-indicator {
  min-width: 5px; min-height: 5px; border-radius: 999px; margin-top: 2px;
  background-color: transparent; transition: all 220ms ease;
}
.dock-indicator.running { background-color: $fg_dim; }
.dock-indicator.active { background-color: $accent; min-width: 16px; }
.dock-sep { min-width: 1px; background-color: $border; margin: 8px 6px; }
.kompass-button { background-color: $accent; border-radius: 16px; }
.kompass-button image { color: $accent_fg; }
.kompass-button:hover { background-color: $accent; box-shadow: 0 0 0 4px $accent_glow; }
.media-chip { background-color: $hover; border-radius: 16px; padding: 2px 10px 2px 4px; }
.media-title { font-weight: 700; font-size: 12px; }
.media-artist { font-size: 11px; color: $fg_dim; }

/* ---------- Kompass ---------- */
.backdrop { background-color: rgba(0, 0, 0, 0); transition: background-color 200ms ease; }
.backdrop.shown { background-color: rgba(0, 0, 0, $backdrop_alpha); }
.overlay-card { opacity: 0; margin-top: -10px; transition: opacity 180ms ease-out, margin-top 220ms ease-out; }
.overlay-card.fade-only { margin-top: 0; }
.overlay-card.shown { opacity: 1; margin-top: 0; }
.kompass { padding: 10px; min-width: 660px; }
.kompass-entry-row { padding: 6px 10px 10px 10px; border-bottom: 1px solid $border; }
.kompass-entry-row image { color: $accent; }
entry.kompass-entry, .kompass-entry {
  background: transparent; background-image: none; border: none; box-shadow: none; outline: none;
  color: $fg; caret-color: $accent; font-size: 21px; font-weight: 500; padding: 4px 6px;
}
.kompass-entry selection { background-color: $accent_soft; color: $fg; }
list, list row { background: transparent; color: $fg; }
.kompass-list { margin-top: 6px; }
.kompass-row { border-radius: 14px; padding: 7px 10px; outline: none; }
.kompass-row:hover { background-color: $hover; }
.kompass-row:selected, .kompass-row:selected:focus { background-color: $accent_soft; }
.kompass-row:selected .kompass-enter { color: $accent; opacity: 1; }
.kompass-title { font-weight: 600; font-size: 14px; }
.kompass-sub { color: $fg_dim; font-size: 12px; }
.kompass-kind { color: $fg_dim; font-size: 11px; font-weight: 600; }
.kompass-enter { color: $fg_dim; opacity: 0; font-size: 12px; font-weight: 800; }
.kompass-big { font-size: 26px; font-weight: 800; color: $accent; }
.facet-badge { border-radius: 12px; min-width: 34px; min-height: 34px; font-weight: 800; font-size: 15px; }
.kompass-section { color: $fg_dim; font-size: 11px; font-weight: 800; margin: 8px 12px 2px 12px; letter-spacing: 1px; }
.kompass-footer { padding: 8px 10px 2px 10px; border-top: 1px solid $border; margin-top: 6px; }
.chip { background-color: $hover; border-radius: 999px; padding: 2px 9px; font-size: 11px; color: $fg_dim; margin-right: 6px; }
.chip-key { font-weight: 800; color: $accent; }

/* ---------- Panels (Schnelleinstellungen, Tagesansicht) ---------- */
.panel { padding: 16px; min-width: 360px; }
.section-title { color: $fg_dim; font-size: 11px; font-weight: 800; letter-spacing: 1px; margin: 10px 4px 6px 4px; }
.tile {
  background-color: $hover; border-radius: 18px; padding: 10px 12px; min-height: 44px;
  transition: background-color 200ms ease;
}
.tile:hover { background-color: $accent_soft; }
.tile.on { background-color: $accent; }
.tile.on label, .tile.on image { color: $accent_fg; }
.tile.on .tile-sub { color: $accent_fg; opacity: 0.8; }
.tile-title { font-weight: 700; font-size: 13px; }
.tile-sub { font-size: 11px; color: $fg_dim; }
.round-button { border-radius: 999px; padding: 8px; background-color: $hover; }
.round-button:hover { background-color: $accent_soft; }
.danger:hover { background-color: rgba(240, 70, 80, 0.85); }
.danger:hover image, .danger:hover label { color: #ffffff; }

scale { padding: 6px 4px; }
scale trough { min-height: 8px; border-radius: 999px; background-color: $hover; border: none; }
scale highlight { background-color: $accent; border-radius: 999px; border: none; }
scale slider {
  min-width: 18px; min-height: 18px; margin: -6px; border-radius: 999px;
  background-color: #ffffff; background-image: none; border: none;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.35);
}
levelbar trough { min-height: 6px; border-radius: 999px; background-color: $hover; border: none; padding: 0; }
levelbar block.filled { background-color: $accent; border-radius: 999px; border: none; }
levelbar block.empty { background-color: transparent; border: none; }

.big-time { font-size: 46px; font-weight: 800; font-feature-settings: "tnum"; }
.big-date { font-size: 14px; color: $fg_dim; font-weight: 600; }
calendar {
  background: transparent; color: $fg; border: none; padding: 4px;
  font-feature-settings: "tnum";
}
calendar:selected { background-color: $accent; color: $accent_fg; border-radius: 10px; }
calendar.header { background: transparent; border: none; color: $fg; }
calendar.button { color: $fg_dim; }
calendar:indeterminate { color: $fg_dim; opacity: 0.4; }
.stat-bar { min-height: 8px; border-radius: 999px; }
.stat-label { font-size: 12px; }
scrolledwindow, viewport { background: transparent; border: none; }
undershoot, overshoot { background: none; }

/* ---------- Benachrichtigungen ---------- */
.notification { padding: 12px 14px; border-radius: 20px; min-width: 340px; margin: 4px 0; box-shadow: 0 6px 14px $shadow; }
.notification.critical { border: 1px solid rgba(240, 70, 80, 0.7); }
.notification.in-center { background-color: $hover; box-shadow: none; border: none; }
.notif-app { color: $fg_dim; font-size: 11px; font-weight: 700; }
.notif-time { color: $fg_dim; font-size: 11px; }
.notif-summary { font-weight: 700; font-size: 14px; }
.notif-body { font-size: 13px; color: $fg_dim; }
.notif-action { background-color: $hover; border-radius: 10px; padding: 4px 10px; margin-top: 8px; }
.notif-action:hover { background-color: $accent_soft; }
.notif-close { padding: 2px; border-radius: 999px; }
.digest { background-color: $accent_soft; border-radius: 16px; padding: 10px 12px; }
.digest label { color: $fg; }

/* ---------- OSD & Toast ---------- */
.osd { padding: 12px 18px; border-radius: 999px; min-width: 260px; }
.osd image { color: $fg; }
.osd-value { font-weight: 800; font-size: 13px; font-feature-settings: "tnum"; min-width: 36px; }
"""
)


def shell_css(palette: Palette) -> str:
    values = palette.as_dict()
    values["backdrop_alpha"] = "0.38" if palette.dark else "0.22"
    return _CSS.substitute(values)


def labwc_themerc(palette: Palette) -> str:
    """Fensterdekorationen für labwc, passend zur aktiven Facette."""
    p = palette
    title_fg = p.fg
    inactive_fg = colors.mix(p.fg, p.titlebar_inactive, 0.45)
    lines = {
        "border.width": "1",
        "padding.height": "7",
        "padding.width": "8",
        "titlebar.height": "34",
        "window.active.border.color": p.accent,
        "window.inactive.border.color": colors.mix(p.titlebar_inactive, p.fg, 0.12),
        "window.active.title.bg.color": p.titlebar,
        "window.inactive.title.bg.color": p.titlebar_inactive,
        "window.active.label.text.color": title_fg,
        "window.inactive.label.text.color": inactive_fg,
        "window.label.text.justify": "center",
        "window.active.button.unpressed.image.color": title_fg,
        "window.inactive.button.unpressed.image.color": inactive_fg,
        "window.active.indicator.toggled-keybind.color": p.accent,
        "menu.items.bg.color": p.surface_solid,
        "menu.items.text.color": p.fg,
        "menu.items.active.bg.color": p.accent,
        "menu.items.active.text.color": p.accent_fg,
        "menu.separator.color": colors.mix(p.surface_solid, p.fg, 0.15),
        "menu.border.color": colors.mix(p.surface_solid, p.fg, 0.12),
        "menu.border.width": "1",
        "osd.bg.color": p.surface_solid,
        "osd.border.color": p.accent,
        "osd.border.width": "1",
        "osd.label.text.color": p.fg,
        "osd.window-switcher.width": "560",
        "osd.window-switcher.item.active.border.color": p.accent,
        "snapping.overlay.region.bg.color": colors.mix(p.bg, p.accent, 0.35),
        "snapping.overlay.edge.bg.color": colors.mix(p.bg, p.accent, 0.35),
    }
    head = "# Prisma – automatisch erzeugt, wird bei Facettenwechsel überschrieben\n"
    return head + "".join(f"{key}: {value}\n" for key, value in lines.items())
