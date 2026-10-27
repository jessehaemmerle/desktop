"""tenwin-shell main program."""

import logging
import shlex
import signal
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, Gio, GLib, Gtk, GtkLayerShell

from tenwin import paths, theme
from tenwin.apps import get_registry
from tenwin.config import get_settings
from tenwin.gtkutil import open_uri
from tenwin.i18n import _
from tenwin.services import system
from tenwin.services.audio import Audio
from tenwin.services.bluetooth import Bluetooth
from tenwin.services.display import Brightness, NightLight
from tenwin.services.network import Network
from tenwin.services.power import Power
from tenwin.shell.actioncenter import ActionCenter
from tenwin.shell.flyouts import BatteryFlyout, CalendarFlyout, NetworkFlyout, VolumeFlyout, WindowListPopup
from tenwin.shell.layer import ClickCatcher, Popup
from tenwin.shell.notifications import NotificationServer
from tenwin.shell.osd import OSD
from tenwin.shell.search import SearchPopup
from tenwin.shell.startmenu import StartMenu
from tenwin.shell.switcher import AltTab, SuperKey, TaskView
from tenwin.shell.taskbar import Taskbar
from tenwin.shell.tray import TrayHost
from tenwin.shell.windows import WindowManager
from tenwin.shell.winx import RunDialog, WinXMenu

log = logging.getLogger("tenwin.shell")

SHELL_XML = """
<node>
  <interface name="org.tenwin.Shell">
    <method name="Command"><arg type="s" name="command" direction="in"/></method>
  </interface>
</node>
"""

# Settings that change the taskbar layout.
TASKBAR_KEYS = {"taskbar.position", "taskbar.small_icons", "taskbar.search", "taskbar.show_taskview",
                "taskbar.tray_show_all", "input.keyboard_layouts", "region.clock_24h",
                "region.clock_seconds"}


class Shell:
    def __init__(self):
        self.settings = get_settings()
        theme.install("shell")
        self.apps = get_registry()
        self.wm = WindowManager()
        self.audio = Audio()
        self.network = Network()
        self.power = Power()
        self.bluetooth = Bluetooth()
        self.brightness = Brightness()
        self.nightlight = NightLight()
        self.current_monitor = None
        self.open_popup = None
        self.taskbars = {}
        Popup.manager = self

        self.notifications = NotificationServer(self)
        self.tray = TrayHost(self)
        self.start_menu = StartMenu(self)
        self.search = SearchPopup(self)
        self.action_center = ActionCenter(self)
        self.calendar = CalendarFlyout(self)
        self.volume_flyout = VolumeFlyout(self)
        self.network_flyout = NetworkFlyout(self)
        self.battery_flyout = BatteryFlyout(self)
        self.window_list = WindowListPopup(self)
        self.run_dialog = RunDialog(self)
        self.winx = WinXMenu(self)
        self.alt_tab = AltTab(self)
        self.task_view = TaskView(self)
        self.super_key = SuperKey(self)
        self.osd = OSD(self)
        self.catcher = ClickCatcher(self.close_popups)

        display = Gdk.Display.get_default()
        display.connect("monitor-added", lambda _d, m: self._add_taskbar(m))
        display.connect("monitor-removed", lambda _d, m: self._remove_taskbar(m))
        for i in range(display.get_n_monitors()):
            self._add_taskbar(display.get_monitor(i))
        self.current_monitor = display.get_primary_monitor() or display.get_monitor(0)

        for signal_name in ("window-added", "window-changed", "window-removed", "active-changed"):
            self.wm.connect(signal_name, self._on_windows_changed)
        self.apps.connect("changed", self._on_windows_changed)
        for service in (self.audio, self.network, self.power):
            service.connect("changed", lambda *_: self._update_status())
        self.settings.connect("changed", self._on_settings)
        self.nightlight.set(self.settings["nightlight.enabled"], self.settings["nightlight.temperature"])

        Gio.bus_own_name(Gio.BusType.SESSION, "org.tenwin.Shell", Gio.BusNameOwnerFlags.REPLACE,
                         self._on_bus, None, lambda *_: log.error("cannot own org.tenwin.Shell"))
        if not self.settings["session.first_run_done"]:
            GLib.timeout_add_seconds(2, self._first_run)

    # -- monitors / taskbars ---------------------------------------------

    def _add_taskbar(self, monitor):
        if monitor in self.taskbars:
            return
        self.taskbars[monitor] = Taskbar(self, monitor)

    def _remove_taskbar(self, monitor):
        taskbar = self.taskbars.pop(monitor, None)
        if taskbar is not None:
            taskbar.destroy()
        if self.current_monitor is monitor:
            display = Gdk.Display.get_default()
            self.current_monitor = display.get_primary_monitor() or display.get_monitor(0)

    def primary_taskbar(self):
        display = Gdk.Display.get_default()
        primary = display.get_primary_monitor()
        if primary in self.taskbars:
            return self.taskbars[primary]
        return next(iter(self.taskbars.values()), None)

    def _on_windows_changed(self, *_args):
        for taskbar in self.taskbars.values():
            taskbar.refresh_apps()

    def _update_status(self):
        for taskbar in self.taskbars.values():
            taskbar.update_status()

    def update_notification_badge(self):
        count = len(self.notifications.history)
        dnd = self.settings["notifications.focus_assist"]
        for taskbar in self.taskbars.values():
            taskbar.set_notification_count(count, dnd)

    def set_start_open(self, is_open):
        for taskbar in self.taskbars.values():
            taskbar.set_start_open(is_open)

    def _on_settings(self, _settings, keys):
        if keys & TASKBAR_KEYS:
            # Popups anchored to the taskbar edge must follow it.
            from tenwin.shell.layer import Edge, taskbar_edge
            edge = taskbar_edge()
            for popup in (self.start_menu, self.search, self.calendar, self.volume_flyout,
                          self.network_flyout, self.battery_flyout, self.window_list, self.tray.overflow,
                          self.run_dialog):
                anchors = (edge, Edge.RIGHT) if isinstance(popup, (CalendarFlyout, VolumeFlyout, NetworkFlyout,
                                                                   BatteryFlyout)) or popup is self.tray.overflow \
                    else (edge, Edge.LEFT)
                popup.set_anchors(anchors)
            for taskbar in self.taskbars.values():
                taskbar.rebuild()
        if "taskbar.pinned" in keys:
            self._on_windows_changed()
        if keys & {"nightlight.enabled", "nightlight.temperature"}:
            self.nightlight.set(self.settings["nightlight.enabled"], self.settings["nightlight.temperature"])
        if "notifications.focus_assist" in keys:
            self.update_notification_badge()
        if any(k.startswith(("appearance.", "input.", "desktops.", "region.language")) for k in keys):
            # labwc theme, keyboard and desktops are part of the generated config.
            GLib.idle_add(self._apply_session)

    def _apply_session(self):
        from tenwin import session
        try:
            session.apply()
        except Exception as exc:  # never let config generation kill the shell
            log.error("applying session settings failed: %s", exc)
        return GLib.SOURCE_REMOVE

    # -- popups -------------------------------------------------------------

    def toggle_popup(self, popup, monitor=None):
        if monitor is not None:
            self.current_monitor = monitor
        if popup.is_open():
            popup.close_popup()
        else:
            popup.open_popup(self.current_monitor)

    def popup_opened(self, popup):
        if self.open_popup is not None and self.open_popup is not popup:
            self.open_popup.close_popup()
        self.alt_tab.cancel()
        self.open_popup = popup
        if popup.catch_clicks:
            if self.current_monitor is not None:
                GtkLayerShell.set_monitor(self.catcher, self.current_monitor)
            self.catcher.show_all()

    def popup_closed(self, popup):
        if self.open_popup is popup:
            self.open_popup = None
            self.catcher.hide()

    def close_popups(self):
        if self.open_popup is not None:
            self.open_popup.close_popup()
        self.catcher.hide()

    # -- commands -------------------------------------------------------------

    def _on_bus(self, connection, _name):
        node = Gio.DBusNodeInfo.new_for_xml(SHELL_XML)
        connection.register_object("/org/tenwin/Shell", node.interfaces[0], self._on_call, None, None)

    def _on_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        if method == "Command":
            command = params.unpack()[0]
            GLib.idle_add(self._run_command, command)
            invocation.return_value(None)
        else:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)

    def _run_command(self, command):
        try:
            self.command(command)
        except Exception:
            log.exception("command %r failed", command)
        return GLib.SOURCE_REMOVE

    def command(self, command):
        parts = shlex.split(command)
        if not parts:
            return
        name, args = parts[0], parts[1:]
        if name not in ("super", "alt-tab", "alt-tab-back"):
            self.super_key.cancel()
        if name == "cancel":
            return
        handler = getattr(self, "cmd_" + name.replace("-", "_"), None)
        if handler is None:
            log.warning("unknown command %r", name)
            return
        handler(*args)

    def cmd_super(self):
        self.super_key.press()

    def cmd_start_menu(self):
        self.toggle_popup(self.start_menu)

    def cmd_search(self):
        self.toggle_popup(self.search)

    def cmd_action_center(self):
        self.toggle_popup(self.action_center)

    def cmd_tray(self):
        self.toggle_popup(self.tray.overflow)

    def cmd_run(self):
        self.toggle_popup(self.run_dialog)

    def cmd_winx(self):
        taskbar = self.primary_taskbar()
        if taskbar is not None:
            self.close_popups()
            self.winx.show_at(taskbar.start_button)

    def cmd_alt_tab(self):
        self.close_popups()
        self.alt_tab.step(1)

    def cmd_alt_tab_back(self):
        self.close_popups()
        self.alt_tab.step(-1)

    def cmd_task_view(self):
        self.task_view.toggle()

    def cmd_show_desktop(self):
        self.close_popups()
        self.wm.toggle_show_desktop()

    def cmd_minimize_all(self):
        self.wm.minimize_all()

    def cmd_maximize(self):
        self.wm.maximize_active()

    def cmd_restore_or_minimize(self):
        self.wm.restore_or_minimize_active()

    def cmd_explorer(self, *uris):
        self.close_popups()
        system.run([paths.binary("tenwin-explorer")] + list(uris))

    def cmd_settings(self, *pages):
        self.open_settings(pages[0] if pages else None)

    def open_settings(self, page=None):
        self.close_popups()
        argv = [paths.binary("tenwin-settings")]
        if page:
            argv.append("tenwin-settings:" + page)
        system.run(argv)

    def open_uri(self, uri):
        return open_uri(uri)

    def cmd_lock(self):
        self.close_popups()
        system.lock()

    def cmd_logout(self):
        system.logout()

    def cmd_suspend(self):
        system.suspend()

    def cmd_reboot(self):
        system.reboot()

    def cmd_poweroff(self):
        system.poweroff()

    def cmd_task_manager(self):
        system.task_manager()

    def cmd_screenshot(self):
        path = system.screenshot(callback=self._screenshot_done)
        if path is None:
            log.warning("screenshot failed (is grim installed?)")

    def cmd_snip(self):
        self.close_popups()
        system.screenshot(region=True, callback=self._snip_done)

    def _screenshot_done(self, path):
        self.notifications.notify(_("Screen snip"), 0, "tenwin-snip", _("Screenshot saved"),
                                  path, [], {"transient": True}, 4000)

    def _snip_done(self, path):
        self.notifications.notify(_("Screen snip"), 0, "tenwin-snip", _("Snip copied to clipboard"),
                                  _("Saved to %s") % path, [], {"transient": True}, 4000)
        return False

    def cmd_volume(self, direction):
        if direction == "up":
            self.audio.change_volume(2 if self.audio.volume < 10 else 5)
        elif direction == "down":
            self.audio.change_volume(-2 if self.audio.volume <= 10 else -5)
        elif direction == "mute":
            self.audio.toggle_mute()
        muted = self.audio.muted if direction != "mute" else not self.audio.muted
        icon = "tenwin-volume-muted" if muted else self.audio.icon_name()
        self.osd.show_level(icon, 0 if muted else self.audio.volume)

    def cmd_mic_mute(self):
        self.audio.toggle_source_mute()

    def cmd_brightness(self, direction):
        self.brightness.refresh()
        self.brightness.change(10 if direction == "up" else -10)
        self.osd.show_level("tenwin-brightness", self.brightness.percent)

    def cmd_taskbar_item(self, number):
        taskbar = self.primary_taskbar()
        if taskbar is None:
            return
        buttons = list(taskbar.app_buttons.values())
        index = int(number) - 1
        if 0 <= index < len(buttons):
            buttons[index].activate()

    def cmd_reload(self):
        self.apps.reload()
        self.start_menu.populate()

    # -- first run ----------------------------------------------------------

    def _first_run(self):
        system.run([paths.binary("tenwin-settings"), "--welcome"])
        return GLib.SOURCE_REMOVE


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    GLib.set_prgname("tenwin-shell")
    Gtk.init(sys.argv)
    if not GtkLayerShell.is_supported():
        log.error("The compositor does not support wlr-layer-shell; tenwin-shell needs labwc.")
        return 1
    shell = Shell()
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: Gtk.main_quit() or False)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, lambda: Gtk.main_quit() or False)
    Gtk.main()
    shell.nightlight.stop()
    return 0
