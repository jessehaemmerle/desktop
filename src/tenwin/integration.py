"""Make apps of other toolkits follow the Tenwin look (Settings > Colors).

* Qt: qt5ct/qt6ct colour schemes generated from the Tenwin palette (accent,
  light/dark, high contrast) with the Fusion style and the Selawik font.
  Without qt5ct, Qt apps use the gtk3 platform theme and thus the Tenwin GTK theme.
* Firefox/Thunderbird (opt-in): a userChrome.css in every profile with square
  tabs, the accent colour on the selected tab and a red close button.
* Flatpak (opt-in): the Tenwin GTK themes are copied to ~/.local/share/themes
  and Flatpak apps get them through a user override.
"""

import configparser
import logging
import os
import shutil
import subprocess

from tenwin import paths

log = logging.getLogger(__name__)

MARKER = "/* Tenwin: generated, removed when the option is turned off */"
USERJS_LINE = 'user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true); // Tenwin'
TENWIN_THEMES = ("Tenwin", "Tenwin-Dark", "Tenwin-Contrast", "Tenwin-Contrast-White")


def config_home():
    return os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")


def data_home():
    return os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")


# -- Qt --------------------------------------------------------------------------------

QT_ROLES = ["WindowText", "Button", "Light", "Midlight", "Dark", "Mid", "Text", "BrightText", "ButtonText",
            "Base", "Window", "Shadow", "Highlight", "HighlightedText", "Link", "LinkVisited", "AlternateBase",
            "NoRole", "ToolTipBase", "ToolTipText", "PlaceholderText"]


def qt_colors(pal, disabled=False):
    """One qt5ct colour-scheme line (the 21 QPalette roles in order) as #argb values."""
    fg = pal["app_fg_dim"] if disabled else pal["app_fg"]
    values = {
        "WindowText": fg, "Button": pal["app_button"], "Light": pal["app_card_hover"],
        "Midlight": pal["app_card"], "Dark": pal["app_divider"], "Mid": pal["app_border"], "Text": fg,
        "BrightText": "#ffffff", "ButtonText": fg, "Base": pal["app_field"], "Window": pal["app_bg"],
        "Shadow": "#000000", "Highlight": pal["accent"], "HighlightedText": pal["accent_fg"],
        "Link": pal["app_link"], "LinkVisited": pal["app_link"], "AlternateBase": pal["app_bg_alt"],
        "NoRole": pal["app_bg"], "ToolTipBase": pal["app_field"], "ToolTipText": pal["app_fg"],
        "PlaceholderText": pal["app_fg_dim"],
    }
    return ", ".join("#ff" + _hex6(values[role]) for role in QT_ROLES)


def _hex6(color):
    color = color.strip()
    if color.startswith("#") and len(color) == 7:
        return color[1:].lower()
    if color.startswith("#") and len(color) == 4:
        return "".join(c * 2 for c in color[1:]).lower()
    if color.startswith("rgba(") or color.startswith("rgb("):
        parts = color[color.index("(") + 1:-1].split(",")
        return "%02x%02x%02x" % tuple(int(float(p)) for p in parts[:3])
    return "000000"


def qt_scheme(pal):
    return ("[ColorScheme]\nactive_colors=%s\ndisabled_colors=%s\ninactive_colors=%s\n"
            % (qt_colors(pal), qt_colors(pal, disabled=True), qt_colors(pal)))


def qt_config(scheme_path, font="Selawik,10,-1,5,50,0,0,0,0,0"):
    return ("[Appearance]\ncolor_scheme_path=%s\ncustom_palette=true\nstandard_dialogs=gtk3\nstyle=Fusion\n"
            "icon_theme=%s\n\n[Fonts]\nfixed=\"DejaVu Sans Mono,10,-1,5,50,0,0,0,0,0\"\ngeneral=\"%s\"\n"
            % (scheme_path, icon_theme(), font))


def icon_theme():
    for name in ("Yaru", "Adwaita"):
        if os.path.isdir("/usr/share/icons/%s" % name):
            return name
    return "hicolor"


def qt_platform_theme(settings):
    """Value for QT_QPA_PLATFORMTHEME."""
    if settings["integration.qt"] and shutil.which("qt5ct"):
        return "qt5ct"
    return "gtk3"


def apply_qt(settings, pal):
    if not settings["integration.qt"]:
        return
    for tool in ("qt5ct", "qt6ct"):
        if not shutil.which(tool):
            continue
        directory = os.path.join(config_home(), tool)
        scheme = os.path.join(directory, "colors", "Tenwin.conf")
        _write(scheme, qt_scheme(pal))
        conf = os.path.join(directory, "%s.conf" % tool)
        if _owned_or_missing(conf):
            _write(conf, "# Tenwin\n" + qt_config(scheme))


def _owned_or_missing(path):
    """Only overwrite configuration files that Tenwin wrote itself."""
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.readline().startswith("# Tenwin")
    except OSError:
        return True


# -- Firefox / Thunderbird ----------------------------------------------------------------

MOZILLA_ROOTS = [
    "~/.mozilla/firefox", "~/snap/firefox/common/.mozilla/firefox",
    "~/.var/app/org.mozilla.firefox/.mozilla/firefox",
    "~/.thunderbird", "~/snap/thunderbird/common/.thunderbird",
    "~/.var/app/org.mozilla.Thunderbird/.thunderbird",
]


def mozilla_profiles():
    profiles = []
    for root in MOZILLA_ROOTS:
        root = os.path.expanduser(root)
        ini = os.path.join(root, "profiles.ini")
        if not os.path.exists(ini):
            continue
        parser = configparser.RawConfigParser()
        try:
            parser.read(ini, encoding="utf-8")
        except (configparser.Error, OSError):
            continue
        for section in parser.sections():
            if not section.startswith("Profile") or not parser.has_option(section, "Path"):
                continue
            path = parser.get(section, "Path")
            relative = parser.get(section, "IsRelative", fallback="1") == "1"
            full = os.path.join(root, path) if relative else path
            if os.path.isdir(full):
                profiles.append(full)
    return profiles


def user_chrome(pal, dark):
    accent = pal["accent"]
    return MARKER + """
:root {
  --tab-border-radius: 0px !important;
  --toolbarbutton-border-radius: 0px !important;
  --arrowpanel-border-radius: 0px !important;
  --tab-block-margin: 0px !important;
}
.tab-background { border-radius: 0 !important; box-shadow: none !important; }
.tabbrowser-tab[selected] .tab-background, .tabmail-tab[selected] {
  border-top: 2px solid %(accent)s !important;
}
.titlebar-button { border-radius: 0 !important; }
.titlebar-button.titlebar-close:hover, .titlebar-close:hover {
  background-color: #e81123 !important; color: #ffffff !important;
}
#urlbar-background, #searchbar, .searchBox { border-radius: 0 !important; }
menupopup, panel { --panel-border-radius: 0px !important; }
""" % {"accent": accent} + ("/* dark */\n" if dark else "")


def apply_mozilla(settings, pal):
    enabled = settings["integration.mozilla"]
    dark = settings["appearance.app_mode"] == "dark"
    for profile in mozilla_profiles():
        chrome = os.path.join(profile, "chrome", "userChrome.css")
        userjs = os.path.join(profile, "user.js")
        if enabled:
            if _ours_or_missing_css(chrome):
                _write(chrome, user_chrome(pal, dark))
            _add_line(userjs, USERJS_LINE)
        else:
            if _is_ours(chrome):
                os.unlink(chrome)
            _remove_line(userjs, USERJS_LINE)


def _is_ours(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read(len(MARKER)) == MARKER
    except OSError:
        return False


def _ours_or_missing_css(path):
    return not os.path.exists(path) or _is_ours(path)


def _add_line(path, line):
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        lines = []
    if line not in lines:
        lines.append(line)
        _write(path, "\n".join(lines) + "\n")


def _remove_line(path, line):
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return
    if line in lines:
        lines = [l for l in lines if l != line]
        if lines:
            _write(path, "\n".join(lines) + "\n")
        else:
            os.unlink(path)


# -- Flatpak ---------------------------------------------------------------------------

def themes_source():
    for root in (paths.DATA_DIR / "themes", "/usr/share/themes"):
        if os.path.isdir(os.path.join(str(root), "Tenwin")):
            return str(root)
    return None


def apply_flatpak(settings, gtk_theme):
    if not shutil.which("flatpak"):
        return
    target_root = os.path.join(data_home(), "themes")
    if settings["integration.flatpak"]:
        source = themes_source()
        if source:
            for name in TENWIN_THEMES:
                src = os.path.join(source, name, "gtk-3.0")
                if os.path.isdir(src):
                    dst = os.path.join(target_root, name, "gtk-3.0")
                    shutil.rmtree(dst, ignore_errors=True)
                    shutil.copytree(src, dst)
        _flatpak(["override", "--user", "--filesystem=xdg-data/themes:ro", "--env=GTK_THEME=%s" % gtk_theme])
    elif flatpak_override_active():
        _flatpak(["override", "--user", "--nofilesystem=xdg-data/themes", "--unset-env=GTK_THEME"])


def flatpak_override_active():
    path = os.path.join(data_home(), "flatpak", "overrides", "global")
    try:
        with open(path, encoding="utf-8") as fh:
            return "GTK_THEME=Tenwin" in fh.read()
    except OSError:
        return False


def _flatpak(args):
    try:
        subprocess.run(["flatpak"] + args, check=False, timeout=20,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("flatpak %s: %s", " ".join(args), exc)


# -- all -------------------------------------------------------------------------------

def apply(settings):
    from tenwin import session, theme
    pal = theme.palette(settings)
    for step, args in ((apply_qt, (settings, pal)), (apply_mozilla, (settings, pal)),
                       (apply_flatpak, (settings, session.theme_name(settings)))):
        try:
            step(*args)
        except OSError as exc:  # never break the session over a theming problem
            log.warning("%s: %s", step.__name__, exc)


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tenwin-tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(content)
    os.replace(tmp, path)

