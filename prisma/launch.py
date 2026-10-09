"""``prisma-launch`` – startet Standardprogramme für Tastenkürzel (Terminal, Dateien, Browser, Medien)."""

from __future__ import annotations

import os
import shlex
import shutil
import sys

from .core import config as cfg

TERMINALS = ["x-terminal-emulator", "gnome-terminal", "ptyxis", "kgx", "foot", "kitty", "alacritty",
             "xfce4-terminal", "konsole", "xterm"]


def terminal() -> list[str]:
    configured = cfg.load().get("terminal") or os.environ.get("TERMINAL", "")
    for candidate in [configured] + TERMINALS:
        if candidate and shutil.which(shlex.split(candidate)[0]):
            return shlex.split(candidate)
    return ["xterm"]


def media(method: str) -> int:
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    (names,) = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames",
                             None, None, Gio.DBusCallFlags.NONE, 1000, None).unpack()
    players = [n for n in names if n.startswith("org.mpris.MediaPlayer2.")]

    def status(name: str) -> str:
        try:
            value = bus.call_sync(name, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties", "Get",
                                  GLib.Variant("(ss)", ("org.mpris.MediaPlayer2.Player", "PlaybackStatus")),
                                  None, Gio.DBusCallFlags.NONE, 500, None)
            return value.unpack()[0]
        except GLib.Error:
            return "Stopped"

    players.sort(key=lambda n: {"Playing": 0, "Paused": 1}.get(status(n), 2))
    if not players:
        return 1
    bus.call_sync(players[0], "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", method,
                  None, None, Gio.DBusCallFlags.NONE, 1000, None)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    what = argv[0] if argv else ""
    if what == "terminal":
        command = terminal()
        os.execvp(command[0], command)
    elif what == "files":
        os.execvp("xdg-open", ["xdg-open", os.path.expanduser("~")])
    elif what == "browser":
        browser = shutil.which("x-www-browser") or shutil.which("sensible-browser")
        if browser:
            os.execv(browser, [browser])
        os.execvp("xdg-open", ["xdg-open", "about:blank"])
    elif what == "media" and len(argv) > 1 and argv[1] in ("PlayPause", "Next", "Previous", "Stop"):
        return media(argv[1])
    print("Verwendung: prisma-launch <terminal|files|browser|media PlayPause|Next|Previous>", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
