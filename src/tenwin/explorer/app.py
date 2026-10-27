"""tenwin-explorer: application entry point."""

import logging
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gio, GLib, Gtk

from tenwin import theme
from tenwin.i18n import _

log = logging.getLogger("tenwin.explorer")


class ExplorerApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.tenwin.Explorer",
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.add_main_option("new-window", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             _("Open a new window"), None)
        self.add_main_option("properties", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             _("Show the properties of the given files"), None)
        self.add_main_option("empty-trash", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             _("Empty the Recycle Bin"), None)
        self._styled = False

    def do_startup(self):
        Gtk.Application.do_startup(self)
        GLib.set_application_name(_("File Explorer"))

    def _style(self):
        if not self._styled:
            theme.install("explorer")
            self._styled = True

    def open_window(self, uri=None):
        from tenwin.explorer.window import ExplorerWindow
        self._style()
        window = ExplorerWindow(self, uri)
        window.present()
        return window

    def do_command_line(self, command_line):
        options = command_line.get_options_dict().end().unpack()
        args = command_line.get_arguments()[1:]
        files = [command_line.create_file_for_arg(a) for a in args if not a.startswith("--")]
        self._style()
        if options.get("empty-trash"):
            from tenwin.explorer.window import empty_trash
            dialog = Gtk.MessageDialog(message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.YES_NO,
                                       text=_("Are you sure you want to permanently delete all items in the "
                                              "Recycle Bin?"))
            dialog.set_title(_("Delete Multiple Items"))
            if dialog.run() == Gtk.ResponseType.YES:
                empty_trash()
            dialog.destroy()
            return 0
        if options.get("properties"):
            from tenwin.explorer.properties import PropertiesDialog
            if files:
                dialog = PropertiesDialog(files)
                self.add_window(dialog)
            return 0
        if files:
            for gfile in files:
                info_type = gfile.query_file_type(Gio.FileQueryInfoFlags.NONE, None)
                if info_type == Gio.FileType.DIRECTORY or gfile.get_uri_scheme() in ("trash", "computer",
                                                                                     "network", "tenwin"):
                    self.open_window(gfile.get_uri())
                else:
                    parent = gfile.get_parent()
                    window = self.open_window(parent.get_uri() if parent else None)
                    name = gfile.get_basename()
                    GLib.timeout_add(500, lambda w=window, n=name: w._select_name(n) and False)
        else:
            self.open_window()
        return 0


def main():
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    GLib.set_prgname("org.tenwin.Explorer")
    app = ExplorerApp()
    return app.run(sys.argv)
