"""Session actions: lock, sign out, power, screenshots, standard tools."""

import logging
import os
import shutil
import subprocess
import time

from gi.repository import Gio, GLib

from tenwin import paths

log = logging.getLogger(__name__)


def _spawn(argv):
    try:
        GLib.spawn_async(argv, flags=GLib.SpawnFlags.SEARCH_PATH)
        return True
    except GLib.Error as exc:
        log.warning("cannot run %s: %s", argv[0], exc)
        return False


def lock():
    return _spawn([paths.binary("tenwin-lock"), "--daemonize"])


def logout():
    if os.environ.get("LABWC_PID"):
        return _spawn(["labwc", "--exit"])
    return False


def _login1(method, *args):
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        bus.call_sync("org.freedesktop.login1", "/org/freedesktop/login1",
                      "org.freedesktop.login1.Manager", method,
                      GLib.Variant("(b)", (True,)), None, Gio.DBusCallFlags.NONE, -1, None)
        return True
    except GLib.Error as exc:
        log.warning("login1.%s failed: %s", method, exc)
        return _spawn(["systemctl", method.lower()])


def suspend():
    return _login1("Suspend")


def reboot():
    return _login1("Reboot")


def poweroff():
    return _login1("PowerOff")


def can(method):
    """'yes', 'no', 'challenge' … from login1.Can<Method>."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        res = bus.call_sync("org.freedesktop.login1", "/org/freedesktop/login1",
                            "org.freedesktop.login1.Manager", "Can" + method, None,
                            GLib.VariantType.new("(s)"), Gio.DBusCallFlags.NONE, 1000, None)
        return res.unpack()[0]
    except GLib.Error:
        return "na"


def screenshot_dir():
    path = os.path.join(paths.xdg_user_dir("PICTURES"), "Screenshots")
    os.makedirs(path, exist_ok=True)
    return path


def screenshot(region=False, callback=None):
    """Full screenshot to ~/Pictures/Screenshots, or a region to the clipboard."""
    if not shutil.which("grim"):
        return None
    stamp = time.strftime("%Y-%m-%d %H-%M-%S")
    target = os.path.join(screenshot_dir(), "Screenshot %s.png" % stamp)
    if region:
        if not shutil.which("slurp"):
            return None

        def worker():
            sel = subprocess.run(["slurp"], capture_output=True, text=True)
            if sel.returncode != 0 or not sel.stdout.strip():
                return
            subprocess.run(["grim", "-g", sel.stdout.strip(), target])
            if shutil.which("wl-copy") and os.path.exists(target):
                with open(target, "rb") as fh:
                    subprocess.run(["wl-copy", "--type", "image/png"], stdin=fh)
            if callback:
                GLib.idle_add(callback, target)

        import threading
        threading.Thread(target=worker, daemon=True).start()
        return target
    if subprocess.run(["grim", target]).returncode == 0:
        if callback:
            callback(target)
        return target
    return None


def terminal_command():
    for term in ("x-terminal-emulator", "gnome-terminal", "kgx", "konsole", "xfce4-terminal",
                 "foot", "alacritty", "kitty", "xterm"):
        if shutil.which(term):
            return term
    return None


def open_terminal(directory=None):
    term = terminal_command()
    if term is None:
        return False
    try:
        subprocess.Popen([term], cwd=directory or os.path.expanduser("~"),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except OSError:
        return False


def first_available(*commands):
    for cmd in commands:
        if shutil.which(cmd[0]):
            return cmd
    return None


def task_manager():
    cmd = first_available(["gnome-system-monitor"], ["plasma-systemmonitor"], ["lxtask"], ["htop"])
    if cmd and cmd[0] == "htop":
        term = terminal_command()
        cmd = [term, "-e", "htop"] if term else None
    return _spawn(cmd) if cmd else False


def run(argv):
    return _spawn(argv)
