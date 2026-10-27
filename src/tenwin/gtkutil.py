"""GTK helpers shared by all Tenwin programs."""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango

ICON_FALLBACK = "application-x-executable"


def icon_image(icon, size, symbolic=False):
    """Gtk.Image for a Gio.Icon, an icon name or None."""
    image = Gtk.Image()
    set_icon(image, icon, size, symbolic)
    return image


def set_icon(image, icon, size, symbolic=False):
    theme = Gtk.IconTheme.get_default()
    if icon is None:
        icon = ICON_FALLBACK
    if isinstance(icon, str):
        if icon.startswith("/"):
            icon = Gio.FileIcon.new(Gio.File.new_for_path(icon))
        else:
            name = icon + "-symbolic" if symbolic and not icon.endswith("-symbolic") else icon
            if not theme.has_icon(name) and theme.has_icon(icon):
                name = icon
            icon = Gio.ThemedIcon.new_with_default_fallbacks(name) if theme.has_icon(name) \
                else Gio.ThemedIcon.new(ICON_FALLBACK)
    image.set_from_gicon(icon, Gtk.IconSize.BUTTON)
    image.set_pixel_size(size)
    return image


def label(text="", css=None, xalign=0.0, ellipsize=False, wrap=False, max_width=None):
    widget = Gtk.Label(label=text, xalign=xalign)
    if css:
        for cls in css.split():
            widget.get_style_context().add_class(cls)
    if ellipsize:
        widget.set_ellipsize(Pango.EllipsizeMode.END)
    if wrap:
        widget.set_line_wrap(True)
        widget.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if max_width:
        widget.set_max_width_chars(max_width)
    return widget


def add_class(widget, *classes):
    ctx = widget.get_style_context()
    for cls in classes:
        ctx.add_class(cls)
    return widget


def remove_class(widget, *classes):
    ctx = widget.get_style_context()
    for cls in classes:
        ctx.remove_class(cls)
    return widget


def set_class(widget, cls, enabled):
    if enabled:
        add_class(widget, cls)
    else:
        remove_class(widget, cls)


def flat_button(child=None, css=None, tooltip=None):
    button = Gtk.Button()
    button.set_relief(Gtk.ReliefStyle.NONE)
    button.set_can_focus(False)
    if child is not None:
        button.add(child)
    if css:
        add_class(button, *css.split())
    if tooltip:
        button.set_tooltip_text(tooltip)
    return button


def enable_rgba(window):
    screen = window.get_screen()
    visual = screen.get_rgba_visual()
    if visual is not None:
        window.set_visual(visual)
    window.set_app_paintable(True)


def clear_children(container):
    for child in container.get_children():
        container.remove(child)
        child.destroy()


def menu_item(text, callback=None, icon=None, sensitive=True, *args):
    item = Gtk.MenuItem()
    box = Gtk.Box(spacing=10)
    if icon:
        box.pack_start(icon_image(icon, 16, symbolic=True), False, False, 0)
    box.pack_start(Gtk.Label(label=text, xalign=0), True, True, 0)
    item.add(box)
    item.set_sensitive(sensitive)
    if callback:
        item.connect("activate", lambda *_: callback(*args))
    return item


def popup_menu(menu, widget=None, event=None):
    """Show a Gtk.Menu at the pointer (or below ``widget``)."""
    add_class(menu, "tw-menu")
    menu.show_all()
    if event is not None:
        menu.popup_at_pointer(event)
    elif widget is not None:
        menu.popup_at_widget(widget, Gdk.Gravity.NORTH_WEST, Gdk.Gravity.SOUTH_WEST, None)
    else:
        menu.popup_at_pointer(None)


def human_size(num):
    from tenwin.i18n import _
    units = [_("bytes"), "KB", "MB", "GB", "TB"]
    if num < 1024:
        return "%d %s" % (num, units[0])
    value = float(num)
    for unit in units[1:]:
        value /= 1024.0
        if value < 1024 or unit == units[-1]:
            text = ("%.1f" % value) if value < 100 else ("%d" % round(value))
            from tenwin.i18n import current_language
            if current_language() == "de":
                text = text.replace(".", ",")
            return "%s %s" % (text, unit)
    return str(num)


def format_datetime(timestamp, with_time=True):
    dt = GLib.DateTime.new_from_unix_local(int(timestamp))
    if dt is None:
        return ""
    from tenwin.config import get_settings
    fmt = "%x"
    if with_time:
        fmt += " %H:%M" if get_settings()["region.clock_24h"] else " %I:%M %p"
    return dt.format(fmt) or ""


def run_detached(argv):
    """Spawn a program without waiting for it."""
    try:
        GLib.spawn_async(argv, flags=GLib.SpawnFlags.SEARCH_PATH | GLib.SpawnFlags.STDOUT_TO_DEV_NULL
                         | GLib.SpawnFlags.STDERR_TO_DEV_NULL)
        return True
    except GLib.Error:
        return False


def open_uri(uri):
    try:
        Gio.AppInfo.launch_default_for_uri(uri, None)
        return True
    except GLib.Error:
        return False
