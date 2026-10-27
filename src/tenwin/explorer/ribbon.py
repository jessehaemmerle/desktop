"""The Explorer ribbon (Windows 10 style)."""

from gi.repository import Gtk

from tenwin.config import get_settings
from tenwin.gtkutil import add_class, flat_button, icon_image, set_class
from tenwin.i18n import _, pgettext


def big_button(icon, text, callback, tooltip=None):
    button = flat_button(css="tw-rb-big", tooltip=tooltip or text.replace("\n", " "))
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.pack_start(icon_image(icon, 32, symbolic=True), False, False, 0)
    label = Gtk.Label(label=text, justify=Gtk.Justification.CENTER)
    box.pack_start(label, False, False, 0)
    button.add(box)
    button.connect("clicked", lambda *_: callback())
    return button


def small_button(icon, text, callback):
    button = flat_button(css="tw-rb-small", tooltip=text)
    box = Gtk.Box(spacing=6)
    box.pack_start(icon_image(icon, 16, symbolic=True), False, False, 0)
    box.pack_start(Gtk.Label(label=text, xalign=0), False, False, 0)
    button.add(box)
    button.connect("clicked", lambda *_: callback())
    return button


def check(text, active, callback):
    button = Gtk.CheckButton(label=text)
    button.set_active(active)
    button.connect("toggled", lambda b: callback(b.get_active()))
    add_class(button, "tw-rb-check")
    return button


def group(title, *columns):
    outer = add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "tw-rb-group")
    row = Gtk.Box(spacing=2)
    for col in columns:
        if isinstance(col, (list, tuple)):
            stack = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            for widget in col:
                stack.pack_start(widget, False, False, 0)
            row.pack_start(stack, False, False, 0)
        else:
            row.pack_start(col, False, False, 0)
    outer.pack_start(row, True, True, 0)
    outer.pack_end(add_class(Gtk.Label(label=title), "tw-rb-group-title"), False, False, 0)
    return outer


class Ribbon(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.settings = get_settings()
        add_class(self, "tw-ribbon")
        self.tabs = add_class(Gtk.Box(), "tw-rb-tabs")
        self.pack_start(self.tabs, False, False, 0)
        self.revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN,
                                     transition_duration=120)
        self.stack = add_class(Gtk.Stack(), "tw-rb-panel")
        self.revealer.add(self.stack)
        self.pack_start(self.revealer, False, False, 0)
        self.tab_buttons = {}
        self.current = "home"

        file_tab = flat_button(Gtk.Label(label=_("File")), "tw-rb-file")
        file_tab.connect("clicked", lambda b: window.show_file_menu(b))
        self.tabs.pack_start(file_tab, False, False, 0)
        for key, text in (("home", pgettext("ribbon", "Home")), ("share", _("Share")), ("view", _("View")),
                          ("trash", _("Recycle Bin Tools"))):
            button = flat_button(Gtk.Label(label=text), "tw-rb-tab")
            button.connect("clicked", lambda _b, k=key: self.select(k))
            self.tabs.pack_start(button, False, False, 0)
            self.tab_buttons[key] = button
        self.toggle_button = flat_button(icon_image("tenwin-chevron-down", 10, symbolic=True), "tw-rb-toggle",
                                         _("Expand the Ribbon (Ctrl+F1)"))
        self.toggle_button.connect("clicked", lambda *_: self.set_expanded(not self.revealer.get_reveal_child()))
        self.tabs.pack_end(self.toggle_button, False, False, 0)

        self.stack.add_named(self._home(), "home")
        self.stack.add_named(self._share(), "share")
        self.stack.add_named(self._view(), "view")
        self.stack.add_named(self._trash(), "trash")
        self.set_context(trash=False)
        self.set_expanded(self.settings["explorer.ribbon_expanded"], save=False)

    # -- tabs ----------------------------------------------------------------

    def _home(self):
        w = self.window
        box = Gtk.Box(spacing=0)
        box.pack_start(group(_("Clipboard"),
                             big_button("tenwin-pin", _("Pin to Quick\naccess"), w.pin_quick_access),
                             big_button("tenwin-copy", _("Copy"), w.copy),
                             big_button("tenwin-paste", _("Paste"), w.paste),
                             [small_button("tenwin-cut", _("Cut"), w.cut),
                              small_button("tenwin-copy", _("Copy path"), w.copy_path)]), False, False, 0)
        box.pack_start(group(_("Organize"),
                             big_button("tenwin-arrow-right", _("Move\nto"), w.move_to),
                             big_button("tenwin-copy", _("Copy\nto"), w.copy_to),
                             big_button("tenwin-delete", _("Delete"), w.delete),
                             big_button("tenwin-rename", _("Rename"), w.rename)), False, False, 0)
        box.pack_start(group(_("New"),
                             big_button("tenwin-new-folder", _("New\nfolder"), w.new_folder),
                             [small_button("tenwin-new-item", _("New item"), w.new_text_file)]), False, False, 0)
        box.pack_start(group(_("Open"),
                             big_button("tenwin-properties", _("Properties"), w.properties),
                             [small_button("tenwin-open", _("Open"), w.open_selected),
                              small_button("tenwin-terminal", _("Open in Terminal"), w.open_terminal)]),
                       False, False, 0)
        box.pack_start(group(_("Select"),
                             [small_button("tenwin-select-all", _("Select all"), w.select_all),
                              small_button("tenwin-select-none", _("Select none"), w.select_none),
                              small_button("tenwin-select-invert", _("Invert selection"), w.invert_selection)]),
                       False, False, 0)
        return box

    def _share(self):
        w = self.window
        box = Gtk.Box()
        box.pack_start(group(_("Send"),
                             big_button("tenwin-mail", _("Email"), w.email),
                             big_button("tenwin-zip", _("Zip"), w.compress)), False, False, 0)
        box.pack_start(group(_("Extract"),
                             big_button("tenwin-zip", _("Extract\nall"), w.extract)), False, False, 0)
        return box

    def _view(self):
        w = self.window
        s = self.settings
        box = Gtk.Box()
        box.pack_start(group(_("Panes"),
                             big_button("tenwin-view-list", _("Navigation\npane"),
                                        lambda: s.set("explorer.nav_pane", not s["explorer.nav_pane"]))),
                       False, False, 0)
        layouts = [("xl", _("Extra large icons")), ("large", _("Large icons")), ("medium", _("Medium icons")),
                   ("small", _("Small icons")), ("list", _("List")), ("details", _("Details"))]
        self.layout_buttons = {}
        col1, col2 = [], []
        for i, (key, text) in enumerate(layouts):
            icon = "tenwin-view-details" if key == "details" else (
                "tenwin-view-list" if key in ("list", "small") else "tenwin-view-icons")
            button = small_button(icon, text, lambda k=key: s.set("explorer.view", k))
            self.layout_buttons[key] = button
            (col1 if i % 2 == 0 else col2).append(button)
        box.pack_start(group(_("Layout"), col1, col2), False, False, 0)
        sort = big_button("tenwin-view-list", _("Sort\nby"), lambda: w.show_sort_menu(sort))
        box.pack_start(group(_("Current view"), sort), False, False, 0)
        self.ext_check = check(_("File name extensions"), s["explorer.show_extensions"],
                               lambda v: s.set("explorer.show_extensions", v))
        self.hidden_check = check(_("Hidden items"), s["explorer.show_hidden"],
                                  lambda v: s.set("explorer.show_hidden", v))
        box.pack_start(group(_("Show/hide"), [self.ext_check, self.hidden_check]), False, False, 0)
        self.update_layout()
        return box

    def _trash(self):
        w = self.window
        box = Gtk.Box()
        box.pack_start(group(_("Manage"),
                             big_button("tenwin-trash", _("Empty\nRecycle Bin"), w.empty_trash),
                             big_button("tenwin-restart", _("Restore all\nitems"), w.restore_all),
                             big_button("tenwin-arrow-up", _("Restore the\nselected items"), w.restore_selected)),
                       False, False, 0)
        return box

    # -- state ----------------------------------------------------------------

    def update_layout(self):
        view = self.settings["explorer.view"]
        for key, button in self.layout_buttons.items():
            set_class(button, "selected", key == view)

    def select(self, key):
        if self.current == key and self.revealer.get_reveal_child() and not self.settings["explorer.ribbon_expanded"]:
            self.revealer.set_reveal_child(False)
            return
        self.current = key
        self.stack.set_visible_child_name(key)
        for k, button in self.tab_buttons.items():
            set_class(button, "selected", k == key)
        self.revealer.set_reveal_child(True)

    def collapse_if_temporary(self):
        if not self.settings["explorer.ribbon_expanded"]:
            self.revealer.set_reveal_child(False)

    def set_expanded(self, expanded, save=True):
        self.revealer.set_reveal_child(expanded)
        if expanded:
            self.select(self.current)
        from tenwin.gtkutil import set_icon
        set_icon(self.toggle_button.get_child(), "tenwin-chevron-up" if expanded else "tenwin-chevron-down", 10,
                 symbolic=True)
        self.toggle_button.set_tooltip_text(_("Minimize the Ribbon (Ctrl+F1)") if expanded
                                            else _("Expand the Ribbon (Ctrl+F1)"))
        if save:
            self.settings.set("explorer.ribbon_expanded", expanded)

    def set_context(self, trash):
        button = self.tab_buttons["trash"]
        button.set_visible(trash)
        button.set_no_show_all(not trash)
        if self.current == "trash" and not trash:
            self.current = "home"
            self.stack.set_visible_child_name("home")
            for k, button in self.tab_buttons.items():
                set_class(button, "selected", k == "home")
