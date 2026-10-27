"""Pure logic of several UI modules (no display needed)."""

import os

from tenwin import apps, search_providers, settings_index, theme
from tenwin.explorer import model
from tenwin.shell.startmenu import COLUMNS, layout_tiles


class FakeApp:
    def __init__(self, name, generic="", keywords=(), executable=""):
        self._name, self._generic, self._kw, self._exe = name, generic, list(keywords), executable

    def get_display_name(self):
        return self._name

    def get_generic_name(self):
        return self._generic

    def get_keywords(self):
        return self._kw

    def get_executable(self):
        return self._exe


def test_first_letter():
    assert apps.first_letter("Firefox") == "F"
    assert apps.first_letter("Ärzte") == "A"
    assert apps.first_letter("7-Zip") == "#"
    assert apps.first_letter("") == "#"


def test_search_apps_ranking():
    candidates = [FakeApp("LibreOffice Writer", "Word Processor"), FakeApp("Writer Tool"),
                  FakeApp("Terminal", keywords=["shell"]), FakeApp("Files", executable="/usr/bin/nautilus")]
    names = [a.get_display_name() for a in search_providers.search_apps(candidates, "writ")]
    assert names == ["Writer Tool", "LibreOffice Writer"]
    assert [a.get_display_name() for a in search_providers.search_apps(candidates, "shell")] == ["Terminal"]
    assert [a.get_display_name() for a in search_providers.search_apps(candidates, "nauti")] == ["Files"]


def test_file_index(tmp_path):
    (tmp_path / "Projekte").mkdir()
    (tmp_path / "Projekte" / "Bericht.odt").write_text("x")
    (tmp_path / ".versteckt").mkdir()
    (tmp_path / ".versteckt" / "Bericht-geheim.txt").write_text("x")
    index = search_providers.FileIndex(str(tmp_path))
    index._build()
    found = [os.path.basename(p) for p, _d in index.search("bericht")]
    assert found == ["Bericht.odt"]
    assert index.search("projekte", dirs=True)[0][1] is True


def test_layout_tiles_first_fit():
    tiles = [{"app": "a", "size": "wide"}, {"app": "b", "size": "medium"},
             {"app": "c", "size": "small"}, {"app": "d", "size": "small"}, {"app": "e", "size": "large"}]
    placed, rows = layout_tiles(tiles)
    spots = {t["app"]: (col, row) for t, col, row, _w, _h in placed}
    assert spots["a"] == (0, 0)
    assert spots["b"] == (4, 0)
    assert spots["c"] == (0, 2) and spots["d"] == (1, 2)
    # Large tiles never overlap and stay within the 6-column grid.
    cells = set()
    for _t, col, row, w, h in placed:
        assert col + w <= COLUMNS
        for dx in range(w):
            for dy in range(h):
                assert (col + dx, row + dy) not in cells
                cells.add((col + dx, row + dy))
    assert rows >= 4


def test_settings_search():
    results = settings_index.search("accent")
    assert results and results[0][0] == "colors"
    assert settings_index.search("") == []
    ids = {p[0] for p in settings_index.PAGES}
    from tenwin.settings.pages import PAGE_BUILDERS
    assert ids == set(PAGE_BUILDERS), "every page in the index needs a builder"


def test_size_text_and_natural_sort():
    assert model.size_text(0, False) == "0 KB"
    assert model.size_text(1, False) == "1 KB"
    assert model.size_text(1025, False) == "2 KB"
    assert model.size_text(5000, True) == ""
    names = ["Bild 10", "Bild 2", "bild 1"]
    assert sorted(names, key=lambda n: model._natural(n.casefold())) == ["bild 1", "Bild 2", "Bild 10"]


def test_palette_contrast():
    for accent in ("#FFB900", "#0078D7", "#000000", "#FFFFFF"):
        fg = "#000000" if theme.luminance(accent) > 0.4 else "#ffffff"
        assert fg in ("#000000", "#ffffff")
    assert theme.shade("#0078D7", 0.1) != "#0078d7"
    assert theme.rgba("#ff0000", 0.5) == "rgba(255,0,0,0.500)"
