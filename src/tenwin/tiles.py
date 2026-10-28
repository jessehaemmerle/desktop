"""Start menu tiles: groups ("categories"), placement and pinning.

A tile is ``{"app": desktop_id, "size": …}`` or ``{"path": "/folder/or/file", "size": …}``.
Groups are ``{"name": str, "tiles": [tile, …]}`` and are stored in the
``start.tiles`` setting (``None`` means the default layout). The functions here
work on plain lists so the shell, the Explorer and the desktop share them.
"""

import copy
import os

from tenwin.config import get_settings
from tenwin.i18n import N_, _

CELL = 48
GAP = 4
COLUMNS = 6  # small-tile columns per group (= 3 medium tiles)
GROUP_WIDTH = COLUMNS * CELL + (COLUMNS - 1) * GAP
SIZES = {"small": (1, 1), "medium": (2, 2), "wide": (4, 2), "large": (4, 4)}

DEFAULT_GROUPS = [
    (N_("Productivity"), [
        ("org.gnome.Calendar.desktop", "medium"),
        ("thunderbird.desktop", "wide"), ("thunderbird_thunderbird.desktop", "wide"),
        ("org.gnome.Evolution.desktop", "wide"),
        ("firefox_firefox.desktop", "medium"), ("firefox.desktop", "medium"),
        ("libreoffice-writer.desktop", "small"), ("libreoffice-calc.desktop", "small"),
        ("libreoffice-impress.desktop", "small"), ("org.tenwin.Explorer.desktop", "small"),
        ("org.gnome.TextEditor.desktop", "medium"), ("org.gnome.gedit.desktop", "medium"),
    ]),
    (N_("Explore"), [
        ("snap-store_snap-store.desktop", "wide"), ("org.gnome.Software.desktop", "wide"),
        ("org.gnome.Weather.desktop", "medium"), ("org.gnome.Calculator.desktop", "medium"),
        ("org.gnome.Loupe.desktop", "medium"), ("org.gnome.eog.desktop", "medium"),
        ("org.gnome.Totem.desktop", "medium"), ("rhythmbox.desktop", "medium"),
        ("org.tenwin.Settings.desktop", "medium"), ("org.gnome.Terminal.desktop", "small"),
        ("gnome-system-monitor.desktop", "small"), ("org.gnome.SystemMonitor.desktop", "small"),
    ]),
]

# freedesktop.org main categories -> Start group names (first match wins)
CATEGORY_GROUPS = [
    ("Office", N_("Office")),
    ("Network", N_("Internet")),
    ("AudioVideo", N_("Media")), ("Audio", N_("Media")), ("Video", N_("Media")),
    ("Graphics", N_("Graphics")),
    ("Development", N_("Development")),
    ("Game", N_("Games")),
    ("Education", N_("Education")), ("Science", N_("Education")),
    ("Settings", N_("System")), ("System", N_("System")),
    ("Utility", N_("Accessories")),
]
OTHER_GROUP = N_("Other")
FOLDERS_GROUP = N_("Folders and files")


# -- keys -------------------------------------------------------------------

def tile_key(tile):
    if tile.get("app"):
        return "app:" + tile["app"]
    if tile.get("path"):
        return "path:" + tile["path"]
    return ""


def app_key(desktop_id):
    return "app:" + desktop_id


def path_key(path):
    return "path:" + os.path.abspath(path)


def make_tile(key, size="medium"):
    kind, _, value = key.partition(":")
    return {"app": value, "size": size} if kind == "app" else {"path": value, "size": size}


# -- default layout -----------------------------------------------------------

def default_tiles(apps):
    groups = []
    for name, candidates in DEFAULT_GROUPS:
        tiles, seen = [], set()
        for desktop_id, size in candidates:
            info = apps.get(desktop_id)
            if info is None or not info.should_show():
                continue
            # Skip alternatives of the same program (snap vs. deb).
            base = desktop_id.split("_")[0].split(".desktop")[0].rsplit(".", 1)[-1].lower()
            if base in seen:
                continue
            seen.add(base)
            tiles.append({"app": info.get_id(), "size": size})
            if len(tiles) >= 6:
                break
        if tiles:
            groups.append({"name": _(name), "tiles": tiles})
    return groups


def load(apps=None):
    """Current groups (a deep copy that may be modified and passed to save)."""
    groups = get_settings()["start.tiles"]
    if groups is None:
        if apps is None:
            from tenwin.apps import get_registry
            apps = get_registry()
        groups = default_tiles(apps)
    return copy.deepcopy(sanitize(groups))


def save(groups):
    get_settings().set("start.tiles", sanitize(groups))


def sanitize(groups):
    """Drop malformed entries (the settings file is user-editable)."""
    result = []
    for group in groups if isinstance(groups, list) else []:
        if not isinstance(group, dict):
            continue
        tiles = [t for t in group.get("tiles", []) if isinstance(t, dict) and tile_key(t)]
        for tile in tiles:
            if tile.get("size") not in SIZES:
                tile["size"] = "medium"
        result.append({"name": str(group.get("name") or ""), "tiles": tiles})
    return result


# -- layout ---------------------------------------------------------------------

def layout_tiles(tiles, columns=COLUMNS):
    """First-fit placement. Returns [(tile, col, row, w, h)] and the row count."""
    occupied = set()
    placed = []
    rows = 0
    for tile in tiles:
        w, h = SIZES.get(tile.get("size"), SIZES["medium"])
        w = min(w, columns)
        row = 0
        while True:
            spot = None
            for col in range(0, columns - w + 1):
                cells = {(col + dx, row + dy) for dx in range(w) for dy in range(h)}
                if not cells & occupied:
                    spot = col
                    break
            if spot is not None:
                occupied |= {(spot + dx, row + dy) for dx in range(w) for dy in range(h)}
                placed.append((tile, spot, row, w, h))
                rows = max(rows, row + h)
                break
            row += 1
    return placed, rows


def group_columns_for_width(tile_area_width, spacing=24):
    """How many tile group columns fit into the given width (at least one)."""
    return max(1, (tile_area_width + spacing) // (GROUP_WIDTH + spacing))


# -- editing --------------------------------------------------------------------

def find(groups, key):
    """(group index, tile index) of ``key`` or (None, None)."""
    for gi, group in enumerate(groups):
        for ti, tile in enumerate(group["tiles"]):
            if tile_key(tile) == key:
                return gi, ti
    return None, None


def is_pinned(groups, key):
    return find(groups, key)[0] is not None


def remove(groups, key):
    """Remove a tile; empty unnamed groups disappear. Returns the removed tile."""
    gi, ti = find(groups, key)
    if gi is None:
        return None
    tile = groups[gi]["tiles"].pop(ti)
    if not groups[gi]["tiles"] and not groups[gi]["name"]:
        groups.pop(gi)
    return tile


def pin(groups, key, group=None, new_group_name=None, size="medium"):
    """Pin ``key`` into an existing group index, a new named group, or the last group."""
    target = groups[group] if group is not None and 0 <= group < len(groups) else None
    tile = remove(groups, key) or make_tile(key, size)
    if new_group_name is not None:
        groups.append({"name": new_group_name, "tiles": [tile]})
        return len(groups) - 1
    if target is None or not any(g is target for g in groups):
        # Removing the tile may have dropped its (now empty) group.
        if not groups:
            groups.append({"name": "", "tiles": []})
        target = groups[-1] if target is None else target
        if not any(g is target for g in groups):
            groups.append(target)
    target["tiles"].append(tile)
    return next(i for i, g in enumerate(groups) if g is target)


def move(groups, key, group, before_key=None):
    """Move a tile (or pin a new app) into ``group`` before ``before_key``."""
    target_group = groups[group] if 0 <= group < len(groups) else None
    tile = remove(groups, key) or make_tile(key)
    if target_group is None:
        target_group = {"name": "", "tiles": []}
    if not any(g is target_group for g in groups):
        groups.append(target_group)
    target = target_group["tiles"]
    index = len(target)
    if before_key:
        for i, other in enumerate(target):
            if tile_key(other) == before_key:
                index = i
                break
    target.insert(index, tile)


def resize(groups, key, size):
    gi, ti = find(groups, key)
    if gi is not None and size in SIZES:
        groups[gi]["tiles"][ti]["size"] = size


def rename_group(groups, index, name):
    if 0 <= index < len(groups):
        groups[index]["name"] = name.strip()


def move_group(groups, index, delta):
    target = index + delta
    if 0 <= index < len(groups) and 0 <= target < len(groups):
        groups[index], groups[target] = groups[target], groups[index]


def remove_group(groups, index):
    if 0 <= index < len(groups):
        groups.pop(index)


# -- categories -----------------------------------------------------------------

def category_name(info):
    """Translated Start group name for an app, from its desktop categories."""
    categories = set(filter(None, (info.get_categories() or "").split(";"))) if info is not None else set()
    for category, name in CATEGORY_GROUPS:
        if category in categories:
            return _(name)
    return _(OTHER_GROUP)


def suggested_group(groups, key, apps):
    """Name of the category group a new tile would fit into."""
    kind, _sep, value = key.partition(":")
    if kind == "path":
        return _(FOLDERS_GROUP)
    return category_name(apps.get(value) if apps is not None else None)


def group_by_category(groups, apps):
    """Rebuild the layout with one group per category (tile sizes are kept).

    Groups are sorted by name; "Other" and "Folders and files" come last.
    """
    tiles = [tile for group in groups for tile in group["tiles"]]
    order = []
    buckets = {}
    for tile in tiles:
        if tile.get("path"):
            name = _(FOLDERS_GROUP)
        else:
            name = category_name(apps.get(tile["app"]))
        if name not in buckets:
            buckets[name] = []
            order.append(name)
        buckets[name].append(tile)
    other = _(OTHER_GROUP)
    order.sort(key=lambda n: (n == other, n == _(FOLDERS_GROUP), n.casefold()))
    return [{"name": name, "tiles": buckets[name]} for name in order]
