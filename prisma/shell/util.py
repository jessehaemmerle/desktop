"""Hilfsfunktionen: Prozesse starten, Icons laden, Layer-Fenster erzeugen."""

from __future__ import annotations

import os
import shlex
import shutil
import sys

from gi.repository import Gdk, Gio, GLib, Gtk, GtkLayerShell as Layer

LAYERS = {
    "background": Layer.Layer.BACKGROUND,
    "bottom": Layer.Layer.BOTTOM,
    "top": Layer.Layer.TOP,
    "overlay": Layer.Layer.OVERLAY,
}
EDGES = {
    "top": Layer.Edge.TOP,
    "bottom": Layer.Edge.BOTTOM,
    "left": Layer.Edge.LEFT,
    "right": Layer.Edge.RIGHT,
}
KEYBOARD = {
    "none": Layer.KeyboardMode.NONE,
    "exclusive": Layer.KeyboardMode.EXCLUSIVE,
    "on-demand": Layer.KeyboardMode.ON_DEMAND,
}


def layer_window(
    app: Gtk.Application,
    name: str,
    layer: str = "top",
    anchors: tuple[str, ...] = (),
    margins: dict | None = None,
    exclusive: int | str | None = None,
    keyboard: str = "none",
    monitor: Gdk.Monitor | None = None,
) -> Gtk.Window:
    """Erzeugt ein transparentes Fenster als wlr-layer-shell-Oberfläche."""
    win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    app.add_window(win)
    win.set_title(f"prisma-{name}")
    win.get_style_context().add_class("prisma-layer")
    win.get_style_context().add_class(f"prisma-{name}")
    win.set_decorated(False)
    screen = win.get_screen()
    visual = screen.get_rgba_visual()
    if visual is not None:
        win.set_visual(visual)
    win.set_app_paintable(True)

    Layer.init_for_window(win)
    Layer.set_namespace(win, f"prisma-{name}")
    Layer.set_layer(win, LAYERS[layer])
    for edge in anchors:
        Layer.set_anchor(win, EDGES[edge], True)
    for edge, value in (margins or {}).items():
        Layer.set_margin(win, EDGES[edge], int(value))
    if exclusive == "auto":
        Layer.auto_exclusive_zone_enable(win)
    elif exclusive is not None:
        Layer.set_exclusive_zone(win, int(exclusive))
    Layer.set_keyboard_mode(win, KEYBOARD[keyboard])
    if monitor is not None:
        Layer.set_monitor(win, monitor)
    return win


def set_keyboard(win: Gtk.Window, mode: str) -> None:
    Layer.set_keyboard_mode(win, KEYBOARD[mode])


def spawn(command: list[str] | str) -> bool:
    """Startet einen Prozess losgelöst von der Shell (GLib räumt Zombies auf)."""
    argv = shlex.split(command) if isinstance(command, str) else list(command)
    if not argv:
        return False
    try:
        GLib.spawn_async(
            argv,
            flags=GLib.SpawnFlags.SEARCH_PATH
            | GLib.SpawnFlags.STDOUT_TO_DEV_NULL
            | GLib.SpawnFlags.STDERR_TO_DEV_NULL,
        )
        return True
    except GLib.Error as exc:
        print(f"prisma: konnte {argv[0]} nicht starten: {exc.message}")
        return False


def prisma_command(module: str, *args: str) -> list[str]:
    """Startet ein Prisma-Modul mit demselben Interpreter (funktioniert installiert und im Quellbaum)."""
    return [sys.executable, "-m", module, *args]


def run(argv: list[str], callback=None) -> None:
    """Führt einen Befehl asynchron aus und liefert stdout (oder None) an ``callback``."""
    if shutil.which(argv[0]) is None:
        if callback:
            GLib.idle_add(lambda: callback(None) and False)
        return
    try:
        proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
    except GLib.Error:
        if callback:
            callback(None)
        return

    def finished(process, result):
        try:
            _ok, stdout, _stderr = process.communicate_utf8_finish(result)
        except GLib.Error:
            stdout = None
        if callback:
            callback(stdout)

    proc.communicate_utf8_async(None, None, finished)


def has(program: str) -> bool:
    return shutil.which(program) is not None


def terminal_command(configured: str = "") -> list[str]:
    for candidate in (configured, os.environ.get("TERMINAL", ""), "x-terminal-emulator", "foot",
                      "kgx", "gnome-terminal", "kitty", "alacritty", "xfce4-terminal", "konsole", "xterm"):
        if candidate and has(candidate.split()[0]):
            return shlex.split(candidate)
    return ["xterm"]


def run_in_terminal(command: str, configured: str = "") -> None:
    term = terminal_command(configured)
    inner = ["sh", "-c", f'{command}; echo; printf "[Prisma] Beendet – Enter schließt."; read _']
    if os.path.basename(term[0]) in ("gnome-terminal", "kgx", "gnome-console", "ptyxis"):
        spawn(term + ["--"] + inner)
    else:
        spawn(term + ["-e"] + inner)


def icon_image(icon, size: int, fallback: str = "application-x-executable") -> Gtk.Image:
    image = Gtk.Image()
    set_icon(image, icon, size, fallback)
    return image


def set_icon(image: Gtk.Image, icon, size: int, fallback: str = "application-x-executable") -> None:
    """Akzeptiert Icon-Namen, Dateipfade, URIs und ``Gio.Icon``."""
    image.set_pixel_size(size)
    if isinstance(icon, Gio.Icon):
        image.set_from_gicon(icon, Gtk.IconSize.DIALOG)
        return
    if isinstance(icon, str) and icon:
        if icon.startswith("file://"):
            icon = GLib.filename_from_uri(icon)[0]
        if icon.startswith("/"):
            try:
                from gi.repository import GdkPixbuf

                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(icon, size, size, True)
                image.set_from_pixbuf(pixbuf)
                return
            except GLib.Error:
                pass
        elif Gtk.IconTheme.get_default().has_icon(icon):
            image.set_from_icon_name(icon, Gtk.IconSize.DIALOG)
            return
    image.set_from_icon_name(fallback, Gtk.IconSize.DIALOG)


def add_class(widget: Gtk.Widget, *names: str) -> Gtk.Widget:
    ctx = widget.get_style_context()
    for name in names:
        ctx.add_class(name)
    return widget


def toggle_class(widget: Gtk.Widget, name: str, on: bool) -> None:
    ctx = widget.get_style_context()
    if on:
        ctx.add_class(name)
    else:
        ctx.remove_class(name)


def label(text: str = "", *classes: str, xalign: float = 0.0, ellipsize: bool = False, wrap: bool = False) -> Gtk.Label:
    lbl = Gtk.Label(label=text)
    lbl.set_xalign(xalign)
    if ellipsize:
        from gi.repository import Pango

        lbl.set_ellipsize(Pango.EllipsizeMode.END)
    if wrap:
        lbl.set_line_wrap(True)
        lbl.set_max_width_chars(46)
    add_class(lbl, *classes)
    return lbl


def clear(container: Gtk.Container) -> None:
    for child in container.get_children():
        container.remove(child)
        child.destroy()
