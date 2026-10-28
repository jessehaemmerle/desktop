"""Start tile groups and the accent colour from the background."""

import colorsys

from tenwin import accent, tiles
from tenwin.theme import hex_to_rgb


class FakeInfo:
    def __init__(self, categories):
        self._categories = categories

    def get_categories(self):
        return self._categories


APPS = {
    "writer.desktop": FakeInfo("Office;WordProcessor;"),
    "firefox.desktop": FakeInfo("Network;WebBrowser;"),
    "gimp.desktop": FakeInfo("Graphics;2DGraphics;"),
    "calc.desktop": FakeInfo("Office;Spreadsheet;"),
    "odd.desktop": FakeInfo(""),
}


def groups_fixture():
    return [
        {"name": "A", "tiles": [{"app": "writer.desktop", "size": "medium"},
                                {"app": "firefox.desktop", "size": "wide"}]},
        {"name": "", "tiles": [{"app": "gimp.desktop", "size": "small"}]},
    ]


def names(groups):
    return [[tiles.tile_key(t) for t in g["tiles"]] for g in groups]


def test_pin_into_group_and_new_group():
    groups = groups_fixture()
    tiles.pin(groups, "app:calc.desktop", group=0)
    assert names(groups)[0][-1] == "app:calc.desktop"
    index = tiles.pin(groups, "path:/home/u/Docs", new_group_name="Folders")
    assert groups[index] == {"name": "Folders", "tiles": [{"path": "/home/u/Docs", "size": "medium"}]}
    # Pinning again moves the tile instead of duplicating it.
    tiles.pin(groups, "app:calc.desktop", group=index)
    assert sum(k == "app:calc.desktop" for g in names(groups) for k in g) == 1


def test_pin_keeps_target_when_source_group_disappears():
    groups = groups_fixture()
    # gimp is alone in an unnamed group that vanishes when it is removed.
    groups.append({"name": "C", "tiles": []})
    index = tiles.pin(groups, "app:gimp.desktop", group=2)
    assert groups[index]["name"] == "C"
    assert names(groups)[index] == ["app:gimp.desktop"]
    assert len(groups) == 2


def test_move_before_and_resize():
    groups = groups_fixture()
    tiles.move(groups, "app:gimp.desktop", 0, before_key="app:firefox.desktop")
    assert names(groups) == [["app:writer.desktop", "app:gimp.desktop", "app:firefox.desktop"]]
    tiles.resize(groups, "app:gimp.desktop", "large")
    assert groups[0]["tiles"][1]["size"] == "large"
    tiles.move(groups, "app:writer.desktop", 5)  # past the end -> new group
    assert names(groups)[-1] == ["app:writer.desktop"]


def test_group_editing():
    groups = groups_fixture()
    tiles.rename_group(groups, 1, "  Bilder ")
    assert groups[1]["name"] == "Bilder"
    tiles.move_group(groups, 1, -1)
    assert groups[0]["name"] == "Bilder"
    tiles.remove_group(groups, 0)
    assert [g["name"] for g in groups] == ["A"]


def test_group_by_category():
    groups = groups_fixture()
    groups[0]["tiles"].append({"path": "/tmp", "size": "medium"})
    groups[1]["tiles"].append({"app": "calc.desktop", "size": "small"})
    groups[1]["tiles"].append({"app": "odd.desktop", "size": "small"})
    result = tiles.group_by_category(groups, APPS)
    assert [g["name"] for g in result] == ["Graphics", "Internet", "Office", "Folders and files", "Other"]
    office = result[2]["tiles"]
    assert [t["app"] for t in office] == ["writer.desktop", "calc.desktop"]
    assert office[1]["size"] == "small"
    assert tiles.suggested_group(groups, "app:gimp.desktop", APPS) == "Graphics"
    assert tiles.suggested_group(groups, "path:/x", APPS) == "Folders and files"


def test_sanitize_and_columns():
    dirty = [{"name": None, "tiles": [{"app": "a", "size": "huge"}, "junk", {"size": "small"}]}, 3]
    assert tiles.sanitize(dirty) == [{"name": "", "tiles": [{"app": "a", "size": "medium"}]}]
    assert tiles.group_columns_for_width(0) == 1
    assert tiles.group_columns_for_width(tiles.GROUP_WIDTH) == 1
    assert tiles.group_columns_for_width(3 * tiles.GROUP_WIDTH + 2 * 24) == 3


def test_dominant_color_prefers_vivid_area():
    grey = [(0.5, 0.5, 0.52)] * 900
    orange = [(0.95, 0.45, 0.05)] * 100
    r, g, b = accent.dominant_color(grey + orange)
    assert r > 0.8 and b < 0.2
    # A picture without any colour gives a grey.
    r, g, b = accent.dominant_color(grey)
    assert abs(r - g) < 0.05


def test_usable_accent_is_readable():
    for rgb in ((1.0, 1.0, 0.8), (0.02, 0.02, 0.1), (0.9, 0.1, 0.1)):
        h, l, s = colorsys.rgb_to_hls(*hex_to_rgb(accent.usable(rgb)))
        assert 0.25 <= l <= 0.47


class FakeSettings(dict):
    pass


def test_for_settings_modes():
    s = FakeSettings({"appearance.accent_mode": "manual", "background.type": "color",
                      "background.color": "#FF8800", "background.picture": ""})
    assert accent.for_settings(s) is None
    s["appearance.accent_mode"] = "dark"
    assert accent.for_settings(s) == accent.DARK_ACCENT
    s["appearance.accent_mode"] = "wallpaper"
    h, _l, _s = colorsys.rgb_to_hls(*hex_to_rgb(accent.for_settings(s)))
    assert abs(h * 360 - 32) < 6  # still orange


def test_from_picture(tmp_path):
    from gi.repository import GdkPixbuf
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 32, 32)
    pixbuf.fill(0x1060D0FF)  # blue
    path = str(tmp_path / "blue.png")
    pixbuf.savev(path, "png", [], [])
    r, g, b = hex_to_rgb(accent.from_picture(path))
    assert b > r and b > g
    assert accent.from_picture(str(tmp_path / "missing.png")) is None
