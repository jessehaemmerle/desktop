"""tenwin-greeter: LightDM sign-in screen in the style of Windows 10.

Run ``tenwin-greeter --preview [--login]`` to try it without LightDM
(the preview password is "tenwin").
"""

import configparser
import logging
import os
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango

from tenwin import paths, theme
from tenwin.gtkutil import add_class, clear_children, flat_button, icon_image, menu_item, popup_menu
from tenwin.i18n import _, current_language

log = logging.getLogger("tenwin.greeter")

CONFIG_FILE = "/etc/lightdm/tenwin-greeter.conf"

try:
    gi.require_version("LightDM", "1")
    from gi.repository import LightDM
except (ImportError, ValueError):
    LightDM = None


def load_config():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    section = config["greeter"] if config.has_section("greeter") else {}
    return {
        "background": section.get("background", paths.default_wallpaper()),
        "clock_24h": section.get("clock-24h", "true").lower() != "false",
    }


class FakeUser:
    def __init__(self, name, real_name):
        self._name, self._real = name, real_name

    def get_name(self):
        return self._name

    def get_display_name(self):
        return self._real

    def get_image(self):
        return None

    def get_session(self):
        return "tenwin"

    def get_logged_in(self):
        return False


class FakeSession:
    def __init__(self, key, name):
        self._key, self._name = key, name

    def get_key(self):
        return self._key

    def get_name(self):
        return self._name


class Backend:
    """Thin wrapper so the UI also runs without LightDM (--preview)."""

    def __init__(self, ui, preview):
        self.ui = ui
        self.preview = preview or LightDM is None
        self.greeter = None
        if not self.preview:
            self.greeter = LightDM.Greeter()
            self.greeter.connect("show-prompt", self._on_prompt)
            self.greeter.connect("show-message", self._on_message)
            self.greeter.connect("authentication-complete", self._on_complete)
            self.greeter.connect_to_daemon_sync()
        self.pending_password = None

    def users(self):
        if self.preview:
            return [FakeUser("jesse", "Jesse"), FakeUser("gast", _("Guest"))]
        return list(LightDM.UserList.get_instance().get_users())

    def sessions(self):
        if self.preview:
            return [FakeSession("tenwin", "Tenwin"), FakeSession("ubuntu", "Ubuntu")]
        return list(LightDM.get_sessions())

    def default_session(self):
        if self.preview:
            return "tenwin"
        return self.greeter.get_default_session_hint() or "tenwin"

    def select_hint(self):
        if self.preview:
            return None
        return self.greeter.get_select_user_hint()

    def login(self, user, password):
        if self.preview:
            GLib.timeout_add(800, lambda: self.ui.on_auth_result(password == "tenwin") and False)
            return
        self.pending_password = password
        if self.greeter.get_in_authentication():
            self.greeter.cancel_authentication()
        self.greeter.authenticate(user.get_name())

    def _on_prompt(self, _greeter, text, prompt_type):
        if self.pending_password is not None:
            self.greeter.respond(self.pending_password)
            self.pending_password = None
        else:
            # A second prompt (e.g. OTP) - ask the user.
            self.ui.show_extra_prompt(text, prompt_type == LightDM.PromptType.SECRET)

    def respond(self, text):
        self.greeter.respond(text)

    def _on_message(self, _greeter, text, _message_type):
        self.ui.show_message(text)

    def _on_complete(self, greeter):
        self.ui.on_auth_result(greeter.get_is_authenticated())

    def start_session(self, session_key):
        if self.preview:
            Gtk.main_quit()
            return True
        try:
            return self.greeter.start_session_sync(session_key)
        except GLib.Error as exc:
            log.error("cannot start session %s: %s", session_key, exc)
            return False

    def can(self, what):
        if self.preview:
            return True
        return {"suspend": LightDM.get_can_suspend, "restart": LightDM.get_can_restart,
                "shutdown": LightDM.get_can_shutdown}[what]()

    def power(self, what):
        if self.preview:
            log.info("preview: %s", what)
            return
        try:
            {"suspend": LightDM.suspend, "restart": LightDM.restart, "shutdown": LightDM.shutdown}[what]()
        except GLib.Error as exc:
            log.error("%s failed: %s", what, exc)


def blurred(pixbuf, width, height):
    """Approximate Windows 10's acrylic sign-in background."""
    if pixbuf is None:
        return None
    small = pixbuf.scale_simple(max(1, width // 28), max(1, height // 28), GdkPixbuf.InterpType.BILINEAR)
    small = small.scale_simple(max(1, width // 10), max(1, height // 10), GdkPixbuf.InterpType.BILINEAR)
    return small.scale_simple(width, height, GdkPixbuf.InterpType.BILINEAR)


def cover(pixbuf, width, height):
    if pixbuf is None:
        return None
    pw, ph = pixbuf.get_width(), pixbuf.get_height()
    factor = max(width / pw, height / ph)
    scaled = pixbuf.scale_simple(max(1, int(pw * factor)), max(1, int(ph * factor)), GdkPixbuf.InterpType.BILINEAR)
    x = (scaled.get_width() - width) // 2
    y = (scaled.get_height() - height) // 2
    return scaled.new_subpixbuf(x, y, width, height)


def load_background(path, width, height):
    try:
        fmt, w, h = GdkPixbuf.Pixbuf.get_file_info(path)
        if fmt is not None and fmt.is_scalable():
            factor = max(width / w, height / h)
            return cover(GdkPixbuf.Pixbuf.new_from_file_at_scale(path, int(w * factor) + 1, int(h * factor) + 1,
                                                                 True), width, height)
        return cover(GdkPixbuf.Pixbuf.new_from_file(path), width, height)
    except (GLib.Error, TypeError) as exc:
        log.warning("background %s: %s", path, exc)
        return None


def avatar_pixbuf(path, size):
    if path and os.path.exists(path):
        try:
            return GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, False)
        except GLib.Error:
            pass
    return None


class Avatar(Gtk.DrawingArea):
    def __init__(self, size):
        super().__init__()
        self.size = size
        self.pixbuf = None
        self.set_size_request(size, size)
        self.connect("draw", self._draw)

    def set_image(self, path):
        self.pixbuf = avatar_pixbuf(path, self.size)
        self.queue_draw()

    def _draw(self, _widget, cr):
        import math
        r = self.size / 2
        cr.arc(r, r, r, 0, 2 * math.pi)
        cr.clip()
        if self.pixbuf is not None:
            Gdk.cairo_set_source_pixbuf(cr, self.pixbuf, 0, 0)
            cr.paint()
            return False
        cr.set_source_rgb(0.8, 0.8, 0.8)
        cr.paint()
        cr.set_source_rgb(1, 1, 1)
        cr.arc(r, r * 0.82, r * 0.36, 0, 2 * math.pi)
        cr.fill()
        cr.arc(r, r * 1.95, r * 0.75, math.pi, 2 * math.pi)
        cr.fill()
        return False


class GreeterWindow(Gtk.Window):
    def __init__(self, monitor, config, backend_factory, primary):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        add_class(self, "tw-greeter")
        self.set_decorated(False)
        self.config = config
        self.primary = primary
        geo = monitor.get_geometry()
        self.width, self.height = geo.width, geo.height
        self.move(geo.x, geo.y)
        self.set_default_size(geo.width, geo.height)
        self.background = load_background(config["background"], geo.width, geo.height)
        self.background_blur = blurred(self.background, geo.width, geo.height)
        self.state = "curtain"
        self.overlay = Gtk.Overlay()
        self.area = Gtk.DrawingArea()
        self.area.connect("draw", self._draw_background)
        self.overlay.add(self.area)
        self.add(self.overlay)
        if primary:
            self.backend = backend_factory(self)
            self.users = self.backend.users()
            hint = self.backend.select_hint()
            self.user = next((u for u in self.users if u.get_name() == hint), self.users[0] if self.users else None)
            self.session_key = self.backend.default_session()
            self._build_curtain()
            self._build_login()
            self.add_events(Gdk.EventMask.KEY_PRESS_MASK | Gdk.EventMask.BUTTON_PRESS_MASK)
            self.connect("key-press-event", self._on_key)
            self.connect("button-press-event", self._on_click)
            GLib.timeout_add_seconds(1, self._tick)
        self.show_all()
        if primary:
            self.login_box.hide()
            self.corner_left.hide()
            self.corner_right.hide()
        self.fullscreen_on_monitor(self.get_screen(), monitor_index(monitor))

    # -- background ----------------------------------------------------------

    def _draw_background(self, widget, cr):
        pixbuf = self.background if self.state == "curtain" else self.background_blur
        if pixbuf is not None:
            Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
            cr.paint()
        else:
            cr.set_source_rgb(0.0, 0.25, 0.55)
            cr.paint()
        if self.state != "curtain":
            cr.set_source_rgba(0, 0, 0, 0.25)
            cr.paint()
        return False

    # -- curtain -------------------------------------------------------------

    def _build_curtain(self):
        box = add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "tw-curtain")
        box.set_halign(Gtk.Align.START)
        box.set_valign(Gtk.Align.END)
        box.set_margin_start(max(24, int(self.height * 0.045)))
        box.set_margin_bottom(int(self.height * 0.09))
        self.time_label = add_class(Gtk.Label(xalign=0), "tw-greeter-time")
        self.date_label = add_class(Gtk.Label(xalign=0), "tw-greeter-date")
        box.pack_start(self.time_label, False, False, 0)
        box.pack_start(self.date_label, False, False, 0)
        self.curtain = box
        self.overlay.add_overlay(box)
        self._tick()

    def _tick(self):
        now = GLib.DateTime.new_now_local()
        self.time_label.set_text(now.format("%H:%M" if self.config["clock_24h"] else "%l:%M").strip())
        fmt = "%A, %e. %B" if current_language() == "de" else "%A, %B %e"
        self.date_label.set_text(now.format(fmt).replace("  ", " "))
        return GLib.SOURCE_CONTINUE

    # -- login ---------------------------------------------------------------

    def _build_login(self):
        self.login_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.login_box.set_halign(Gtk.Align.CENTER)
        self.login_box.set_valign(Gtk.Align.CENTER)
        self.avatar = Avatar(192)
        self.avatar.set_halign(Gtk.Align.CENTER)
        self.login_box.pack_start(self.avatar, False, False, 0)
        self.name_label = add_class(Gtk.Label(), "tw-greeter-name")
        self.login_box.pack_start(self.name_label, False, False, 0)
        self.form = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.form.set_vhomogeneous(False)
        field = add_class(Gtk.Box(), "tw-greeter-field")
        field.set_valign(Gtk.Align.START)
        field.set_size_request(296, 32)
        self.password = add_class(Gtk.Entry(visibility=False, placeholder_text=_("Password")), "tw-greeter-password")
        self.password.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        self.password.set_width_chars(28)
        self.password.connect("activate", lambda *_: self._on_activate())
        self.extra_prompt = False
        field.pack_start(self.password, True, True, 0)
        go = flat_button(icon_image("tenwin-arrow-right", 16, symbolic=True), "tw-greeter-go", _("Submit"))
        go.connect("clicked", lambda *_: self._on_activate())
        field.pack_start(go, False, False, 0)
        field.set_halign(Gtk.Align.CENTER)
        self.form.add_named(field, "password")
        self.welcome = add_class(Gtk.Label(label=_("Welcome")), "tw-greeter-message")
        self.form.add_named(self.welcome, "welcome")
        error_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.error_label = add_class(Gtk.Label(label=_("The password is incorrect. Try again."), wrap=True,
                                               justify=Gtk.Justification.CENTER), "tw-greeter-message")
        self.error_label.set_max_width_chars(40)
        error_box.pack_start(self.error_label, False, False, 0)
        ok = Gtk.Button(label=_("OK"))
        add_class(ok, "tw-greeter-ok")
        ok.set_halign(Gtk.Align.CENTER)
        ok.connect("clicked", lambda *_: self.show_form())
        error_box.pack_start(ok, False, False, 0)
        self.form.add_named(error_box, "error")
        self.login_box.pack_start(self.form, False, False, 4)
        self.overlay.add_overlay(self.login_box)

        self.corner_left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.corner_left.set_halign(Gtk.Align.START)
        self.corner_left.set_valign(Gtk.Align.END)
        self.corner_left.set_margin_start(16)
        self.corner_left.set_margin_bottom(16)
        self.overlay.add_overlay(self.corner_left)
        self._fill_users()

        self.corner_right = Gtk.Box(spacing=4)
        self.corner_right.set_halign(Gtk.Align.END)
        self.corner_right.set_valign(Gtk.Align.END)
        self.corner_right.set_margin_end(16)
        self.corner_right.set_margin_bottom(16)
        sessions = self.backend.sessions()
        if len(sessions) > 1:
            session_button = flat_button(icon_image("tenwin-desktop", 24, symbolic=True), "tw-greeter-corner",
                                         _("Session"))
            session_button.connect("clicked", lambda b: self._session_menu(b, sessions))
            self.corner_right.pack_start(session_button, False, False, 0)
        power = flat_button(icon_image("tenwin-power", 24, symbolic=True), "tw-greeter-corner", _("Power"))
        power.connect("clicked", lambda b: self._power_menu(b))
        self.corner_right.pack_start(power, False, False, 0)
        self.overlay.add_overlay(self.corner_right)
        self._show_user()

    def _fill_users(self):
        clear_children(self.corner_left)
        if len(self.users) < 2:
            return
        for user in self.users:
            button = flat_button(css="tw-greeter-user")
            row = Gtk.Box(spacing=10)
            small = Avatar(40)
            small.set_image(user.get_image())
            row.pack_start(small, False, False, 0)
            name = Gtk.Label(label=user.get_display_name() or user.get_name(), xalign=0)
            name.set_ellipsize(Pango.EllipsizeMode.END)
            row.pack_start(name, True, True, 0)
            button.add(row)
            if user is self.user:
                add_class(button, "selected")
            button.connect("clicked", lambda _b, u=user: self.select_user(u))
            self.corner_left.pack_start(button, False, False, 0)
        self.corner_left.show_all()

    def _show_user(self):
        if self.user is None:
            self.name_label.set_text(_("Other user"))
            return
        self.name_label.set_text(self.user.get_display_name() or self.user.get_name())
        self.avatar.set_image(self.user.get_image())
        session = self.user.get_session()
        if session:
            self.session_key = session

    def select_user(self, user):
        self.user = user
        self._show_user()
        self._fill_users()
        self.show_form()

    def _session_menu(self, button, sessions):
        menu = Gtk.Menu()
        for session in sessions:
            mark = "✓  " if session.get_key() == self.session_key else "     "
            menu.append(menu_item(mark + session.get_name(), lambda s=session: setattr(self, "session_key",
                                                                                         s.get_key())))
        popup_menu(menu, widget=button)

    def _power_menu(self, button):
        menu = Gtk.Menu()
        for key, label, icon in (("suspend", _("Sleep"), "tenwin-sleep"), ("shutdown", _("Shut down"), "tenwin-power"),
                                 ("restart", _("Restart"), "tenwin-restart")):
            if self.backend.can(key):
                menu.append(menu_item(label, lambda k=key: self.backend.power(k), icon))
        popup_menu(menu, widget=button)

    # -- state ---------------------------------------------------------------

    def show_form(self):
        self.state = "login"
        self.curtain.hide()
        self.login_box.show()
        self.corner_left.show()
        self.corner_right.show()
        self.form.set_visible_child_name("password")
        self._reset_entry()
        self.password.grab_focus()
        self.area.queue_draw()

    def show_curtain(self):
        self.state = "curtain"
        self._reset_entry()
        self.login_box.hide()
        self.corner_left.hide()
        self.corner_right.hide()
        self.curtain.show()
        self.area.queue_draw()

    def submit(self):
        if self.user is None:
            return
        password = self.password.get_text()
        self.password.set_text("")
        self.form.set_visible_child_name("welcome")
        self.backend.login(self.user, password)

    def on_auth_result(self, ok):
        self._reset_entry()
        if ok:
            if not self.backend.start_session(self.session_key):
                self.error_label.set_text(_("The session could not be started."))
                self.form.set_visible_child_name("error")
        else:
            self.error_label.set_text(_("The password is incorrect. Try again."))
            self.form.set_visible_child_name("error")
        return False

    def show_message(self, text):
        self.error_label.set_text(text)

    def show_extra_prompt(self, text, secret):
        """A further PAM prompt (one-time code, new password, …)."""
        self.extra_prompt = True
        self.password.set_placeholder_text(text)
        self.password.set_visibility(not secret)
        self.form.set_visible_child_name("password")
        self.password.grab_focus()

    def _reset_entry(self):
        self.extra_prompt = False
        self.password.set_text("")
        self.password.set_visibility(False)
        self.password.set_placeholder_text(_("Password"))

    def _on_activate(self):
        if self.extra_prompt:
            text = self.password.get_text()
            self._reset_entry()
            self.form.set_visible_child_name("welcome")
            self.backend.respond(text)
        else:
            self.submit()

    # -- input --------------------------------------------------------------

    def _on_key(self, _widget, event):
        if self.state == "curtain":
            self.show_form()
            char = Gdk.keyval_to_unicode(event.keyval)
            if char and chr(char).isprintable():
                self.password.set_text(chr(char))
                self.password.set_position(-1)
            return True
        if event.keyval == Gdk.KEY_Escape:
            self.show_curtain()
            return True
        return False

    def _on_click(self, _widget, _event):
        if self.state == "curtain":
            self.show_form()
            return True
        return False


def monitor_index(monitor):
    display = Gdk.Display.get_default()
    for i in range(display.get_n_monitors()):
        if display.get_monitor(i) == monitor:
            return i
    return 0


def main():
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    preview = "--preview" in sys.argv
    GLib.set_prgname("tenwin-greeter")
    Gtk.init(sys.argv)
    theme.install("greeter")
    display = Gdk.Display.get_default()
    root = Gdk.get_default_root_window() if hasattr(Gdk, "get_default_root_window") else None
    if root is not None:
        try:
            root.set_cursor(Gdk.Cursor.new_from_name(display, "default"))
        except TypeError:
            pass
    config = load_config()
    primary = display.get_primary_monitor() or display.get_monitor(0)
    windows = []
    for i in range(display.get_n_monitors()):
        monitor = display.get_monitor(i)
        windows.append(GreeterWindow(monitor, config, lambda ui: Backend(ui, preview), monitor == primary))
    if preview and "--login" in sys.argv:
        for window in windows:
            if window.primary:
                window.show_form()
    Gtk.main()
    return 0
