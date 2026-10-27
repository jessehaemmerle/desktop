"""Taskbar search flyout (apps, settings, files)."""

import os

from gi.repository import Gdk, Gio, GLib, Gtk, GtkLayerShell, Pango

from tenwin import settings_index
from tenwin.config import get_settings
from tenwin.gtkutil import add_class, clear_children, flat_button, icon_image, set_class
from tenwin.i18n import _
from tenwin.search_providers import FileIndex, search_apps
from tenwin.shell.layer import Edge, Popup, taskbar_edge, taskbar_height

TABS = [("all", "All"), ("apps", "Apps"), ("documents", "Documents"), ("settings", "Settings"),
        ("folders", "Folders")]


class Result:
    def __init__(self, kind, title, subtitle, icon, activate, data=None):
        self.kind = kind          # app | setting | file | folder
        self.title = title
        self.subtitle = subtitle
        self.icon = icon
        self.activate = activate
        self.data = data


class SearchPopup(Popup):
    def __init__(self, shell):
        super().__init__("tenwin-search", anchors=(taskbar_edge(), Edge.LEFT))
        self.shell = shell
        self.files = FileIndex()
        self.tab = "all"
        self.results = []
        self.selected = 0
        self._search_id = 0
        self._build()
        GtkLayerShell.set_exclusive_zone(self, -1)  # cover the taskbar search box
        self.connect("key-press-event", self._on_key)

    def _build(self):
        frame = add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "tw-panel")
        frame.set_size_request(760, 600)
        self.add(frame)
        top = get_settings()["taskbar.position"] == "top"

        tabs = add_class(Gtk.Box(), "tw-search-tabs")
        self.tab_buttons = {}
        for key, label in TABS:
            button = flat_button(Gtk.Label(label=_(label)))
            button.connect("clicked", lambda _b, k=key: self.set_tab(k))
            tabs.pack_start(button, False, False, 0)
            self.tab_buttons[key] = button
        frame.pack_start(tabs, False, False, 0)
        frame.pack_start(Gtk.Separator(), False, False, 0)

        body = Gtk.Box()
        frame.pack_start(body, True, True, 0)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_size_request(400, -1)
        self.result_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        scroll.add(self.result_box)
        body.pack_start(scroll, False, False, 0)
        self.detail = add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "tw-search-detail")
        body.pack_start(self.detail, True, True, 0)

        bar = add_class(Gtk.Box(spacing=8), "tw-search-entry-bar")
        bar.set_size_request(-1, taskbar_height())
        icon = icon_image("tenwin-search", 16, symbolic=True)
        icon.set_margin_start(12)
        bar.pack_start(icon, False, False, 0)
        self.entry = Gtk.Entry(placeholder_text=_("Type here to search"))
        self.entry.connect("changed", self._on_changed)
        self.entry.connect("activate", lambda *_: self._activate_selected())
        bar.pack_start(self.entry, True, True, 0)
        if top:
            frame.pack_start(bar, False, False, 0)
            frame.reorder_child(bar, 0)
        else:
            frame.pack_end(bar, False, False, 0)

    # -- Popup hooks ---------------------------------------------------------

    def on_open(self):
        self.files.ensure()
        self.set_margins(left=48)
        self.set_tab("all", refresh=False)
        self.refresh()

    def after_show(self):
        self.entry.grab_focus()
        self.entry.set_position(-1)

    def open_with_text(self, text, monitor=None):
        self.entry.set_text(text)
        self.open_popup(monitor)

    def on_close(self):
        self.entry.set_text("")

    # -- searching -----------------------------------------------------------

    def set_tab(self, key, refresh=True):
        self.tab = key
        for k, button in self.tab_buttons.items():
            set_class(button, "selected", k == key)
        if refresh:
            self.refresh()

    def _on_changed(self, *_args):
        if self._search_id:
            GLib.source_remove(self._search_id)
        self._search_id = GLib.timeout_add(60, self._delayed)

    def _delayed(self):
        self._search_id = 0
        self.refresh()
        return GLib.SOURCE_REMOVE

    def refresh(self):
        query = self.entry.get_text().strip()
        results = []
        tab = self.tab
        if not query:
            results = [self._app_result(i) for i in (self.shell.apps.most_used(8) or self.shell.apps.apps[:8])]
            self._show(results, _("Top apps"))
            return
        if tab in ("all", "apps"):
            results += [self._app_result(i) for i in search_apps(self.shell.apps.apps, query,
                                                                 8 if tab == "all" else 30)]
        if tab in ("all", "settings"):
            for page_id, title, category, icon in settings_index.search(query, 5 if tab == "all" else 30):
                results.append(Result("setting", title, _("Settings") + " › " + category, icon,
                                      lambda p=page_id: self.shell.open_settings(p)))
        if tab in ("all", "documents", "folders"):
            dirs = {"documents": False, "folders": True}.get(tab)
            for path, is_dir in self.files.search(query, 8 if tab == "all" else 40, dirs):
                results.append(self._file_result(path, is_dir))
        self._show(results, None)

    def _app_result(self, info):
        return Result("app", info.get_display_name(), _("App"), info.get_icon(),
                      lambda: self.shell.apps.launch(info), info)

    def _file_result(self, path, is_dir):
        gfile = Gio.File.new_for_path(path)
        icon = None
        try:
            finfo = gfile.query_info("standard::icon", Gio.FileQueryInfoFlags.NONE, None)
            icon = finfo.get_icon()
        except GLib.Error:
            pass
        home = os.path.expanduser("~")
        location = os.path.dirname(path)
        if location.startswith(home):
            location = "~" + location[len(home):]
        kind = "folder" if is_dir else "file"
        if is_dir:
            activate = lambda: self.shell.command("explorer " + gfile.get_uri())
        else:
            activate = lambda: self.shell.open_uri(gfile.get_uri())
        return Result(kind, os.path.basename(path), location, icon or "text-x-generic", activate, path)

    def _show(self, results, title):
        clear_children(self.result_box)
        self.results = results
        self.selected = 0
        if not results:
            empty = add_class(Gtk.Label(label=_("No results found for \"%s\"") % self.entry.get_text(),
                                        wrap=True, xalign=0), "tw-search-empty")
            empty.set_margin_start(16)
            empty.set_margin_top(16)
            self.result_box.pack_start(empty, False, False, 0)
            self.result_box.show_all()
            self._show_detail(None)
            return
        self.rows = []
        header_shown = set()
        for index, result in enumerate(results):
            if title and index == 0:
                self.result_box.pack_start(self._header(title), False, False, 0)
            elif not title:
                section = _("Best match") if index == 0 else {
                    "app": _("Apps"), "setting": _("Settings"), "file": _("Documents"),
                    "folder": _("Folders")}[result.kind]
                if section not in header_shown:
                    header_shown.add(section)
                    self.result_box.pack_start(self._header(section), False, False, 0)
            row = self._row(result, index, big=(index == 0 and not title))
            self.rows.append(row)
            self.result_box.pack_start(row, False, False, 0)
        self.result_box.show_all()
        self._select(0)

    def _header(self, text):
        return add_class(Gtk.Label(label=text, xalign=0), "tw-section-title")

    def _row(self, result, index, big=False):
        button = flat_button(css="tw-result")
        box = Gtk.Box(spacing=12)
        box.pack_start(icon_image(result.icon, 32 if big else 24, symbolic=result.kind == "setting"),
                       False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        text.set_valign(Gtk.Align.CENTER)
        title = add_class(Gtk.Label(label=result.title, xalign=0), "tw-result-title")
        title.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        text.pack_start(title, False, False, 0)
        if big or result.kind in ("file", "folder", "setting"):
            sub = add_class(Gtk.Label(label=result.subtitle, xalign=0), "tw-result-sub")
            sub.set_ellipsize(Pango.EllipsizeMode.START)
            text.pack_start(sub, False, False, 0)
        box.pack_start(text, True, True, 0)
        button.add(box)
        button.connect("clicked", lambda *_: self._activate(result))
        button.connect("enter-notify-event", lambda *_: self._select(index) and False)
        return button

    def _select(self, index):
        if not self.results:
            return
        self.selected = max(0, min(index, len(self.results) - 1))
        for i, row in enumerate(getattr(self, "rows", [])):
            set_class(row, "selected", i == self.selected)
        self._show_detail(self.results[self.selected])

    def _show_detail(self, result):
        clear_children(self.detail)
        if result is None:
            return
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(32)
        box.pack_start(icon_image(result.icon, 64, symbolic=result.kind == "setting"), False, False, 0)
        title = add_class(Gtk.Label(label=result.title, justify=Gtk.Justification.CENTER), "tw-detail-title")
        title.set_line_wrap(True)
        title.set_max_width_chars(26)
        box.pack_start(title, False, False, 0)
        kind_text = {"app": _("App"), "setting": _("System settings"), "file": _("File"),
                     "folder": _("File folder")}[result.kind]
        box.pack_start(add_class(Gtk.Label(label=kind_text), "tw-dim-text"), False, False, 0)
        if result.kind in ("file", "folder"):
            loc = add_class(Gtk.Label(label=result.subtitle), "tw-dim-text")
            loc.set_ellipsize(Pango.EllipsizeMode.START)
            loc.set_max_width_chars(36)
            box.pack_start(loc, False, False, 0)
        self.detail.pack_start(box, False, False, 0)
        self.detail.pack_start(Gtk.Separator(margin_top=16, margin_bottom=8, margin_start=24, margin_end=24),
                               False, False, 0)
        actions = [(_("Open"), "tenwin-open", lambda: self._activate(result))]
        if result.kind == "app":
            info = result.data
            start = self.shell.start_menu
            if start.is_pinned_start(info):
                actions.append((_("Unpin from Start"), "tenwin-unpin", lambda: start.pin_start(info, False)))
            else:
                actions.append((_("Pin to Start"), "tenwin-pin", lambda: start.pin_start(info, True)))
            if self.shell.apps.is_pinned(info):
                actions.append((_("Unpin from taskbar"), "tenwin-unpin",
                                lambda: self.shell.apps.set_pinned(info, False)))
            else:
                actions.append((_("Pin to taskbar"), "tenwin-pin", lambda: self.shell.apps.set_pinned(info, True)))
        elif result.kind in ("file", "folder"):
            folder = os.path.dirname(result.data)
            actions.append((_("Open file location"), "tenwin-folder",
                            lambda: self.shell.command("explorer " + Gio.File.new_for_path(folder).get_uri())))
            actions.append((_("Copy full path"), "tenwin-copy", lambda: self._copy(result.data)))
        for text, icon, callback in actions:
            button = flat_button(css="tw-detail-action")
            row = Gtk.Box(spacing=12)
            row.pack_start(icon_image(icon, 16, symbolic=True), False, False, 0)
            row.pack_start(Gtk.Label(label=text, xalign=0), True, True, 0)
            button.add(row)
            button.connect("clicked", lambda _b, cb=callback: (cb(), self.refresh()))
            self.detail.pack_start(button, False, False, 0)
        self.detail.show_all()

    def _copy(self, text):
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)

    def _activate(self, result):
        self.close_popup()
        result.activate()

    def _activate_selected(self):
        if self.results:
            self._activate(self.results[self.selected])

    def _on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Down:
            self._select(self.selected + 1)
            return True
        if event.keyval == Gdk.KEY_Up:
            self._select(self.selected - 1)
            return True
        return False

