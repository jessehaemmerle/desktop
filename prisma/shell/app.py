"""Die Shell-Anwendung: verbindet alle Bausteine und stellt Aktionen für ``prisma-msg`` bereit."""

from __future__ import annotations

import os
import signal
import sys
from datetime import datetime

from gi.repository import Gio, GLib, Gtk

from .. import SHELL_ID, __version__
from ..core import config as cfg
from . import util


class PrismaShell(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=SHELL_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.hub = None
        self._add_actions()

    # ------------------------------------------------------------ Aktionen
    def _add_actions(self) -> None:
        simple = {
            "kompass": lambda: self._toggle_overlay(self.kompass, opener=lambda: self.kompass.open()),
            "quicksettings": lambda: self._toggle_overlay(self.quicksettings),
            "daypanel": lambda: self._toggle_overlay(self.daypanel),
            "dnd": lambda: self.hub.set_dnd(not self.hub.dnd),
            "lock": self.lock,
            "reload": self.reload,
            "facet-next": lambda: self.hub.cycle_facet(1),
            "facet-prev": lambda: self.hub.cycle_facet(-1),
            "theme-cycle": lambda: self.hub.cycle_mode(),
        }
        for name, callback in simple.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, cb=callback: self.hub and cb())
            self.add_action(action)
        with_arg = {
            "kompass-query": lambda arg: self._open_kompass(arg),
            "facet": lambda arg: self._facet(arg),
            "move-to-facet": lambda arg: self._move_to_facet(arg),
            "focus": lambda arg: self._focus(arg),
            "volume": lambda arg: self._volume(arg),
            "brightness": lambda arg: self._brightness(arg),
            "screenshot": lambda arg: self.screenshot(arg),
            "power": lambda arg: self.power(arg),
        }
        for name, callback in with_arg.items():
            action = Gio.SimpleAction.new(name, GLib.VariantType("s"))
            action.connect("activate", lambda _a, param, cb=callback: self.hub and cb(param.get_string()))
            self.add_action(action)

    def do_activate(self) -> None:
        if self.hub is not None:
            return
        self.hold()
        from .background import Backgrounds
        from .dock import Dock
        from .hub import Hub
        from .kompass import Kompass
        from .notify_ui import NotificationPopups
        from .osd import Osd
        from .panels import DayPanel, QuickSettings
        from .services import Services
        from .topbar import TopBar

        self.hub = Hub(self)
        self.services = Services()
        self.backgrounds = Backgrounds(self, self.hub)
        self.topbar = TopBar(self, self.hub, self.services)
        self.dock = Dock(self, self.hub, self.services)
        self.popups = NotificationPopups(self, self.hub)
        self.osd = Osd(self)
        self.kompass = Kompass(self, self.hub, self.services)
        self.quicksettings = QuickSettings(self, self.hub, self.services)
        self.daypanel = DayPanel(self, self.hub)
        self.overlays = [self.kompass, self.quicksettings, self.daypanel]
        for overlay in (self.quicksettings, self.daypanel):
            overlay.on_visibility = self._panel_visibility
        self.hub.connect("toast", lambda _h, icon, text: self.osd.toast(icon, text))
        for sig in (signal.SIGINT, signal.SIGTERM):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, self._quit)
        print(f"prisma: Shell {__version__} gestartet – Facette „{self.hub.facet['name']}“")

    def _quit(self) -> bool:
        if self.hub:
            self.hub.shutdown()
        self.quit()
        return False

    # ------------------------------------------------------------ Overlays
    def _toggle_overlay(self, overlay, opener=None) -> None:
        for other in self.overlays:
            if other is not overlay:
                other.hide()
        if overlay.visible:
            overlay.hide()
        elif opener:
            opener()
        else:
            overlay.show()

    def _panel_visibility(self, _overlay, _visible: bool) -> None:
        self.popups.set_suppressed(self.quicksettings.visible or self.daypanel.visible)

    def _open_kompass(self, text: str) -> None:
        for other in self.overlays:
            if other is not self.kompass:
                other.hide()
        self.kompass.open(text)

    # ------------------------------------------------------------ Facetten & Fokus
    def _facet(self, arg: str) -> None:
        if arg in ("next", "+"):
            self.hub.cycle_facet(1)
        elif arg in ("prev", "-"):
            self.hub.cycle_facet(-1)
        else:
            self.hub.switch_facet(arg)

    def _move_to_facet(self, arg: str) -> None:
        facet = cfg.find_facet(self.hub.config, arg)
        window = self.hub.windows.active()
        if facet and self.hub.windows.move_to_facet(window, facet["id"]):
            self.hub.emit("toast", "window-new-symbolic", f"Fenster nach „{facet['name']}“ verschoben")

    def _focus(self, arg: str) -> None:
        if arg in ("", "toggle"):
            self.hub.toggle_focus()
        elif arg == "stop":
            self.hub.stop_focus()
        else:
            try:
                self.hub.start_focus(float(arg))
            except ValueError:
                self.hub.toggle_focus()

    # ------------------------------------------------------------ Hardware-Tasten
    def _volume(self, arg: str) -> None:
        audio = self.services.audio
        if arg == "mute":
            audio.toggle_mute()
        else:
            audio.step(1 if arg == "up" else -1)
        self.osd.show_level(audio.icon, 0.0 if audio.muted else audio.volume)

    def _brightness(self, arg: str) -> None:
        brightness = self.services.brightness
        if brightness.level is None:
            brightness.refresh()
            return
        brightness.step(1 if arg == "up" else -1)
        self.osd.show_level("display-brightness-symbolic", brightness.level)

    # ------------------------------------------------------------ System
    def lock(self) -> None:
        util.spawn(util.prisma_command("prisma.lock"))

    def power(self, what: str) -> None:
        if what == "logout":
            self.hub.shutdown()
            if os.environ.get("LABWC_PID"):
                util.spawn(["labwc", "--exit"])
            else:
                self.quit()
        elif what in ("suspend", "reboot", "poweroff", "hibernate"):
            if what == "suspend":
                self.lock()
            util.spawn(["systemctl", what])

    def screenshot(self, mode: str) -> None:
        if not util.has("grim"):
            self.hub.emit("toast", "dialog-warning-symbolic", "Für Bildschirmfotos bitte „grim“ installieren")
            return
        folder = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) or os.path.expanduser("~/Bilder")
        folder = os.path.join(folder, "Bildschirmfotos")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, datetime.now().strftime("Bildschirmfoto_%Y-%m-%d_%H-%M-%S.png"))
        quoted = GLib.shell_quote(path)
        if mode == "area":
            if not util.has("slurp"):
                self.hub.emit("toast", "dialog-warning-symbolic", "Für Bereichsfotos bitte „slurp“ installieren")
                return
            command = f'region="$(slurp)" && grim -g "$region" {quoted}'
        else:
            command = f"grim {quoted}"
        if util.has("wl-copy"):
            command += f" && wl-copy < {quoted}"
        command += " && echo ok"

        def done(output):
            if output and "ok" in output:
                self.hub.notifications.post_internal(
                    "Bildschirmfoto gespeichert", f"{os.path.basename(path)} – auch in der Zwischenablage",
                    path, actions=[("open", "Öffnen"), ("folder", "Ordner zeigen")],
                    callback=lambda key: util.spawn(["xdg-open", path if key != "folder" else folder]))

        # Kurz warten, damit geschlossene Overlays nicht im Bild landen.
        GLib.timeout_add(350, lambda: util.run(["sh", "-c", command], done) and False)

    def reload(self) -> None:
        if self.hub:
            self.hub.shutdown()
        os.execv(sys.executable, [sys.executable, "-m", "prisma.shell.main"] + sys.argv[1:])
