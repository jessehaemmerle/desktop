"""All pages of the Settings app."""

import os
import platform
import shutil
import socket
import subprocess

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango

from tenwin import __version__, paths
from tenwin.config import ACCENT_COLORS, DEFAULTS, get_settings
from tenwin.gtkutil import add_class, clear_children, flat_button, human_size, icon_image, set_class
from tenwin.i18n import N_, _
from tenwin.services import system
from tenwin.services.audio import Audio
from tenwin.services.bluetooth import Bluetooth
from tenwin.services.display import Brightness, apply_output, list_outputs
from tenwin.services.network import Network
from tenwin.services.power import Power
from tenwin.settings.widgets import Page

_services = {}


def service(name):
    if name not in _services:
        _services[name] = {"audio": Audio, "network": Network, "power": Power, "bluetooth": Bluetooth,
                           "brightness": Brightness}[name]()
    return _services[name]


def minutes_options():
    values = [1, 2, 3, 5, 10, 15, 20, 25, 30, 45, 60, 120, 180, 240, 300, 0]
    opts = []
    for v in values:
        if v == 0:
            opts.append((0, _("Never")))
        elif v < 60:
            opts.append((v, _("%d minutes") % v if v != 1 else _("1 minute")))
        else:
            opts.append((v, _("%d hours") % (v // 60) if v != 60 else _("1 hour")))
    return opts


# ------------------------------------------------------------------ System

def page_display(win):
    p = Page(_("Display"))
    brightness = service("brightness")
    if brightness.available:
        p.section(_("Brightness and color"))
        p.slider(_("Change brightness"), 1, 100, 1, getter=lambda: brightness.percent, setter=brightness.set)
    else:
        p.section(_("Color"))
    p.toggle(_("Night light"), "nightlight.enabled",
             description=_("Displays warmer colors to help you sleep."))
    p.slider(_("Strength (color temperature in Kelvin)"), 2500, 6500, 100, "nightlight.temperature",
             fmt=lambda v: "%d K" % v)

    outputs = [o for o in list_outputs() if o.get("enabled", True)]
    if not outputs:
        p.text(_("No display information is available (wlr-randr missing?)."))
        return p
    p.section(_("Scale and layout"))
    names = [(o["name"], "%s (%s)" % (o.get("description") or o["name"], o["name"])) for o in outputs]
    state = {"output": outputs[0]}
    if len(outputs) > 1:
        p.combo(_("Display"), names, getter=lambda: outputs[0]["name"],
                setter=lambda n: select(next(o for o in outputs if o["name"] == n)), width=380)
    holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    p.add(holder)

    def select(output):
        state["output"] = output
        clear_children(holder)
        sub = Page("")
        sub.set_margin_start(0)
        sub.set_margin_top(0)
        sub.get_children()[0].destroy()
        scales = [(1.0, "100 %"), (1.25, "125 %"), (1.5, "150 %"), (1.75, "175 %"), (2.0, "200 %")]
        current_scale = min(scales, key=lambda s: abs(s[0] - float(output.get("scale", 1.0))))[0]
        sub.combo(_("Change the size of text, apps, and other items"), scales, getter=lambda: current_scale,
                  setter=lambda v: change(output, scale=float(v)))
        modes = []
        seen = set()
        current_mode = None
        for mode in sorted(output.get("modes", []), key=lambda m: (-m["width"], -m["height"], -m["refresh"])):
            key = "%dx%d" % (mode["width"], mode["height"])
            if key in seen:
                continue
            seen.add(key)
            label = "%d × %d" % (mode["width"], mode["height"])
            if mode.get("preferred"):
                label += " " + _("(Recommended)")
            modes.append((key, label))
            if mode.get("current"):
                current_mode = key
        if modes:
            sub.combo(_("Display resolution"), modes, getter=lambda: current_mode,
                      setter=lambda v: change(output, mode=v))
        transforms = [("normal", _("Landscape")), ("90", _("Portrait")), ("180", _("Landscape (flipped)")),
                      ("270", _("Portrait (flipped)"))]
        sub.combo(_("Display orientation"), transforms, getter=lambda: output.get("transform", "normal"),
                  setter=lambda v: change(output, transform=v))
        holder.pack_start(sub, False, False, 0)
        holder.show_all()

    def change(output, mode=None, scale=None, transform=None):
        previous = dict(output)
        width = height = None
        if mode:
            width, height = (int(x) for x in mode.split("x"))
        if not apply_output(output["name"], width, height, None, scale, transform):
            win.error(_("The display settings could not be applied."))
            return
        if confirm_display(win):
            stored = dict(get_settings()["display.outputs"] or {})
            entry = dict(stored.get(output["name"], {}))
            if width:
                entry.update(width=width, height=height)
            if scale:
                entry["scale"] = scale
            if transform:
                entry["transform"] = transform
            stored[output["name"]] = entry
            get_settings().set("display.outputs", stored)
        else:
            cur = next((m for m in previous.get("modes", []) if m.get("current")), None)
            apply_output(previous["name"], cur["width"] if cur else None, cur["height"] if cur else None,
                         None, float(previous.get("scale", 1.0)), previous.get("transform", "normal"))
            win.show_page("display")

    select(state["output"])
    p.tool_link(_("Advanced display settings"), ["wdisplays"])
    return p


def confirm_display(win):
    """'Keep these display settings?' with a 15 second auto-revert."""
    dialog = Gtk.MessageDialog(transient_for=win, modal=True, message_type=Gtk.MessageType.QUESTION,
                               text=_("Keep these display settings?"))
    dialog.add_button(_("Keep changes"), Gtk.ResponseType.YES)
    dialog.add_button(_("Revert"), Gtk.ResponseType.NO)
    remaining = {"s": 15}

    def tick():
        remaining["s"] -= 1
        dialog.format_secondary_text(_("Reverting to previous display settings in %d seconds.") % remaining["s"])
        if remaining["s"] <= 0:
            dialog.response(Gtk.ResponseType.NO)
            return False
        return True

    dialog.format_secondary_text(_("Reverting to previous display settings in %d seconds.") % 15)
    timer = GLib.timeout_add_seconds(1, tick)
    result = dialog.run() == Gtk.ResponseType.YES
    if remaining["s"] > 0:
        GLib.source_remove(timer)
    dialog.destroy()
    return result


def page_sound(win):
    p = Page(_("Sound"))
    audio = service("audio")
    if not audio.available:
        p.text(_("pactl is not installed, so sound devices can't be shown."))
        return p
    p.section(_("Output"))
    sinks = [(d.name, d.description) for d in audio.sinks] or [("", _("No output devices found"))]
    p.combo(_("Choose your output device"), sinks, getter=lambda: audio.default_sink,
            setter=audio.set_default_sink, width=380)
    p.slider(_("Master volume"), 0, 100, 1, getter=lambda: audio.volume, setter=audio.set_volume)
    p.section(_("Input"))
    sources = [(d.name, d.description) for d in audio.sources] or [("", _("No input devices found"))]
    p.combo(_("Choose your input device"), sources, getter=lambda: audio.default_source,
            setter=audio.set_default_source, width=380)
    src = audio.source
    p.slider(_("Microphone volume"), 0, 100, 1, getter=lambda: src.volume if src else 0,
             setter=audio.set_source_volume)
    p.section(_("Related settings"))
    p.tool_link(_("Sound Control Panel"), ["pavucontrol"], ["gnome-control-center", "sound"])
    return p


def page_notifications(win):
    p = Page(_("Notifications & actions"))
    p.section(_("Notifications"))
    p.toggle(_("Get notifications from apps and other senders"), "notifications.enabled")
    p.toggle(_("Focus assist: only show priority notifications"), "notifications.focus_assist")
    p.section(_("Quick actions"))
    p.check(_("Show all quick actions in the Action center"), "quickactions.expanded")
    return p


def page_power(win):
    p = Page(_("Power & sleep"))
    p.section(_("Screen"))
    p.combo(_("Lock the screen after"), minutes_options(), "power.lock_after_min")
    p.section(_("Sleep"))
    p.combo(_("PC goes to sleep after"), minutes_options(), "power.suspend_after_min")
    p.check(_("Lock the screen when the PC goes to sleep"), "power.lock_on_suspend")
    power = service("power")
    profiles = power.available_profiles()
    if profiles:
        p.section(_("Power mode"))
        names = {"power-saver": _("Battery saver"), "balanced": _("Balanced"), "performance": _("Best performance")}
        p.combo(None, [(x, names.get(x, x)) for x in profiles], getter=lambda: power.profile,
                setter=power.set_profile)
    if power.has_battery:
        p.section(_("Battery"))
        p.text(_("Battery level: %d %%") % power.percent, dim=False)
    return p


def page_storage(win):
    p = Page(_("Storage"))
    from tenwin.explorer.places import drives
    p.section(_("Local storage"))
    for name, _location, _icon, _obj, free, size in drives():
        if not size:
            continue
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.pack_start(Gtk.Label(label=name, xalign=0), False, False, 0)
        bar = Gtk.LevelBar()
        bar.set_min_value(0)
        bar.set_max_value(1)
        bar.set_value((size - free) / size)
        bar.set_size_request(420, 10)
        box.pack_start(bar, False, False, 0)
        box.pack_start(add_class(Gtk.Label(label=_("%s used, %s free") % (human_size(size - free), human_size(free)),
                                           xalign=0), "tw-dim"), False, False, 0)
        p.add(box, 8)
    p.tool_link(_("Disk Usage Analyzer"), ["baobab"])
    p.tool_link(_("Disks"), ["gnome-disks"])
    return p


def _read(path, key=None):
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if key is None:
                    return line.strip()
                if line.startswith(key):
                    return line.split(":", 1)[1].strip() if ":" in line else line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


def page_about(win):
    p = Page(_("About"))
    p.text(_("Your PC is monitored and protected."), dim=False)
    p.section(_("Device specifications"))
    mem_kb = _read("/proc/meminfo", "MemTotal").split(" ")[0]
    try:
        memory = human_size(int(mem_kb) * 1024)
    except ValueError:
        memory = "?"
    rows = [
        (_("Device name"), socket.gethostname()),
        (_("Processor"), _read("/proc/cpuinfo", "model name") or platform.processor()),
        (_("Installed RAM"), memory),
        (_("System type"), _("%s operating system") % platform.machine()),
    ]
    p.info_rows(rows)
    text = "\n".join("%s\t%s" % r for r in rows)
    p.button(_("Copy"), lambda: Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1))
    p.button(_("Rename this PC"), lambda: rename_pc(win))
    p.section(_("Operating system specifications"))
    osinfo = [
        (_("Edition"), _read("/etc/os-release", "PRETTY_NAME") or platform.system()),
        (_("Kernel"), platform.release()),
        (_("Desktop"), "Tenwin %s" % __version__),
    ]
    p.info_rows(osinfo)
    return p


def rename_pc(win):
    dialog = Gtk.Dialog(title=_("Rename your PC"), transient_for=win, modal=True)
    dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
    dialog.add_button(_("Next"), Gtk.ResponseType.OK)
    box = dialog.get_content_area()
    box.set_spacing(8)
    box.set_margin_start(20)
    box.set_margin_end(20)
    box.set_margin_top(12)
    box.pack_start(Gtk.Label(label=_("You can use a combination of letters, hyphens, and numbers."), xalign=0),
                   False, False, 0)
    entry = Gtk.Entry(text=socket.gethostname())
    box.pack_start(entry, False, False, 6)
    dialog.show_all()
    if dialog.run() == Gtk.ResponseType.OK:
        name = entry.get_text().strip()
        valid = name and len(name) <= 63 and all(c.isalnum() or c == "-" for c in name) and not name.startswith("-")
        if valid:
            try:
                bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
                bus.call_sync("org.freedesktop.hostname1", "/org/freedesktop/hostname1",
                              "org.freedesktop.hostname1", "SetStaticHostname",
                              GLib.Variant("(sb)", (name, True)), None, Gio.DBusCallFlags.NONE, 60000, None)
            except GLib.Error as exc:
                win.error(_("The PC could not be renamed."), exc.message)
        else:
            win.error(_("The name is not valid."))
    dialog.destroy()
    win.show_page("about")


# ------------------------------------------------------------------ Devices

def page_bluetooth(win):
    p = Page(_("Bluetooth & other devices"))
    bt = service("bluetooth")
    if bt.available:
        p.toggle(_("Bluetooth"), getter=lambda: bt.powered, setter=bt.set_powered)
    else:
        p.text(_("No Bluetooth adapter was found."))
    p.tool_link(_("Add Bluetooth or other device"), ["blueman-manager"], ["gnome-control-center", "bluetooth"])
    return p


def page_printers(win):
    p = Page(_("Printers & scanners"))
    p.text(_("Printers are managed by the system printing service (CUPS)."))
    if not p.tool_link(_("Add a printer or scanner"), ["system-config-printer"], ["gnome-control-center", "printers"]):
        p.link(_("Open the CUPS web interface"), lambda: system.run(["xdg-open", "http://localhost:631/"]))
    return p


def page_mouse(win):
    p = Page(_("Mouse & touchpad"))
    p.combo(_("Select your primary button"), [(False, _("Left")), (True, _("Right"))], "input.left_handed")
    p.slider(_("Cursor speed"), -1.0, 1.0, 0.1, "input.pointer_speed", fmt=lambda v: "%+.1f" % v)
    p.toggle(_("Reverse scrolling direction (natural scrolling)"), "input.natural_scroll")
    p.section(_("Touchpad"))
    p.toggle(_("Tap with a single finger to single-click"), "input.tap_to_click")
    return p


def page_typing(win):
    p = Page(_("Keyboard"))
    p.slider(_("Repeat delay (ms)"), 150, 1000, 10, "input.repeat_delay")
    p.slider(_("Repeat rate (characters per second)"), 5, 60, 1, "input.repeat_rate")
    p.toggle(_("Turn on Num Lock at sign-in"), "input.numlock")
    p.link(_("Keyboard layout and input languages"), lambda: win.show_page("region"))
    return p


# ------------------------------------------------------------------ Network

def page_network_status(win):
    p = Page(_("Status"))
    net = service("network")
    p.section(_("Network status"))
    kind, name, _strength = net.primary()
    if kind == "none":
        p.text(_("You're not connected to any networks."), dim=False)
    else:
        p.add(icon_image("tenwin-network" if kind != "wifi" else "tenwin-wifi-3", 64, symbolic=True))
        p.text("%s\n%s" % (name, _("You're connected to the Internet")), dim=False)
    p.tool_link(_("Change connection properties"), ["nm-connection-editor"])
    p.section(_("Advanced network settings"))
    p.tool_link(_("Network and Sharing Center"), ["nm-connection-editor"], ["gnome-control-center", "network"])
    return p


def page_wifi(win):
    p = Page(_("Wi-Fi"))
    net = service("network")
    if not net.has_wifi:
        p.text(_("No Wi-Fi adapter was found."))
        return p
    p.toggle(_("Wi-Fi"), getter=lambda: net.wifi_enabled, setter=net.set_wifi_enabled)
    p.tool_link(_("Manage known networks"), ["nm-connection-editor"])
    return p


def page_airplane(win):
    p = Page(_("Airplane mode"))
    net = service("network")
    bt = service("bluetooth")

    def set_mode(on):
        net.set_airplane_mode(on)
        if bt.available:
            bt.set_powered(not on)

    p.toggle(_("Stop all wireless communication"), getter=lambda: net.airplane_mode, setter=set_mode)
    return p


def page_vpn(win):
    p = Page(_("VPN"))
    p.text(_("VPN connections are managed by NetworkManager."))
    p.tool_link(_("Add a VPN connection"), ["nm-connection-editor", "--create", "--type=vpn"], ["nm-connection-editor"])
    return p


# ------------------------------------------------------------------ Personalization

def wallpaper_candidates():
    seen, result = set(), []
    dirs = [str(paths.WALLPAPER_DIR), "/usr/share/backgrounds", os.path.expanduser("~/Pictures/Wallpapers")]
    for directory in dirs:
        for root, _dirs, files in os.walk(directory):
            for name in sorted(files):
                if name.lower().endswith((".png", ".jpg", ".jpeg", ".svg", ".webp")):
                    path = os.path.join(root, name)
                    real = os.path.realpath(path)
                    if real not in seen:
                        seen.add(real)
                        result.append(path)
            if len(result) > 40:
                break
    return result


def thumbnail_grid(paths_, current, on_pick):
    flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=6, row_spacing=6)
    flow.set_max_children_per_line(5)
    flow.set_min_children_per_line(3)
    for path in paths_:
        button = flat_button(css="tw-thumb")
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 120, 68, False)
            button.add(Gtk.Image.new_from_pixbuf(pixbuf))
        except GLib.Error:
            continue
        set_class(button, "selected", path == current)
        button.set_tooltip_text(os.path.basename(path))
        button.connect("clicked", lambda _b, pth=path: on_pick(pth))
        flow.add(button)
    return flow


def page_background(win):
    p = Page(_("Background"))
    s = get_settings()
    preview = add_class(Gtk.DrawingArea(), "tw-preview")
    preview.set_size_request(340, 192)
    from tenwin.desktop.app import Wallpaper
    wallpaper = Wallpaper()

    def draw(widget, cr):
        a = widget.get_allocation()
        wallpaper.draw(cr, a.width, a.height)
        return False

    preview.connect("draw", draw)
    p.add(preview, 8)
    s.connect("changed", lambda *_: preview.queue_draw())
    p.combo(_("Background"), [("picture", _("Picture")), ("color", _("Solid color"))], "background.type",
            setter=lambda _v: win.show_page("background"))
    if s["background.type"] == "picture":
        p.caption(_("Choose your picture"))
        current = s["background.picture"] or paths.default_wallpaper()
        p.add(thumbnail_grid(wallpaper_candidates(), current, lambda pth: (s.set("background.picture", pth),
                                                                           win.show_page("background"))))
        p.button(_("Browse"), lambda: browse_image(win, "background.picture"))
        p.combo(_("Choose a fit"), [("fill", _("Fill")), ("fit", _("Fit")), ("stretch", _("Stretch")),
                                    ("tile", _("Tile")), ("center", _("Center"))], "background.fit")
    else:
        p.caption(_("Choose your background color"))
        p.add(color_grid(ACCENT_COLORS[:24] + ["#000000", "#1f1f1f", "#2d7d9a", "#004b50"],
                         s["background.color"], lambda c: s.set("background.color", c)))
    return p


def color_grid(colors, current, on_pick, columns=8):
    grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=2, row_spacing=2)
    grid.set_max_children_per_line(columns)
    grid.set_min_children_per_line(columns)
    grid.set_halign(Gtk.Align.START)
    for color in colors:
        button = flat_button(css="tw-swatch")
        area = Gtk.DrawingArea()
        area.set_size_request(42, 42)
        rgba = Gdk.RGBA()
        rgba.parse(color)

        def draw(_w, cr, c=rgba, sel=(color.lower() == (current or "").lower())):
            cr.set_source_rgb(c.red, c.green, c.blue)
            cr.paint()
            if sel:
                cr.set_source_rgb(1, 1, 1)
                cr.set_line_width(2)
                cr.rectangle(2, 2, 38, 38)
                cr.stroke()
                cr.move_to(26, 32)
                cr.line_to(30, 36)
                cr.line_to(37, 28)
                cr.stroke()
            return False

        area.connect("draw", draw)
        button.add(area)
        button.set_tooltip_text(color)
        button.connect("clicked", lambda _b, c=color: on_pick(c))
        grid.add(button)
    return grid


def browse_image(win, key):
    dialog = Gtk.FileChooserDialog(title=_("Choose a picture"), transient_for=win, action=Gtk.FileChooserAction.OPEN)
    dialog.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("Choose picture"), Gtk.ResponseType.OK)
    filt = Gtk.FileFilter()
    filt.set_name(_("Images"))
    filt.add_pixbuf_formats()
    dialog.add_filter(filt)
    dialog.set_current_folder(paths.xdg_user_dir("PICTURES"))
    if dialog.run() == Gtk.ResponseType.OK:
        get_settings().set(key, dialog.get_filename())
    dialog.destroy()
    win.show_page(win.current_page)


def page_colors(win):
    p = Page(_("Colors"))
    s = get_settings()
    shell, app = s["appearance.shell_mode"], s["appearance.app_mode"]
    mode = "light" if shell == app == "light" else "dark" if shell == app == "dark" else "custom"

    def choose(value):
        if value in ("light", "dark"):
            s.update({"appearance.shell_mode": value, "appearance.app_mode": value})
        win.show_page("colors")

    p.combo(_("Choose your color"), [("light", _("Light")), ("dark", _("Dark")), ("custom", _("Custom"))],
            getter=lambda: mode, setter=choose)
    if mode == "custom":
        p.radios(_("Choose your default Windows mode"), [("light", _("Light")), ("dark", _("Dark"))],
                 "appearance.shell_mode")
        p.radios(_("Choose your default app mode"), [("light", _("Light")), ("dark", _("Dark"))],
                 "appearance.app_mode")
    p.toggle(_("Transparency effects"), "appearance.transparency")
    p.section(_("Choose your accent color"))
    p.add(color_grid(ACCENT_COLORS, s["appearance.accent"],
                     lambda c: (s.set("appearance.accent", c), win.show_page("colors"))), 4)

    def custom_color():
        dialog = Gtk.ColorChooserDialog(title=_("Choose a custom accent color"), transient_for=win)
        rgba = Gdk.RGBA()
        rgba.parse(s["appearance.accent"])
        dialog.set_rgba(rgba)
        if dialog.run() == Gtk.ResponseType.OK:
            c = dialog.get_rgba()
            s.set("appearance.accent", "#%02X%02X%02X" % (round(c.red * 255), round(c.green * 255),
                                                          round(c.blue * 255)))
        dialog.destroy()
        win.show_page("colors")

    p.link(_("Custom color"), custom_color)
    p.section(_("Show accent color on the following surfaces"))
    p.check(_("Start, taskbar, and action center"), "appearance.accent_on_surfaces")
    p.check(_("Title bars and window borders"), "appearance.accent_on_titlebars")
    return p


def page_lockscreen(win):
    p = Page(_("Lock screen"))
    s = get_settings()
    use_desktop = not s["lockscreen.picture"]

    def set_same(v):
        s.set("lockscreen.picture", "" if v else (s["background.picture"] or paths.default_wallpaper()))
        win.show_page("lockscreen")

    p.toggle(_("Use the desktop background on the lock screen"), getter=lambda: use_desktop, setter=set_same)
    if not use_desktop:
        p.caption(_("Choose your picture"))
        p.add(thumbnail_grid(wallpaper_candidates(), s["lockscreen.picture"],
                             lambda pth: (s.set("lockscreen.picture", pth), win.show_page("lockscreen"))))
        p.button(_("Browse"), lambda: browse_image(win, "lockscreen.picture"))
    p.link(_("Screen timeout settings"), lambda: win.show_page("power"))
    p.button(_("Lock now (Win+L)"), system.lock)
    return p


def page_start(win):
    p = Page(_("Start"))
    p.toggle(_("Show most used apps"), "start.show_most_used")
    p.toggle(_("Show recently added apps"), "start.show_recently_added")
    p.section(_("Choose which folders appear on Start"))
    s = get_settings()
    for key, label in (("explorer", _("File Explorer")), ("settings", _("Settings")), ("documents", _("Documents")),
                       ("downloads", _("Downloads")), ("music", _("Music")), ("pictures", _("Pictures")),
                       ("videos", _("Videos"))):
        def setter(on, k=key):
            folders = [f for f in s["start.folders"] if f != k]
            if on:
                folders.append(k)
            s.set("start.folders", folders)
        p.check(label, getter=lambda k=key: k in s["start.folders"], setter=setter)
    p.section(_("Tiles"))
    p.button(_("Reset tiles to the default layout"), lambda: s.set("start.tiles", None))
    return p


def page_taskbar(win):
    p = Page(_("Taskbar"))
    p.toggle(_("Use small taskbar buttons"), "taskbar.small_icons")
    p.combo(_("Taskbar location on screen"), [("bottom", _("Bottom")), ("top", _("Top"))], "taskbar.position")
    p.combo(_("Search"), [("box", _("Show search box")), ("icon", _("Show search icon")), ("hidden", _("Hidden"))],
            "taskbar.search")
    p.toggle(_("Show Task View button"), "taskbar.show_taskview")
    p.section(_("Notification area"))
    p.toggle(_("Always show all icons in the notification area"), "taskbar.tray_show_all")
    p.toggle(_("Show seconds in the clock"), "region.clock_seconds")
    return p


def page_desktop_icons(win):
    p = Page(_("Desktop icons"))
    p.check(_("This PC"), "desktop.show_this_pc")
    p.check(_("User's Files"), "desktop.show_home")
    p.check(_("Recycle Bin"), "desktop.show_trash")
    p.check(_("Show desktop icons"), "desktop.show_icons")
    p.combo(_("Icon size"), [("large", _("Large icons")), ("medium", _("Medium icons")), ("small", _("Small icons"))],
            "desktop.icon_size")
    return p


# ------------------------------------------------------------------ Apps

def page_apps_features(win):
    p = Page(_("Apps & features"))
    from tenwin.apps import get_registry
    p.text(_("Search, sort, and filter by drive. If you would like to uninstall or move an app, select it from the "
             "list."))
    search = Gtk.SearchEntry(placeholder_text=_("Search this list"))
    search.set_size_request(300, -1)
    search.set_halign(Gtk.Align.START)
    p.add(search, 6)
    listbox = add_class(Gtk.ListBox(), "tw-app-list")
    listbox.set_selection_mode(Gtk.SelectionMode.NONE)
    p.add(listbox)
    store = shutil.which("gnome-software") or shutil.which("snap-store")
    for info in get_registry().apps:
        row = Gtk.ListBoxRow()
        box = Gtk.Box(spacing=12)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.pack_start(icon_image(info.get_icon(), 32), False, False, 0)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        texts.pack_start(Gtk.Label(label=info.get_display_name(), xalign=0), False, False, 0)
        desc = add_class(Gtk.Label(label=info.get_description() or "", xalign=0), "tw-dim")
        desc.set_ellipsize(Pango.EllipsizeMode.END)
        desc.set_max_width_chars(50)
        texts.pack_start(desc, False, False, 0)
        box.pack_start(texts, True, True, 0)
        if store:
            button = Gtk.Button(label=_("Uninstall"))
            add_class(button, "tw-gray-button")
            button.connect("clicked", lambda _b, i=info: system.run(
                ["gnome-software", "--details=%s" % i.get_id()] if shutil.which("gnome-software") else ["snap-store"]))
            box.pack_end(button, False, False, 0)
        row.add(box)
        row.app_name = info.get_display_name().casefold()
        listbox.add(row)
    listbox.set_filter_func(lambda row: search.get_text().casefold() in row.app_name)
    search.connect("search-changed", lambda *_: listbox.invalidate_filter())
    return p


DEFAULT_TYPES = [
    ("web", N_("Web browser"), ["x-scheme-handler/http", "x-scheme-handler/https", "text/html"]),
    ("mail", N_("Email"), ["x-scheme-handler/mailto"]),
    ("music", N_("Music player"), ["audio/mpeg", "audio/flac", "audio/ogg", "audio/x-wav"]),
    ("video", N_("Video player"), ["video/mp4", "video/x-matroska", "video/webm"]),
    ("photo", N_("Photo viewer"), ["image/jpeg", "image/png", "image/gif", "image/webp"]),
    ("text", N_("Text editor"), ["text/plain"]),
    ("pdf", N_("PDF viewer"), ["application/pdf"]),
]


def page_default_apps(win):
    p = Page(_("Default apps"))
    for _key, title, types in DEFAULT_TYPES:
        apps = Gio.AppInfo.get_all_for_type(types[0])
        if not apps:
            continue
        current = Gio.AppInfo.get_default_for_type(types[0], False)

        def setter(app_id, t=types, candidates=apps):
            app = next((a for a in candidates if a.get_id() == app_id), None)
            if app is None:
                return
            for mime in t:
                try:
                    app.set_as_default_for_type(mime)
                except GLib.Error:
                    pass

        p.combo(_(title), [(a.get_id(), a.get_display_name()) for a in apps],
                getter=lambda c=current: c.get_id() if c else None, setter=setter, width=320)
    return p


def autostart_entries():
    from tenwin.autostart import collect_entries
    result = []
    for name, path in collect_entries().items():
        keyfile = GLib.KeyFile()
        try:
            keyfile.load_from_file(path, GLib.KeyFileFlags.KEEP_TRANSLATIONS)
            title = keyfile.get_locale_string("Desktop Entry", "Name", None)
        except GLib.Error:
            continue
        try:
            hidden = keyfile.get_boolean("Desktop Entry", "Hidden")
        except GLib.Error:
            hidden = False
        result.append((name, path, title, not hidden))
    return sorted(result, key=lambda e: e[2].casefold())


def set_autostart(name, path, enabled):
    user_dir = os.path.join(GLib.get_user_config_dir(), "autostart")
    os.makedirs(user_dir, exist_ok=True)
    target = os.path.join(user_dir, name)
    keyfile = GLib.KeyFile()
    keyfile.load_from_file(path, GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
    keyfile.set_boolean("Desktop Entry", "Hidden", not enabled)
    keyfile.save_to_file(target)


def page_startup(win):
    p = Page(_("Startup"))
    p.text(_("Apps can be configured to start when you sign in."))
    for name, path, title, enabled in autostart_entries():
        p.toggle(title, getter=lambda e=enabled: e, setter=lambda on, n=name, pth=path: set_autostart(n, pth, on))
    return p


# ------------------------------------------------------------------ Accounts

def accounts_user_path():
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        res = bus.call_sync("org.freedesktop.Accounts", "/org/freedesktop/Accounts", "org.freedesktop.Accounts",
                            "FindUserByName", GLib.Variant("(s)", (GLib.get_user_name(),)),
                            GLib.VariantType.new("(o)"), Gio.DBusCallFlags.NONE, 2000, None)
        return bus, res.unpack()[0]
    except GLib.Error:
        return None, None


def avatar_path():
    face = os.path.expanduser("~/.face")
    if os.path.exists(face):
        return face
    candidate = "/var/lib/AccountsService/icons/%s" % GLib.get_user_name()
    return candidate if os.path.exists(candidate) else None


def page_your_info(win):
    p = Page(_("Your info"))
    avatar = avatar_path()
    if avatar:
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(avatar, 160, 160, True)
            p.add(Gtk.Image.new_from_pixbuf(pixbuf), 8)
        except GLib.Error:
            p.add(icon_image("tenwin-user", 96, symbolic=True), 8)
    else:
        p.add(icon_image("tenwin-user", 96, symbolic=True), 8)
    p.add(add_class(Gtk.Label(label=GLib.get_real_name() or GLib.get_user_name(), xalign=0), "tw-h2"))
    p.text(GLib.get_user_name())
    p.section(_("Create your picture"))

    def choose():
        dialog = Gtk.FileChooserDialog(title=_("Browse for one"), transient_for=win, action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("Choose picture"), Gtk.ResponseType.OK)
        filt = Gtk.FileFilter()
        filt.add_pixbuf_formats()
        dialog.add_filter(filt)
        if dialog.run() == Gtk.ResponseType.OK:
            set_avatar(dialog.get_filename(), win)
        dialog.destroy()
        win.show_page("your-info")

    p.link(_("Browse for one"), choose)
    p.tool_link(_("Manage my account"), ["gnome-control-center", "users"])
    return p


def set_avatar(source, win):
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(source, 256, 256, True)
        face = os.path.expanduser("~/.face")
        pixbuf.savev(face, "png", [], [])
    except GLib.Error as exc:
        win.error(_("The picture could not be used."), exc.message)
        return
    bus, user_path = accounts_user_path()
    if bus is not None:
        try:
            bus.call_sync("org.freedesktop.Accounts", user_path, "org.freedesktop.Accounts.User", "SetIconFile",
                          GLib.Variant("(s)", (face,)), None, Gio.DBusCallFlags.NONE, 5000, None)
        except GLib.Error:
            pass  # ~/.face is still used by the lock screen


def page_sign_in(win):
    p = Page(_("Sign-in options"))
    p.section(_("Password"))
    p.text(_("Change your account password."))

    def change_password():
        term = system.terminal_command()
        if shutil.which("gnome-control-center"):
            system.run(["gnome-control-center", "users"])
        elif term:
            system.run([term, "-e", "passwd"])

    p.button(_("Change"), change_password)
    p.section(_("Require sign-in"))
    p.check(_("Lock the screen when the PC wakes up from sleep"), "power.lock_on_suspend")
    return p


# ------------------------------------------------------------------ Time & language

def timedate_call(method, args, signature):
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    bus.call_sync("org.freedesktop.timedate1", "/org/freedesktop/timedate1", "org.freedesktop.timedate1", method,
                  GLib.Variant(signature, args), None, Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION, 60000, None)


def timedate_prop(name, default=None):
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        res = bus.call_sync("org.freedesktop.timedate1", "/org/freedesktop/timedate1",
                            "org.freedesktop.DBus.Properties", "Get",
                            GLib.Variant("(ss)", ("org.freedesktop.timedate1", name)), None,
                            Gio.DBusCallFlags.NONE, 2000, None)
        return res.unpack()[0]
    except GLib.Error:
        return default


def timezones():
    try:
        out = subprocess.run(["timedatectl", "list-timezones"], capture_output=True, text=True, timeout=5).stdout
        return [z for z in out.splitlines() if z]
    except (OSError, subprocess.SubprocessError):
        return []


def page_datetime(win):
    p = Page(_("Date & time"))
    now = GLib.DateTime.new_now_local()
    p.add(add_class(Gtk.Label(label=now.format("%H:%M, %x"), xalign=0), "tw-h2"))

    def set_ntp(on):
        try:
            timedate_call("SetNTP", (on, True), "(bb)")
        except GLib.Error as exc:
            win.error(_("The setting could not be changed."), exc.message)

    p.toggle(_("Set time automatically"), getter=lambda: bool(timedate_prop("NTP", False)), setter=set_ntp)
    zones = timezones()
    current = timedate_prop("Timezone", "")
    if zones:
        def set_zone(zone):
            try:
                timedate_call("SetTimezone", (zone, True), "(sb)")
            except GLib.Error as exc:
                win.error(_("The time zone could not be changed."), exc.message)

        p.combo(_("Time zone"), [(z, z.replace("_", " ")) for z in zones], getter=lambda: current, setter=set_zone,
                width=320)
    p.section(_("Formats"))
    p.toggle(_("Use 24-hour clock"), "region.clock_24h")
    return p


KEYBOARD_LAYOUTS = [
    ("de", "Deutsch"), ("de(nodeadkeys)", "Deutsch (ohne Akzenttasten)"), ("at", "Deutsch (Österreich)"),
    ("ch", "Deutsch (Schweiz)"), ("us", "English (US)"), ("gb", "English (UK)"), ("fr", "Français"),
    ("es", "Español"), ("it", "Italiano"), ("nl", "Nederlands"), ("pl", "Polski"), ("tr", "Türkçe"),
]


def page_region(win):
    p = Page(_("Region & language"))
    p.combo(_("Windows display language"), [("auto", _("Use system language")), ("de", "Deutsch"),
                                            ("en", "English")], "region.language")
    p.text(_("Sign out and back in for the language change to take effect everywhere."))
    p.section(_("Keyboards"))
    s = get_settings()
    layouts = [l for l in s["input.keyboard_layouts"].split(",") if l]
    flow = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    names = dict(KEYBOARD_LAYOUTS)
    for layout in layouts:
        row = Gtk.Box(spacing=10)
        row.pack_start(icon_image("tenwin-keyboard", 16, symbolic=True), False, False, 0)
        row.pack_start(Gtk.Label(label=names.get(layout, layout), xalign=0), True, True, 0)
        if len(layouts) > 1:
            remove = Gtk.Button(label=_("Remove"))
            add_class(remove, "tw-gray-button")
            remove.connect("clicked", lambda _b, l=layout: (s.set("input.keyboard_layouts", ",".join(
                x for x in layouts if x != l)), win.show_page("region")))
            row.pack_end(remove, False, False, 0)
        flow.pack_start(row, False, False, 0)
    p.add(flow)
    available = [(k, v) for k, v in KEYBOARD_LAYOUTS if k not in layouts]
    p.combo(_("Add a keyboard"), [("", "")] + available, getter=lambda: "",
            setter=lambda v: v and (s.set("input.keyboard_layouts", ",".join(layouts + [v])),
                                    win.show_page("region")))
    if len(layouts) > 1:
        p.text(_("Press Win+Space to switch between keyboards."))
    return p


# ------------------------------------------------------------------ Ease of access

def page_ease_display(win):
    p = Page(_("Display"))
    p.slider(_("Make text bigger"), 1.0, 2.25, 0.05, "appearance.text_scale", fmt=lambda v: "%d %%" % round(v * 100))
    p.toggle(_("Show animations"), "appearance.animations")
    p.toggle(_("Show transparency"), "appearance.transparency")
    p.combo(_("Change pointer size"), [(24, _("Normal")), (32, _("Large")), (48, _("Extra large"))],
            "appearance.cursor_size")
    p.text(_("Pointer size changes apply to new windows; sign out to apply them everywhere."))
    return p


# ------------------------------------------------------------------ Update

def page_windows_update(win):
    p = Page(_("Software update"))
    p.add(icon_image("tenwin-update", 64, symbolic=True), 6)
    p.text(_("Updates for the system and your apps are installed by the Ubuntu software updater."), dim=False)

    def check():
        for argv in (["update-manager"], ["gnome-software", "--mode=updates"], ["snap-store", "--mode=updates"]):
            if shutil.which(argv[0]):
                system.run(argv)
                return
        term = system.terminal_command()
        if term:
            system.run([term, "-e", "sh", "-c", "sudo apt update && sudo apt upgrade; read -r _"])

    p.button(_("Check for updates"), check, accent=True)
    p.section(_("Reset"))
    p.text(_("Reset all Tenwin settings to their defaults. Your files are not affected."))

    def reset():
        dialog = Gtk.MessageDialog(transient_for=win, modal=True, message_type=Gtk.MessageType.WARNING,
                                   buttons=Gtk.ButtonsType.YES_NO, text=_("Reset all Tenwin settings?"))
        if dialog.run() == Gtk.ResponseType.YES:
            s = get_settings()
            s.update({k: v for k, v in DEFAULTS.items() if k != "session.first_run_done"})
        dialog.destroy()

    p.button(_("Reset settings"), reset)
    return p


PAGE_BUILDERS = {
    "display": page_display, "sound": page_sound, "notifications": page_notifications, "power": page_power,
    "storage": page_storage, "about": page_about, "bluetooth": page_bluetooth, "printers": page_printers,
    "mouse": page_mouse, "typing": page_typing, "network-status": page_network_status, "wifi": page_wifi,
    "airplane": page_airplane, "vpn": page_vpn, "background": page_background, "colors": page_colors,
    "lockscreen": page_lockscreen, "start": page_start, "taskbar": page_taskbar,
    "desktop-icons": page_desktop_icons, "apps-features": page_apps_features, "default-apps": page_default_apps,
    "startup": page_startup, "your-info": page_your_info, "sign-in": page_sign_in, "datetime": page_datetime,
    "region": page_region, "ease-display": page_ease_display, "windows-update": page_windows_update,
}
