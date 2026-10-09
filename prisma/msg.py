"""``prisma-msg`` – steuert die laufende Shell über D-Bus (für Tastenkürzel und Skripte)."""

from __future__ import annotations

import sys

from . import SHELL_ID, SHELL_PATH

USAGE = """Verwendung: prisma-msg <befehl> [argument]

  kompass [text]          Kompass öffnen/schließen (optional mit Suchtext)
  quicksettings           Schnelleinstellungen
  daypanel                Tagesüberblick & Benachrichtigungen
  facet <name|nr|next|prev>   Facette wechseln
  move-to-facet <name|nr>  Aktives Fenster in eine Facette verschieben
  focus [minuten|stop]    Fokus-Session starten/beenden
  volume <up|down|mute>   Lautstärke
  brightness <up|down>    Helligkeit
  screenshot <full|area>  Bildschirmfoto
  dnd                     Nicht stören umschalten
  theme-cycle             Erscheinungsbild: Auto → Hell → Dunkel
  lock                    Bildschirm sperren
  power <logout|suspend|reboot|poweroff>
  reload                  Shell neu laden
"""

WITH_ARGUMENT = {"facet", "move-to-facet", "focus", "volume", "brightness", "screenshot", "power"}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0 if argv else 1
    command, args = argv[0], argv[1:]

    import gi

    gi.require_version("GLib", "2.0")
    from gi.repository import Gio, GLib

    if command == "kompass" and args:
        command, parameters = "kompass-query", [GLib.Variant("s", " ".join(args))]
    elif command in WITH_ARGUMENT:
        parameters = [GLib.Variant("s", args[0] if args else "toggle")]
    else:
        parameters = []

    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync(
            SHELL_ID, SHELL_PATH, "org.gtk.Actions", "Activate",
            GLib.Variant("(sava{sv})", (command, parameters, {})),
            None, Gio.DBusCallFlags.NONE, 3000, None,
        )
    except GLib.Error as exc:
        print(f"prisma-msg: Shell nicht erreichbar ({exc.message})", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
