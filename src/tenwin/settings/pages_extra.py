"""Settings pages: Multitasking, Tablet mode, Themes, Fonts, Gaming, Privacy and
the Ease of Access pages for the magnifier, high contrast, Narrator and keyboard."""

import os
import shutil

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from tenwin import designs, fonts, privacy
from tenwin.config import get_settings
from tenwin.gtkutil import add_class, clear_children, flat_button
from tenwin.i18n import N_, _
from tenwin.services import system
from tenwin.settings.widgets import Page


# ------------------------------------------------------------------ System

def page_multitasking(win):
    p = Page(_("Multitasking"))
    p.section(_("Snap windows"))
    p.toggle(_("When I snap a window, show what I can snap next to it"), "snap.assist")
    p.text(_("Win+Left and Win+Right snap a window to one half of the screen; Win+Up and Win+Down then make it "
             "a quarter. Drag a window to the edge of the screen to snap it to a half, or hold Win (or Ctrl, Alt, "
             "Shift) while dragging to snap it into a quarter."))
    p.section(_("Arrange windows"))
    p.text(_("Right-click the taskbar to cascade the open windows, or to show them stacked or side by side."))
    p.section(_("Virtual desktops"))
    p.combo(_("Number of desktops"), [(n, str(n)) for n in range(1, 11)], "desktops.count", width=120)
    p.text(_("Switch desktops with Ctrl+Win+Left/Right, move a window with Ctrl+Win+Shift+Left/Right."))
    return p


def page_tablet(win):
    p = Page(_("Tablet mode"))
    p.toggle(_("Make Windows more touch-friendly when using your device as a tablet"), "tablet.mode")
    p.text(_("In tablet mode Start fills the screen, apps open maximized and the taskbar gets bigger buttons "
             "and a touch keyboard button."))
    p.toggle(_("Show the touch keyboard button on the taskbar"), "osk.show_button")
    p.button(_("Open the touch keyboard (Ctrl+Win+O)"), lambda: system.run(["tenwin-ctl", "osk"]))
    return p


# ------------------------------------------------------------------ Personalization

def page_themes(win):
    p = Page(_("Themes"))
    s = get_settings()
    p.section(_("Current theme: %s") % current_theme_name())
    summary = Gtk.Grid(column_spacing=24, row_spacing=4)
    picture = s["background.picture"] or str(designs.paths.default_wallpaper())
    rows = [(_("Background"), os.path.basename(picture) if s["background.type"] == "picture" else _("Solid color")),
            (_("Color"), {"manual": s["appearance.accent"], "wallpaper": _("Automatic"), "dark": _("Dark")}
             .get(s["appearance.accent_mode"], "")),
            (_("Mouse cursor"), s["appearance.cursor_theme"])]
    for i, (label, value) in enumerate(rows):
        summary.attach(add_class(Gtk.Label(label=label, xalign=0), "tw-dim"), 0, i, 1, 1)
        summary.attach(Gtk.Label(label=value or "–", xalign=0), 1, i, 1, 1)
    p.add(summary, 4)
    p.link(_("Background"), lambda: win.show_page("background"))
    p.link(_("Color"), lambda: win.show_page("colors"))
    cursors = designs.cursor_themes()
    if cursors:
        p.combo(_("Mouse cursor"), [(c, c) for c in cursors], "appearance.cursor_theme")

    def save():
        name = ask_text(win, _("Save theme"), _("Name your theme"), "")
        if name and designs.save_current(name):
            win.show_page("themes")

    p.button(_("Save theme"), save)
    p.section(_("Change theme"))
    flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=8, row_spacing=8)
    flow.set_max_children_per_line(3)
    flow.set_min_children_per_line(2)
    for theme in designs.all_themes():
        flow.add(theme_tile(win, theme))
    p.add(flow, 4)
    return p


def current_theme_name():
    for theme in designs.all_themes():
        if designs.is_current(theme):
            return designs.display_name(theme)
    return _("Custom")


def theme_tile(win, theme):
    button = flat_button(css="tw-theme-tile")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    picture = theme["values"].get("background.picture")
    preview = Gtk.Overlay()
    image = Gtk.Image()
    if picture and os.path.exists(picture):
        try:
            from gi.repository import GdkPixbuf
            image.set_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(picture, 160, 90, False))
        except Exception:  # unreadable picture: show the colour only
            pass
    image.set_size_request(160, 90)
    preview.add(image)
    accent = theme["values"].get("appearance.accent")
    if accent and theme["values"].get("appearance.accent_mode", "manual") == "manual":
        strip = Gtk.Box()
        strip.set_size_request(160, 12)
        strip.set_valign(Gtk.Align.END)
        provider = Gtk.CssProvider()
        provider.load_from_data(("box { background-color: %s; }" % accent).encode())
        strip.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        preview.add_overlay(strip)
    box.pack_start(preview, False, False, 0)
    label = Gtk.Label(label=designs.display_name(theme), xalign=0)
    label.set_ellipsize(Pango.EllipsizeMode.END)
    box.pack_start(label, False, False, 0)
    button.add(box)
    button.connect("clicked", lambda *_: (designs.apply(theme), win.show_page("themes")))
    if not theme.get("builtin"):
        def menu(_w, event):
            if event.button != 3:
                return False
            m = Gtk.Menu()
            item = Gtk.MenuItem(label=_("Delete"))
            item.connect("activate", lambda *_: (designs.delete(theme["name"]), win.show_page("themes")))
            m.append(item)
            m.show_all()
            m.popup_at_pointer(event)
            return True
        button.connect("button-release-event", menu)
    return button


def ask_text(win, title, prompt, text):
    dialog = Gtk.Dialog(title=title, transient_for=win, modal=True)
    dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
    dialog.add_button(_("Save"), Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.OK)
    area = dialog.get_content_area()
    area.set_spacing(8)
    for side in ("start", "end", "top", "bottom"):
        getattr(area, "set_margin_" + side)(16)
    area.pack_start(Gtk.Label(label=prompt, xalign=0), False, False, 0)
    entry = Gtk.Entry(text=text, activates_default=True)
    area.pack_start(entry, False, False, 0)
    dialog.show_all()
    response = dialog.run()
    value = entry.get_text().strip()
    dialog.destroy()
    return value if response == Gtk.ResponseType.OK else None


def page_fonts(win):
    p = Page(_("Fonts"))
    p.section(_("Add fonts"))
    drop = add_class(Gtk.Label(label=_("Drag and drop to install"), justify=Gtk.Justification.CENTER), "tw-font-drop")
    drop.set_size_request(480, 80)
    events = Gtk.EventBox()
    events.add(drop)
    events.drag_dest_set(Gtk.DestDefaults.ALL, [Gtk.TargetEntry.new("text/uri-list", 0, 0)], Gdk.DragAction.COPY)

    def dropped(_w, _ctx, _x, _y, data, _info, _time):
        files = [Gio.File.new_for_uri(u).get_path() for u in data.get_uris()]
        installed, errors = fonts.install([f for f in files if f])
        report(installed, errors)

    def report(installed, errors):
        message = []
        if installed:
            message.append(_("Installed: %s") % ", ".join(installed))
        if errors:
            message.append(_("Not a font file: %s") % ", ".join(errors))
        status.set_text("\n".join(message))

    events.connect("drag-data-received", dropped)
    p.add(events, 4)

    def browse():
        dialog = Gtk.FileChooserDialog(title=_("Install fonts"), transient_for=win, action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("Install"), Gtk.ResponseType.OK)
        dialog.set_select_multiple(True)
        flt = Gtk.FileFilter()
        flt.set_name(_("Font files"))
        for ext in fonts.FONT_EXTENSIONS:
            flt.add_pattern("*" + ext)
            flt.add_pattern("*" + ext.upper())
        dialog.add_filter(flt)
        if dialog.run() == Gtk.ResponseType.OK:
            report(*fonts.install(dialog.get_filenames()))
        dialog.destroy()

    p.button(_("Browse for fonts"), browse)
    status = p.text("")
    p.section(_("Available fonts"))
    search = Gtk.SearchEntry(placeholder_text=_("Search for fonts"))
    search.set_size_request(320, -1)
    search.set_halign(Gtk.Align.START)
    p.add(search, 4)
    flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=8, row_spacing=8)
    flow.set_max_children_per_line(3)
    flow.set_min_children_per_line(2)
    p.add(flow, 4)
    all_families = fonts.families()

    def fill(*_args):
        clear_children(flow)
        for family in fonts.filter_families(all_families, search.get_text())[:60]:
            card = add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4), "tw-font-card")
            card.set_size_request(170, 90)
            sample = Gtk.Label(label=_("The quick brown fox"), xalign=0)
            sample.set_ellipsize(Pango.EllipsizeMode.END)
            attrs = Pango.AttrList()
            attrs.insert(Pango.attr_family_new(family))
            attrs.insert(Pango.attr_size_new(16 * Pango.SCALE))
            sample.set_attributes(attrs)
            card.pack_start(sample, True, True, 0)
            name = Gtk.Label(label=family, xalign=0)
            name.set_ellipsize(Pango.EllipsizeMode.END)
            card.pack_start(name, False, False, 0)
            flow.add(card)
        flow.show_all()

    search.connect("search-changed", fill)
    fill()
    user = fonts.user_fonts()
    if user:
        p.section(_("Fonts you installed"))
        for name in user:
            row = Gtk.Box(spacing=12)
            row.pack_start(Gtk.Label(label=name, xalign=0), True, True, 0)
            remove = Gtk.Button(label=_("Uninstall"))
            remove.connect("clicked", lambda _b, n=name: (fonts.remove(n), win.show_page("fonts")))
            row.pack_end(remove, False, False, 0)
            p.add(row, 2)
    return p


# ------------------------------------------------------------------ Gaming

def page_game_bar(win):
    p = Page(_("Game Bar"))
    p.toggle(_("Open the Game Bar with Win+G"), "gaming.game_bar",
             description=_("Take screenshots, record the screen and watch the performance while you play."))
    p.section(_("Keyboard shortcuts"))
    grid = Gtk.Grid(column_spacing=32, row_spacing=4)
    for i, (label, keys) in enumerate(((_("Open Game Bar"), "Win+G"), (_("Take screenshot"), "Win+Alt+Print"),
                                       (_("Start/stop recording"), "Win+Alt+R"))):
        grid.attach(Gtk.Label(label=label, xalign=0), 0, i, 1, 1)
        grid.attach(add_class(Gtk.Label(label=keys, xalign=0), "tw-dim"), 1, i, 1, 1)
    p.add(grid, 4)
    return p


def page_captures(win):
    from tenwin.shell.gamebar import can_record, captures_dir
    p = Page(_("Captures"))
    folder = captures_dir()
    p.caption(_("Screenshots and recordings are saved to"))
    p.text(folder, dim=False)

    def open_folder():
        os.makedirs(folder, exist_ok=True)
        system.run(["tenwin-explorer", folder])

    p.button(_("Open folder"), open_folder)

    def change():
        dialog = Gtk.FileChooserDialog(title=_("Captures"), transient_for=win,
                                       action=Gtk.FileChooserAction.SELECT_FOLDER)
        dialog.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("Select folder"), Gtk.ResponseType.OK)
        if dialog.run() == Gtk.ResponseType.OK:
            get_settings().set("gaming.captures_dir", dialog.get_filename())
        dialog.destroy()
        win.show_page("captures")

    p.button(_("Change folder"), change)
    if not can_record():
        p.text(_("Screen recording needs the \"wf-recorder\" package."))
    return p


def page_game_mode(win):
    p = Page(_("Game Mode"))
    available = shutil.which("gamemoderun") is not None
    p.toggle(_("Game Mode"), "gaming.game_mode",
             description=_("Games started from Start run with Feral GameMode, which gives them priority "
                           "and the fastest CPU settings while they run."))
    if not available:
        p.text(_("Install the \"gamemode\" package to use Game Mode."))
    return p


# ------------------------------------------------------------------ Ease of Access

def page_ease_magnifier(win):
    from tenwin.session import labwc_version
    p = Page(_("Magnifier"))
    p.text(_("Win+Plus turns the magnifier on and zooms in, Win+Minus zooms out, Win+Esc turns it off."))
    p.combo(_("Change zoom level"), [(z, "%d %%" % z) for z in (200, 300, 400, 600, 800)],
            "ease.magnifier_zoom", width=140)
    if labwc_version() < (0, 8):
        p.text(_("With labwc %d.%d the magnifier shows an enlarged picture of the screen that follows the mouse; "
                 "press Win+Plus again to update it. labwc 0.8 or newer zooms live.") % labwc_version())
    p.button(_("Turn on Magnifier"), lambda: system.run(["tenwin-ctl", "magnifier", "in"]))
    return p


CONTRAST_THEMES = [("", N_("None")), ("contrast-1", N_("High Contrast #1")), ("contrast-2", N_("High Contrast #2")),
                   ("contrast-black", N_("High Contrast Black")), ("contrast-white", N_("High Contrast White"))]


def page_ease_contrast(win):
    p = Page(_("High contrast"))
    p.text(_("High contrast themes use a very limited set of distinct colors to make content easier to see."))
    p.combo(_("Choose a theme"), [(v, _(label)) for v, label in CONTRAST_THEMES], "appearance.contrast",
            setter=lambda _v: win.show_page("ease-contrast"))
    from tenwin import theme
    current = get_settings()["appearance.contrast"]
    if current in theme.CONTRAST:
        bg, fg, sel, sel_fg, link, _light = theme.CONTRAST[current]
        preview = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        provider = Gtk.CssProvider()
        provider.load_from_data(("box { background-color: %s; padding: 12px; border: 2px solid %s; }" % (bg, fg))
                                .encode())
        preview.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        for text, color, back in ((_("Text"), fg, None), (_("Hyperlinks"), link, None),
                                  (_("Selected text"), sel_fg, sel)):
            label = Gtk.Label(xalign=0)
            span = '<span foreground="%s"%s>%s</span>' % (color, ' background="%s"' % back if back else "",
                                                          GLib.markup_escape_text(text))
            label.set_markup(span)
            preview.pack_start(label, False, False, 0)
        preview.set_size_request(320, -1)
        p.add(preview, 8)
    p.text(_("Sign out and in again so that every app uses the new colors."))
    return p


def page_ease_narrator(win):
    p = Page(_("Narrator"))
    p.toggle(_("Use Narrator"), "ease.narrator",
             description=_("Narrator is a screen reader that describes what's on your screen (Ctrl+Win+Enter)."))
    if not shutil.which("orca"):
        p.text(_("Narrator uses the Orca screen reader. Install the \"orca\" package to use it."))
    else:
        p.tool_link(_("Narrator settings"), ["orca", "--setup"])
    return p


def page_ease_keyboard(win):
    p = Page(_("Keyboard"))
    p.section(_("Use your device without a physical keyboard"))
    p.button(_("Open the touch keyboard (Ctrl+Win+O)"), lambda: system.run(["tenwin-ctl", "osk"]))
    p.toggle(_("Show the touch keyboard button on the taskbar"), "osk.show_button")
    p.link(_("Typing settings"), lambda: win.show_page("typing"))
    return p


# ------------------------------------------------------------------ Privacy

def privacy_page(win, feature, title, master_text, key, note, apps_title):
    p = Page(title)
    p.toggle(master_text, key, setter=lambda on: (privacy.set_all(feature, on), win.show_page(win.current_page)))
    p.text(note)
    apps = privacy.app_permissions(feature)
    if apps:
        p.section(apps_title)
        for app_id, allowed in sorted(apps.items(), key=lambda kv: privacy.app_name(kv[0]).casefold()):
            p.toggle(privacy.app_name(app_id), getter=lambda a=allowed: a,
                     setter=lambda on, a=app_id: privacy.set_app_permission(feature, a, on))
    else:
        p.text(_("No apps have asked for access yet."))
    return p


def page_privacy_location(win):
    return privacy_page(win, "location", _("Location"), _("Allow apps to access your location"), "privacy.location",
                        _("Applies to apps that ask through the location portal (for example Flatpak apps)."),
                        _("Choose which apps can access your precise location"))


def page_privacy_camera(win):
    return privacy_page(win, "camera", _("Camera"), _("Allow apps to access your camera"), "privacy.camera",
                        _("Applies to apps that ask through the camera portal (for example Flatpak apps). "
                          "Other apps can open the camera directly."),
                        _("Choose which apps can access your camera"))


def page_privacy_microphone(win):
    p = Page(_("Microphone"))
    s = get_settings()

    def set_mic(on):
        s.set("privacy.microphone", on)
        privacy.set_microphone(on)

    p.toggle(_("Allow apps to access your microphone"), getter=lambda: s["privacy.microphone"], setter=set_mic)
    p.text(_("Linux has no per-app microphone permission. Turning access off mutes the microphone for all apps."))
    return p


PAGE_BUILDERS = {
    "multitasking": page_multitasking, "tablet": page_tablet, "themes": page_themes, "fonts": page_fonts,
    "game-bar": page_game_bar, "captures": page_captures, "game-mode": page_game_mode,
    "ease-magnifier": page_ease_magnifier, "ease-contrast": page_ease_contrast,
    "ease-narrator": page_ease_narrator, "ease-keyboard": page_ease_keyboard,
    "privacy-location": page_privacy_location, "privacy-camera": page_privacy_camera,
    "privacy-microphone": page_privacy_microphone,
}
