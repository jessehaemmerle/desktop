"""Win+X menu (right click on Start) and the Run dialog (Win+R)."""

import os
import shutil

from gi.repository import Gio, GLib, Gtk

from tenwin.config import State
from tenwin.gtkutil import add_class, flat_button, icon_image, menu_item, popup_menu
from tenwin.i18n import _
from tenwin.services import system
from tenwin.shell.layer import Edge, Popup, taskbar_edge


class WinXMenu:
    def __init__(self, shell):
        self.shell = shell

    def _entries(self):
        s = self.shell

        def tool(*candidates):
            for argv in candidates:
                if shutil.which(argv[0]):
                    return lambda a=argv: system.run(a)
            return None

        return [
            (_("Apps and Features"), lambda: s.open_settings("apps-features")),
            (_("Power Options"), lambda: s.open_settings("power")),
            (_("Event Viewer"), tool(["gnome-logs"])),
            (_("System"), lambda: s.open_settings("about")),
            (_("Device Manager"), tool(["hardinfo2"], ["hardinfo"])),
            (_("Network Connections"), tool(["nm-connection-editor"])),
            (_("Disk Management"), tool(["gnome-disks"])),
            (_("Terminal"), lambda: system.open_terminal()),
            None,
            (_("Task Manager"), lambda: s.command("task-manager")),
            (_("Settings"), lambda: s.command("settings")),
            (_("File Explorer"), lambda: s.command("explorer")),
            (_("Search"), lambda: s.command("search")),
            (_("Run"), lambda: s.command("run")),
            None,
            "power",
            (_("Desktop"), lambda: s.command("show-desktop")),
        ]

    def show_at(self, widget):
        menu = Gtk.Menu()
        for entry in self._entries():
            if entry is None:
                menu.append(Gtk.SeparatorMenuItem())
            elif entry == "power":
                item = Gtk.MenuItem(label=_("Shut down or sign out"))
                sub = Gtk.Menu()
                add_class(sub, "tw-menu")
                sub.append(menu_item(_("Sign out"), lambda: self.shell.command("logout")))
                sub.append(menu_item(_("Sleep"), lambda: self.shell.command("suspend")))
                sub.append(menu_item(_("Shut down"), lambda: self.shell.command("poweroff")))
                sub.append(menu_item(_("Restart"), lambda: self.shell.command("reboot")))
                item.set_submenu(sub)
                menu.append(item)
            else:
                label, callback = entry
                if callback is not None:
                    menu.append(menu_item(label, callback))
        popup_menu(menu, widget=widget)


class RunDialog(Popup):
    HISTORY = 20

    def __init__(self, shell):
        super().__init__("tenwin-run", anchors=(taskbar_edge(), Edge.LEFT), css="tw-surface", catch_clicks=False)
        self.shell = shell
        self.set_margins(left=12, bottom=12, top=12)
        frame = add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "tw-run")
        frame.set_size_request(400, -1)
        self.add(frame)

        title = add_class(Gtk.Box(spacing=8), "tw-run-title")
        title.pack_start(icon_image("tenwin-run", 16, symbolic=True), False, False, 0)
        title.pack_start(Gtk.Label(label=_("Run"), xalign=0), True, True, 0)
        close = flat_button(icon_image("tenwin-close", 10, symbolic=True), "tw-run-close")
        close.connect("clicked", lambda *_: self.close_popup())
        title.pack_end(close, False, False, 0)
        frame.pack_start(title, False, False, 0)

        body = Gtk.Grid(column_spacing=12, row_spacing=14)
        body.set_margin_start(16)
        body.set_margin_end(16)
        body.set_margin_top(12)
        body.set_margin_bottom(18)
        body.attach(icon_image("tenwin-run", 32, symbolic=True), 0, 0, 1, 1)
        text = Gtk.Label(label=_("Type the name of a program, folder, document, or Internet resource, "
                                 "and Tenwin will open it for you."), xalign=0, wrap=True)
        text.set_max_width_chars(44)
        body.attach(text, 1, 0, 2, 1)
        body.attach(Gtk.Label(label=_("Open:"), xalign=0), 0, 1, 1, 1)
        self.combo = Gtk.ComboBoxText.new_with_entry()
        self.combo.set_hexpand(True)
        self.entry = self.combo.get_child()
        self.entry.connect("activate", lambda *_: self.run())
        body.attach(self.combo, 1, 1, 2, 1)
        self.error = Gtk.Label(xalign=0, wrap=True)
        self.error.set_no_show_all(True)
        body.attach(self.error, 1, 2, 2, 1)
        frame.pack_start(body, False, False, 0)

        footer = add_class(Gtk.Box(spacing=8), "tw-run-footer")
        for label, callback in ((_("Browse..."), self.browse), (_("Cancel"), self.close_popup),
                                (_("OK"), self.run)):
            button = Gtk.Button(label=label)
            button.connect("clicked", lambda _b, cb=callback: cb())
            footer.pack_end(button, False, False, 0)
        frame.pack_start(footer, False, False, 0)

    def on_open(self):
        self.combo.remove_all()
        history = State().get("run_history") or []
        for item in history:
            self.combo.append_text(item)
        self.entry.set_text(history[0] if history else "")
        self.error.hide()

    def after_show(self):
        self.entry.grab_focus()
        self.entry.select_region(0, -1)

    def browse(self):
        dialog = Gtk.FileChooserNative.new(_("Browse"), None, Gtk.FileChooserAction.OPEN, _("Open"), _("Cancel"))
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            self.entry.set_text(GLib.shell_quote(dialog.get_filename()))
        dialog.destroy()

    def run(self):
        text = self.entry.get_text().strip()
        if not text:
            return
        if self._launch(text):
            State().modify("run_history",
                           lambda old: [text] + [h for h in (old or []) if h != text][: self.HISTORY - 1])
            self.close_popup()
        else:
            self.error.set_text(_("Tenwin cannot find '%s'. Make sure you typed the name correctly, "
                                  "and then try again.") % text)
            self.error.show()

    def _launch(self, text):
        expanded = os.path.expanduser(os.path.expandvars(text))
        if "://" in text or text.startswith(("mailto:", "www.")):
            return self.shell.open_uri(text if "://" in text or text.startswith("mailto:") else "https://" + text)
        if os.path.isdir(expanded):
            self.shell.command("explorer " + Gio.File.new_for_path(expanded).get_uri())
            return True
        if os.path.isfile(expanded) and not os.access(expanded, os.X_OK):
            return self.shell.open_uri(Gio.File.new_for_path(expanded).get_uri())
        try:
            argv = GLib.shell_parse_argv(text)[1]
        except GLib.Error:
            return False
        if not argv or not (shutil.which(os.path.expanduser(argv[0]))):
            return False
        argv[0] = os.path.expanduser(argv[0])
        return system.run(argv)

