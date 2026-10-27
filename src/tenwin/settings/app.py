"""tenwin-settings: the Settings app and the first-run welcome dialog."""

import logging
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gio, GLib, Gtk, Pango

from tenwin import settings_index, theme
from tenwin.config import get_settings
from tenwin.gtkutil import add_class, clear_children, flat_button, icon_image, set_class
from tenwin.i18n import _
from tenwin.settings.pages import PAGE_BUILDERS
from tenwin.settings.widgets import nav_row

log = logging.getLogger("tenwin.settings")


class SettingsWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=_("Settings"))
        add_class(self, "tw-app-window", "tw-settings")
        self.set_default_size(1020, 700)
        self.set_icon_name("org.tenwin.Settings")
        self.current_page = None
        self.current_category = None
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=100)
        self.add(self.stack)
        self.stack.add_named(self._home(), "home")
        self.category_view = Gtk.Box()
        self.stack.add_named(self.category_view, "category")
        self.connect("key-press-event", self._on_key)
        self.show_all()

    # -- home -----------------------------------------------------------------

    def _home(self):
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(28)
        box.set_halign(Gtk.Align.CENTER)
        title = add_class(Gtk.Label(label=_("Windows Settings").replace("Windows", "Tenwin")), "tw-h1")
        box.pack_start(title, False, False, 0)
        self.home_search = self._search_entry()
        self.home_search.set_size_request(380, -1)
        self.home_search.set_halign(Gtk.Align.CENTER)
        box.pack_start(self.home_search, False, False, 12)
        grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=4, row_spacing=4)
        grid.set_max_children_per_line(5)
        grid.set_min_children_per_line(2)
        grid.set_homogeneous(True)
        for cat_id, title, subtitle, icon in settings_index.CATEGORIES:
            button = flat_button(css="tw-set-tile")
            inner = Gtk.Box(spacing=14)
            image = add_class(icon_image(icon, 32, symbolic=True), "tw-set-tile-icon")
            image.set_valign(Gtk.Align.START)
            inner.pack_start(image, False, False, 0)
            texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            texts.pack_start(Gtk.Label(label=_(title), xalign=0), False, False, 0)
            sub = add_class(Gtk.Label(label=_(subtitle), xalign=0, wrap=True), "tw-dim")
            sub.set_max_width_chars(22)
            sub.set_lines(2)
            sub.set_ellipsize(Pango.EllipsizeMode.END)
            texts.pack_start(sub, False, False, 0)
            inner.pack_start(texts, True, True, 0)
            button.add(inner)
            button.set_size_request(240, 88)
            button.connect("clicked", lambda _b, c=cat_id: self.show_category(c))
            grid.add(button)
        box.pack_start(grid, False, False, 12)
        scroll.add(box)
        return scroll

    def _search_entry(self):
        entry = add_class(Gtk.SearchEntry(placeholder_text=_("Find a setting")), "tw-set-search")
        completion = Gtk.EntryCompletion()
        store = Gtk.ListStore(str, str)
        for page_id, cat, title, _icon, _kw in settings_index.PAGES:
            store.append(["%s (%s)" % (_(title), settings_index.category_title(cat)), page_id])
        completion.set_model(store)
        completion.set_text_column(0)
        completion.set_match_func(lambda _c, key, it: bool(settings_index.search(key)) and
                                  store[it][1] in [r[0] for r in settings_index.search(key, 30)], None)
        completion.connect("match-selected", lambda _c, model, it: (self.show_page(model[it][1]), True)[1])
        entry.set_completion(completion)
        entry.connect("activate", self._on_search)
        return entry

    def _on_search(self, entry):
        results = settings_index.search(entry.get_text(), 1)
        if results:
            self.show_page(results[0][0])

    # -- categories / pages ------------------------------------------------

    def show_category(self, cat_id, page_id=None):
        pages = settings_index.pages_for(cat_id)
        if not pages:
            return
        page_id = page_id or pages[0][0]
        if self.current_category != cat_id:
            self.current_category = cat_id
            clear_children(self.category_view)
            nav = add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "tw-set-nav")
            nav.set_size_request(300, -1)
            home = flat_button(css="tw-set-home")
            home_box = Gtk.Box(spacing=16)
            home_box.pack_start(icon_image("tenwin-home", 16, symbolic=True), False, False, 0)
            home_box.pack_start(Gtk.Label(label=_("Home"), xalign=0), True, True, 0)
            home.add(home_box)
            home.connect("clicked", lambda *_: self.show_home())
            nav.pack_start(home, False, False, 8)
            search = self._search_entry()
            search.set_margin_start(16)
            search.set_margin_end(16)
            nav.pack_start(search, False, False, 4)
            nav.pack_start(add_class(Gtk.Label(label=settings_index.category_title(cat_id), xalign=0),
                                     "tw-set-cat-title"), False, False, 10)
            self.nav_list = add_class(Gtk.ListBox(), "tw-set-nav-list")
            self.nav_rows = {}
            for pid, _cat, title, icon, _kw in pages:
                row = nav_row(icon, _(title))
                self.nav_rows[pid] = row
                self.nav_list.add(row)
            self.nav_list.connect("row-activated", lambda _l, row: self._open_row(row))
            nav.pack_start(self.nav_list, False, False, 0)
            self.category_view.pack_start(nav, False, False, 0)
            self.page_scroll = add_class(Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER), "tw-set-content")
            self.category_view.pack_start(self.page_scroll, True, True, 0)
            self.category_view.show_all()
        self.stack.set_visible_child_name("category")
        self._show_page_content(page_id)

    def _open_row(self, row):
        for pid, r in self.nav_rows.items():
            if r is row:
                self._show_page_content(pid)

    def _show_page_content(self, page_id):
        builder = PAGE_BUILDERS.get(page_id)
        if builder is None:
            return
        self.current_page = page_id
        for pid, row in self.nav_rows.items():
            set_class(row.get_child(), "selected", pid == page_id)
        child = self.page_scroll.get_child()
        if child is not None:
            self.page_scroll.remove(child)
            child.destroy()
        try:
            page = builder(self)
        except Exception:
            log.exception("page %s failed", page_id)
            page = Gtk.Label(label=_("This page could not be loaded."))
        self.page_scroll.add(page)
        self.page_scroll.get_vadjustment().set_value(0)
        self.page_scroll.show_all()
        title = next((t for p, _c, t, _i, _k in settings_index.PAGES if p == page_id), "")
        self.set_title("%s – %s" % (_("Settings"), _(title)))

    def show_page(self, page_id):
        for pid, cat, _title, _icon, _kw in settings_index.PAGES:
            if pid == page_id:
                self.present()
                GLib.idle_add(lambda: self.show_category(cat, pid) and False)
                return True
        return False

    def show_home(self):
        self.current_category = None
        self.current_page = None
        self.set_title(_("Settings"))
        self.stack.set_visible_child_name("home")

    def error(self, title, message=""):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.ERROR,
                                   buttons=Gtk.ButtonsType.OK, text=title)
        if message:
            dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()

    def _on_key(self, _widget, event):
        from gi.repository import Gdk
        if event.keyval == Gdk.KEY_BackSpace and event.state & Gdk.ModifierType.MOD1_MASK:
            self.show_home()
            return True
        return False


class WelcomeWindow(Gtk.Window):
    """First run: let the user choose light or dark (OOBE-like)."""

    def __init__(self, app):
        super().__init__(title=_("Welcome to Tenwin"))
        self.set_application(app)
        add_class(self, "tw-app-window", "tw-welcome")
        self.set_default_size(720, 460)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.settings = get_settings()
        self.choice = "light" if self.settings["appearance.app_mode"] == "light" and \
            self.settings["appearance.shell_mode"] == "light" else "dark"
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_margin_start(40)
        box.set_margin_end(40)
        box.set_margin_top(32)
        box.set_margin_bottom(28)
        box.pack_start(add_class(Gtk.Label(label=_("Welcome to Tenwin"), xalign=0), "tw-h1"), False, False, 0)
        box.pack_start(add_class(Gtk.Label(label=_("Choose how your desktop should look. You can change this "
                                                   "later in Settings › Personalization › Colors."),
                                           xalign=0, wrap=True), "tw-dim"), False, False, 0)
        cards = Gtk.Box(spacing=24, homogeneous=True)
        self.cards = {}
        for mode, label in (("light", _("Light")), ("dark", _("Dark"))):
            button = flat_button(css="tw-mode-card")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            preview = add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "tw-mode-preview", mode)
            preview.set_size_request(280, 160)
            window = add_class(Gtk.Box(), "tw-mode-window")
            window.set_size_request(150, 90)
            window.set_halign(Gtk.Align.CENTER)
            window.set_valign(Gtk.Align.CENTER)
            preview.pack_start(window, True, True, 0)
            bar = add_class(Gtk.Box(), "tw-mode-taskbar")
            bar.set_size_request(-1, 16)
            preview.pack_end(bar, False, False, 0)
            inner.pack_start(preview, False, False, 0)
            inner.pack_start(Gtk.Label(label=label), False, False, 0)
            button.add(inner)
            button.connect("clicked", lambda _b, m=mode: self.select(m))
            self.cards[mode] = button
            cards.pack_start(button, True, True, 0)
        box.pack_start(cards, True, True, 8)
        footer = Gtk.Box()
        go = Gtk.Button(label=_("Next"))
        add_class(go, "tw-accent-button")
        go.connect("clicked", lambda *_: self.finish())
        footer.pack_end(go, False, False, 0)
        box.pack_start(footer, False, False, 0)
        self.add(box)
        self._highlight()
        self.show_all()

    def _highlight(self):
        for m, card in self.cards.items():
            set_class(card, "selected", m == self.choice)

    def select(self, mode):
        self.choice = mode
        self._highlight()
        # Preview the choice immediately.
        self.settings.update({"appearance.shell_mode": mode, "appearance.app_mode": mode})

    def finish(self):
        self.settings.update({"appearance.shell_mode": self.choice, "appearance.app_mode": self.choice,
                              "session.first_run_done": True})
        self.destroy()


class SettingsApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.tenwin.Settings", flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.add_main_option("welcome", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             _("Show the welcome dialog"), None)
        self.window = None
        self._styled = False

    def do_command_line(self, command_line):
        options = command_line.get_options_dict().end().unpack()
        args = command_line.get_arguments()[1:]
        if not self._styled:
            theme.install("settings")
            self._styled = True
        if options.get("welcome"):
            WelcomeWindow(self).present()
            return 0
        if self.window is None:
            self.window = SettingsWindow(self)
            self.window.connect("destroy", lambda *_: setattr(self, "window", None))
        self.window.present()
        for arg in args:
            page = arg.split(":", 1)[1] if arg.startswith(("tenwin-settings:", "ms-settings:")) else arg
            page = page.strip("/")
            if not self.window.show_page(page):
                for cat_id, *_rest in settings_index.CATEGORIES:
                    if cat_id == page:
                        self.window.show_category(cat_id)
        return 0


def main():
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    GLib.set_prgname("org.tenwin.Settings")
    return SettingsApp().run(sys.argv)
