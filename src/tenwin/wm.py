"""Window placement actions that labwc 0.7 only offers to key bindings.

labwc has no IPC, but it runs key bindings for virtual keyboards. Tenwin
binds hidden key combinations (three or four modifiers plus rare XF86 keys) to
SnapToRegion/SnapToEdge and triggers them with the tenwin-vkbd helper after
focusing the target window. See docs/adr/0002-fensterverwaltung.md.

This module only holds the tables; the shell drives them (tenwin.shell.snap).
"""

# Keysyms that exist on every evdev keymap but are (almost) never on real keyboards.
FKEYS = ["XF86Launch%s" % c for c in "123456789AB"] + ["XF86Tools"]
MODIFIERS = ["C-A-S-", "C-A-S-W-", "C-A-W-", "C-S-W-", "A-S-W-"]

# Regions that are always defined: they also serve interactive moves with a
# modifier held (labwc picks the region whose centre is closest to the
# pointer, so the corners give quarters and the middle of a side a half).
DRAG_REGIONS = [
    ("tw-tl", 0, 0, 50, 50), ("tw-tr", 50, 0, 50, 50),
    ("tw-bl", 0, 50, 50, 50), ("tw-br", 50, 50, 50, 50),
    ("tw-left", 0, 0, 50, 100), ("tw-right", 50, 0, 50, 100),
]

# Arrangements (cascade, stacked, side by side) use hidden "slot" bindings
# with MoveTo/ResizeTo in pixels, rewritten for each arrangement. (Regions
# can't be used: labwc puts windows back to their natural geometry when a
# region they are snapped to disappears from the configuration.)
SLOTS = 10
GRID_LIMIT = 9
# Server-side decoration of the Tenwin labwc theme (border.width, titlebar.height).
BORDER = 1
TITLEBAR = 30


def _split(count):
    """Integer percentages that add up to 100: 3 -> [(0, 33), (33, 34), (67, 33)]."""
    bounds = [round(i * 100 / count) for i in range(count + 1)]
    return [(bounds[i], bounds[i + 1] - bounds[i]) for i in range(count)]


def grid_shape(count, columns_first=True):
    """(columns, rows) used to arrange ``count`` windows."""
    if count <= 4:
        return (count, 1) if columns_first else (1, count)
    if count <= 6:
        return (3, 2) if columns_first else (2, 3)
    return (3, 3)


def layout_cells(kind, count):
    """Cells in percent (x, y, w, h) for "side" (side by side), "stack" or "cascade"."""
    count = max(1, count)
    if kind == "cascade":
        return [(3 * i, 4 * i, 60, 60) for i in range(min(count, SLOTS))]
    count = min(count, GRID_LIMIT)
    columns, rows = grid_shape(count, columns_first=(kind == "side"))
    cells = [(x, y, w, h) for (y, h) in _split(rows) for (x, w) in _split(columns)]
    return cells[:count]


def slot_boxes(kind, count, area):
    """Window content boxes in pixels for an arrangement inside ``area`` (x, y, w, h)."""
    ax, ay, aw, ah = area
    boxes = []
    for x, y, w, h in layout_cells(kind, count):
        fx, fy = ax + aw * x // 100, ay + ah * y // 100
        fw, fh = aw * w // 100, ah * h // 100
        boxes.append((fx + BORDER, fy + TITLEBAR + BORDER,
                      max(100, fw - 2 * BORDER), max(60, fh - TITLEBAR - 2 * BORDER)))
    return boxes


def slot_name(index):
    return "slot-%d" % index


def _actions():
    """Every hidden action name, in a fixed order (the order decides the key)."""
    names = ["edge-left", "edge-right", "restore"]
    names += [r[0] for r in DRAG_REGIONS]
    names += [slot_name(i) for i in range(SLOTS)]
    return names


ACTIONS = _actions()
# MoveRelative 0 0 un-maximises and un-snaps a window (back to its own size).
UNSNAP = '<action name="MoveRelative" x="0" y="0" />'


def action_xml(name, boxes=()):
    if name.startswith("edge-"):
        return '<action name="SnapToEdge" direction="%s" />' % name[5:]
    if name == "restore":
        return UNSNAP
    if name.startswith("slot-"):
        index = int(name[5:])
        if index >= len(boxes):
            return '<action name="None" />'
        x, y, w, h = boxes[index]
        return (UNSNAP + '<action name="MoveTo" x="%d" y="%d" />'
                '<action name="ResizeTo" width="%d" height="%d" />' % (x, y, w, h))
    return '<action name="SnapToRegion" region="%s" />' % name


def key_for_index(index):
    return MODIFIERS[index // len(FKEYS)] + FKEYS[index % len(FKEYS)]


def hidden_keybinds(boxes=()):
    """(key, action XML, action name) for rc.xml; ``boxes`` fill the arrangement slots."""
    if len(ACTIONS) > len(FKEYS) * len(MODIFIERS):
        raise ValueError("not enough hidden key combinations")
    return [(key_for_index(i), action_xml(name, boxes), name) for i, name in enumerate(ACTIONS)]


_KEYS = {name: key_for_index(i) for i, name in enumerate(ACTIONS)}


def key_for(action):
    """Hidden key combination for an action name such as "tw-tl" or "edge-left"."""
    return _KEYS[action]


def regions_xml():
    lines = ["  <regions>"]
    for name, x, y, w, h in DRAG_REGIONS:
        lines.append('    <region name="%s" x="%d%%" y="%d%%" width="%d%%" height="%d%%" />'
                     % (name, x, y, w, h))
    lines.append("  </regions>")
    return lines


# -- snap state machine (Win+arrow keys like Windows 10) -----------------------

# state: None (floating), "max", "left", "right", "tl", "tr", "bl", "br"
_UP = {"left": "tw-tl", "right": "tw-tr", "bl": "edge-left", "br": "edge-right"}
_DOWN = {"left": "tw-bl", "right": "tw-br", "tl": "edge-left", "tr": "edge-right"}
STATE_OF = {"tw-tl": "tl", "tw-tr": "tr", "tw-bl": "bl", "tw-br": "br",
            "edge-left": "left", "edge-right": "right", "tw-left": "left", "tw-right": "right"}


def next_step(state, direction):
    """What Win+Up/Down does for a window in ``state``. (Win+Left/Right are
    plain labwc SnapToEdge bindings that report back with "snapped".)

    Returns an action name (hidden key binding), "maximize", "unmaximize",
    "minimize" or None.
    """
    if direction == "up":
        if state in _UP:
            return _UP[state]
        return None if state == "max" else "maximize"
    if direction == "down":
        if state in _DOWN:
            return _DOWN[state]
        if state == "max":
            return "unmaximize"
        return "minimize"
    return None
