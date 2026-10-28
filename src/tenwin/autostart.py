"""Start XDG autostart entries (~/.config/autostart, /etc/xdg/autostart)."""

import logging
import os
import shutil
import sys

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

log = logging.getLogger("tenwin.autostart")

DESKTOP_NAMES = ("Tenwin", "wlroots")

# Tenwin provides these itself (tray icons for network/volume, notifications).
SKIP = {
    "nm-applet.desktop",
    "blueman.desktop",
    "gnome-keyring-secrets.desktop",
    "gnome-keyring-ssh.desktop",
    "gnome-keyring-pkcs11.desktop",
    "polkit-gnome-authentication-agent-1.desktop",
    "lxpolkit.desktop",
    "org.gnome.SettingsDaemon.Sharing.desktop",
    "xdg-desktop-portal-gnome.desktop",
}


def autostart_dirs():
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    config_dirs = (os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg").split(":")
    return [os.path.join(config_home, "autostart")] + [os.path.join(d, "autostart") for d in config_dirs]


def collect_entries():
    """Return {file name: path}; earlier (user) directories override later ones."""
    entries = {}
    for directory in autostart_dirs():
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            continue
        for name in names:
            if name.endswith(".desktop") and name not in entries:
                entries[name] = os.path.join(directory, name)
    return entries


def should_start(name, keyfile):
    group = "Desktop Entry"

    def get(key):
        try:
            return keyfile.get_string(group, key)
        except GLib.Error:
            return None

    def get_bool(key):
        try:
            return keyfile.get_boolean(group, key)
        except GLib.Error:
            return False

    if name in SKIP or get_bool("Hidden"):
        return False
    only = get("OnlyShowIn")
    if only and not set(filter(None, only.split(";"))) & set(DESKTOP_NAMES):
        return False
    not_in = get("NotShowIn")
    if not_in and set(filter(None, not_in.split(";"))) & set(DESKTOP_NAMES):
        return False
    try_exec = get("TryExec")
    if try_exec and not shutil.which(try_exec):
        return False
    return True


def entries():
    """[(file name, path, display name, enabled)] for the Startup pages."""
    result = []
    for name, path in collect_entries().items():
        keyfile = GLib.KeyFile()
        try:
            keyfile.load_from_file(path, GLib.KeyFileFlags.KEEP_TRANSLATIONS)
            title = keyfile.get_locale_string("Desktop Entry", "Name", None)
        except GLib.Error:
            continue
        try:
            hidden = keyfile.get_boolean("Desktop Entry", "Hidden")
        except GLib.Error:
            hidden = False
        result.append((name, path, title, not hidden))
    return sorted(result, key=lambda e: e[2].casefold())


def set_enabled(name, path, enabled):
    """Enable/disable an entry through a copy in ~/.config/autostart (Hidden=)."""
    user_dir = os.path.join(GLib.get_user_config_dir(), "autostart")
    os.makedirs(user_dir, exist_ok=True)
    target = os.path.join(user_dir, name)
    keyfile = GLib.KeyFile()
    keyfile.load_from_file(path, GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
    keyfile.set_boolean("Desktop Entry", "Hidden", not enabled)
    keyfile.save_to_file(target)


def main():
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    for name, path in collect_entries().items():
        keyfile = GLib.KeyFile()
        try:
            keyfile.load_from_file(path, GLib.KeyFileFlags.NONE)
        except GLib.Error:
            continue
        if not should_start(name, keyfile):
            continue
        info = Gio.DesktopAppInfo.new_from_keyfile(keyfile)
        if info is None:
            continue
        try:
            info.launch([], None)
            log.info("started %s", name)
        except GLib.Error as exc:
            log.warning("cannot start %s: %s", name, exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
