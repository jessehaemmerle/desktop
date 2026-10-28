"""Privacy: app permissions for camera and location (xdg-desktop-portal), microphone.

Apps that ask through the portals (Flatpak and Snap apps, some native apps)
keep their decision in the portal permission store, which these helpers read
and change. Apps with direct device access are not affected; the pages say so.
"""

import logging
import shutil
import subprocess

from gi.repository import Gio, GLib

log = logging.getLogger(__name__)

STORE_BUS = "org.freedesktop.impl.portal.PermissionStore"
STORE_PATH = "/org/freedesktop/impl/portal/PermissionStore"

# feature -> (table, id, "allowed" value, "denied" value)
FEATURES = {
    "camera": ("devices", "camera", ["yes"], ["no"]),
    "location": ("location", "location", ["EXACT", "0"], ["NONE", "0"]),
}


def _call(method, args, reply="()"):
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        result = bus.call_sync(STORE_BUS, STORE_PATH, STORE_BUS, method, args,
                               GLib.VariantType.new(reply), Gio.DBusCallFlags.NONE, 2000, None)
        return result.unpack()
    except GLib.Error as exc:
        log.info("permission store %s: %s", method, exc.message)
        return None


def is_allowed(feature, value):
    allowed = FEATURES[feature][2]
    return bool(value) and value[0] == allowed[0]


def app_permissions(feature):
    """{app id: allowed?} for apps that asked for ``feature``."""
    table, entry, _allowed, _denied = FEATURES[feature]
    result = _call("Lookup", GLib.Variant("(ss)", (table, entry)), "(a{sas}v)")
    if not result:
        return {}
    permissions = result[0]
    return {app: is_allowed(feature, value) for app, value in permissions.items() if app}


def set_app_permission(feature, app_id, allowed):
    table, entry, yes, no = FEATURES[feature]
    _call("SetPermission", GLib.Variant("(sbssas)", (table, True, entry, app_id, yes if allowed else no)))


def set_all(feature, allowed):
    """Master switch: apply to every app that has asked so far."""
    for app_id in app_permissions(feature):
        set_app_permission(feature, app_id, allowed)


def app_name(app_id):
    info = Gio.DesktopAppInfo.new(app_id + ".desktop") if app_id else None
    return info.get_display_name() if info is not None else app_id


def set_microphone(enabled):
    """There is no per-app microphone gate on Linux: muting the input devices is
    the closest equivalent of turning microphone access off."""
    if shutil.which("pactl"):
        subprocess.Popen(["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "0" if enabled else "1"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
