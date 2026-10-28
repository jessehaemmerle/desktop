"""'Pin to Start ▸' menus shared by the Start menu, the Explorer and the desktop."""

from gi.repository import Gtk

from tenwin import tiles
from tenwin.gtkutil import add_class, menu_item
from tenwin.i18n import _


def ask_group_name(suggestion="", parent=None):
    """Ask for the name of a new tile group. Returns the name or None."""
    dialog = Gtk.Dialog(title=_("New group"), transient_for=parent, modal=True)
    dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
    dialog.add_button(_("OK"), Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.OK)
    area = dialog.get_content_area()
    area.set_spacing(8)
    area.set_margin_start(16)
    area.set_margin_end(16)
    area.set_margin_top(12)
    area.pack_start(Gtk.Label(label=_("Name the group (for example \"Office\" or \"Games\"):"), xalign=0),
                    False, False, 0)
    entry = Gtk.Entry(activates_default=True, text=suggestion)
    area.pack_start(entry, False, False, 0)
    dialog.show_all()
    response = dialog.run()
    name = entry.get_text().strip()
    dialog.destroy()
    return name if response == Gtk.ResponseType.OK else None


def pin(keys, group=None, new_group_name=None, apps=None):
    groups = tiles.load(apps)
    for key in keys:
        if new_group_name is not None:
            group = tiles.pin(groups, key, new_group_name=new_group_name)
            new_group_name = None  # the other keys join the new group
        else:
            group = tiles.pin(groups, key, group=group)
    tiles.save(groups)


def unpin(keys, apps=None):
    groups = tiles.load(apps)
    for key in keys:
        tiles.remove(groups, key)
    tiles.save(groups)


def pin_submenu(keys, label=None, apps=None, parent=None):
    """Menu item with the existing groups (categories) and new-group entries."""
    item = Gtk.MenuItem(label=label or _("Pin to Start"))
    sub = add_class(Gtk.Menu(), "tw-menu")
    groups = tiles.load(apps)
    current = {tiles.find_any(groups, key)[0] for key in keys}
    for index, group in enumerate(groups):
        name = group["name"] or _("Unnamed group")
        mark = "✓  " if current == {index} else "     "
        sub.append(menu_item(mark + name, lambda i=index: pin(keys, group=i, apps=apps)))
    if groups:
        sub.append(Gtk.SeparatorMenuItem())
    suggestion = tiles.suggested_group(groups, keys[0], apps)
    if suggestion.casefold() not in {g["name"].casefold() for g in groups}:
        sub.append(menu_item(_("New group \"%s\"") % suggestion,
                             lambda: pin(keys, new_group_name=suggestion, apps=apps), "tenwin-new-folder"))

    def ask():
        name = ask_group_name(suggestion, parent)
        if name is not None:
            pin(keys, new_group_name=name, apps=apps)

    sub.append(menu_item(_("New group…"), ask, "tenwin-new-folder"))
    item.set_submenu(sub)
    return item


def path_items(paths, apps=None, parent=None):
    """Pin/unpin menu items for files and folders (Explorer, desktop)."""
    keys = [tiles.path_key(p) for p in paths]
    groups = tiles.load(apps)
    pinned = all(tiles.is_pinned(groups, key) for key in keys)
    items = [pin_submenu(keys, _("Move to group") if pinned else None, apps, parent)]
    if pinned:
        items.append(menu_item(_("Unpin from Start"), lambda: unpin(keys, apps), "tenwin-unpin"))
    return items
