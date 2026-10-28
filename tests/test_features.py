"""Window placement, Task Manager, touch keyboard, Explorer and integration helpers."""

import os

import pytest

from tenwin import apps, designs, fonts, integration, theme, tiles, wm
from tenwin.config import get_settings
from tenwin.explorer import network, panes
from tenwin.taskmgr import procstat


# -- window placement ---------------------------------------------------------------

def test_hidden_keys_are_unique_and_rare():
    keys = [k for k, _xml, _name in wm.hidden_keybinds()]
    assert len(keys) == len(set(keys)) == len(wm.ACTIONS)
    assert all(k.count("-") >= 3 for k in keys)  # at least three modifiers
    assert wm.key_for("tw-tl") in keys


def test_layout_cells_cover_the_area():
    for kind in ("side", "stack"):
        for count in range(1, 10):
            cells = wm.layout_cells(kind, count)
            assert len(cells) == count
            area = sum(w * h for _x, _y, w, h in cells)
            columns, rows = wm.grid_shape(count, kind == "side")
            assert area <= 100 * 100
            assert area >= 100 * 100 * count / (columns * rows) - 200
    assert wm.layout_cells("side", 3)[1] == (33, 0, 34, 100)
    assert len(wm.layout_cells("cascade", 20)) == wm.SLOTS


def test_slot_boxes_leave_room_for_decorations():
    (x, y, w, h), = wm.slot_boxes("side", 1, (0, 40, 1000, 700))
    assert (x, y) == (wm.BORDER, 40 + wm.TITLEBAR + wm.BORDER)
    assert w == 1000 - 2 * wm.BORDER and h == 700 - wm.TITLEBAR - 2 * wm.BORDER
    xml = wm.action_xml("slot-0", [(1, 2, 3, 4)])
    assert "MoveRelative" in xml and 'x="1"' in xml and 'height="4"' in xml
    assert wm.action_xml("slot-5", []) == '<action name="None" />'


def test_win_up_down_state_machine():
    assert wm.next_step(None, "up") == "maximize"
    assert wm.next_step("left", "up") == "tw-tl"
    assert wm.next_step("tl", "down") == "edge-left"
    assert wm.next_step("br", "up") == "edge-right"
    assert wm.next_step("max", "down") == "unmaximize"
    assert wm.next_step(None, "down") == "minimize"
    assert wm.next_step("max", "up") is None


def test_rc_xml_has_regions_and_hidden_bindings():
    from tenwin import session
    rc = session.rc_xml(get_settings(), [(10, 20, 300, 200)])
    assert '<region name="tw-tl"' in rc
    assert 'region="tw-br"' in rc
    assert '<action name="MoveTo" x="10" y="20" />' in rc
    assert "snapped left" in rc


# -- tiles --------------------------------------------------------------------------

def test_tile_folders():
    groups = [{"name": "A", "tiles": [{"app": "a.desktop", "size": "medium"},
                                      {"app": "b.desktop", "size": "medium"},
                                      {"app": "c.desktop", "size": "small"}]}]
    assert tiles.combine(groups, "app:b.desktop", "app:a.desktop")
    folder = groups[0]["tiles"][0]
    assert folder["folder"] and [t["app"] for t in folder["tiles"]] == ["a.desktop", "b.desktop"]
    assert tiles.is_pinned(groups, "app:b.desktop")
    assert tiles.combine(groups, "app:c.desktop", tiles.tile_key(folder))
    assert len(folder["tiles"]) == 3
    tiles.set_color(groups, "app:c.desktop", tiles.TILE_COLORS[2])
    assert tiles.get(groups, "app:c.desktop")["color"] == tiles.TILE_COLORS[2]
    # Taking tiles out until one is left dissolves the folder.
    tiles.remove(groups, "app:c.desktop")
    tiles.move(groups, "app:b.desktop", 0)
    assert groups[0]["tiles"][0] == {"app": "a.desktop", "size": "medium"}
    assert not tiles.combine(groups, "app:a.desktop", "app:a.desktop")


def test_sanitize_folders():
    dirty = [{"name": "", "tiles": [{"folder": "f1", "tiles": [{"app": "x"}]},
                                    {"folder": "f2", "tiles": [{"app": "y"}, {"folder": "f3", "tiles": []},
                                                               {"app": "z", "color": "red"}]}]}]
    clean = tiles.sanitize(dirty)
    assert clean[0]["tiles"][0] == {"app": "x", "size": "medium"}
    inner = clean[0]["tiles"][1]["tiles"]
    assert [t.get("app") for t in inner] == ["y", "z"] and "color" not in inner[1]


# -- Task Manager -------------------------------------------------------------------------

STAT = "1234 (Web Content (x)) S 1000 1234 1234 0 -1 4194560 100 0 0 0 250 50 0 0 20 0 7 0 5000 0 0"


def test_parse_proc_files():
    stat = procstat.parse_stat(STAT)
    assert stat["comm"] == "Web Content (x)" and stat["ppid"] == 1000 and stat["ticks"] == 300
    assert stat["threads"] == 7
    cpu = procstat.parse_cpu_times("cpu  100 0 50 800 50 0 0 0 0 0\ncpu0 50 0 25 400 25 0 0 0 0 0\n")
    assert cpu["cpu"] == (150, 1000)
    mem = procstat.parse_meminfo("MemTotal:       16000 kB\nMemAvailable:    8000 kB\n")
    assert mem["MemTotal"] == 16000 * 1024
    net = procstat.parse_net_dev("h1\nh2\n  lo: 1 0 0 0 0 0 0 0 2 0 0 0 0 0 0 0\n eth0: 100 0 0 0 0 0 0 0 200 0 0 0 0 0 0 0\n")
    assert net == {"eth0": (100, 200)}
    disks = procstat.parse_diskstats(" 8 0 sda 1 0 10 0 2 0 20 0 0 30 0\n 8 1 sda1 1 0 10 0 2 0 20 0 0 30 0\n"
                                     " 259 0 nvme0n1 1 0 4 0 1 0 8 0 0 5 0\n 7 0 loop0 1 0 4 0 0 0 0 0 0 0 0\n")
    assert set(disks) == {"sda", "nvme0n1"} and disks["sda"] == (10 * 512, 20 * 512, 30)
    assert procstat.parse_io("rchar: 5\nread_bytes: 100\nwrite_bytes: 50\n") == 150


def _proc(pid, ppid, comm, exe="", cmdline=""):
    p = procstat.Process()
    p.pid, p.ppid, p.comm, p.exe, p.cmdline, p.rss = pid, ppid, comm, exe, cmdline or comm, 1
    return p


def test_group_apps():
    procs = [_proc(10, 1, "firefox", "firefox"), _proc(11, 10, "Web Content"), _proc(12, 10, "Socket Process"),
             _proc(20, 1, "python3.12", "python3.12", "python3.12 -m tenwin.taskmgr"), _proc(30, 1, "bash")]
    apps_ = [("firefox.desktop", "Firefox", None, "firefox", "firefox"),
             ("org.tenwin.TaskManager.desktop", "Task Manager", None, "org.tenwin.TaskManager", "tenwin-taskmgr")]
    groups, background = procstat.group_apps(procs, apps_)
    assert [(k, sorted(p.pid for p in m)) for k, _n, _i, m in groups] == [
        ("firefox.desktop", [10, 11, 12]), ("org.tenwin.TaskManager.desktop", [20])]
    assert [p.pid for p in background] == [30]


def test_sampler_reads_this_machine():
    s = procstat.Sampler()
    s.sample()
    s.sample()
    assert s.processes and s.memory.get("MemTotal", 0) > 0
    assert any(p.pid == os.getpid() for p in s.processes)


# -- touch keyboard, Explorer, apps ---------------------------------------------------------

def test_touch_keyboard_tables():
    from tenwin.shell import osk
    for layout in ("de", "us"):
        codes = [k[1] for row in osk.LETTERS[layout] + osk.SYMBOLS[layout] for k in row]
        assert all(0 < c < 256 for c in codes)
    assert osk.tap_command(16, "altgr", "") == "tap 16 altgr\n"
    assert [k[0] for k in osk.LETTERS["de"][0]][5] == "z"  # QWERTZ


def test_unc_paths():
    assert network.unc_to_uri(r"\\nas\Daten\Fotos 2024") == "smb://nas/Daten/Fotos%202024"
    assert network.unc_to_uri("sftp://me@host/x") == "sftp://me@host/x"
    assert network.unc_to_uri("nas/share") == "smb://nas/share"
    assert network.is_remote("smb://nas/share") and not network.is_remote("file:///tmp")
    assert network.is_disc_image("/tmp/ubuntu.ISO")


def test_preview_text(tmp_path):
    text = tmp_path / "a.txt"
    text.write_text("eins\nzwei\n")
    assert panes.read_text(str(text)) == "eins\nzwei"
    binary = tmp_path / "b.bin"
    binary.write_bytes(b"\x00\x01")
    assert panes.read_text(str(binary)) is None
    assert panes.is_text("text/x-python") and panes.is_image("image/png")


def test_strip_field_codes():
    assert apps.strip_field_codes("steam %U --silent") == "steam --silent"
    assert apps.strip_field_codes("echo 100%%") == "echo 100%"


def test_magnifier_offset():
    from tenwin.shell.access import source_offset
    assert source_offset(0, 1000, 2) == 0
    assert source_offset(1000, 1000, 2) == 500
    assert source_offset(500, 1000, 4) == pytest.approx(375)


# -- Settings backends ---------------------------------------------------------------------

def test_themes_save_apply_delete():
    s = get_settings()
    s.update({"appearance.accent": "#E81123", "appearance.accent_mode": "manual"})
    assert designs.save_current("Rot")
    saved = [t for t in designs.saved() if t["name"] == "Rot"][0]
    s.set("appearance.accent", "#0078D7")
    assert not designs.is_current(saved)
    designs.apply(saved)
    assert s["appearance.accent"] == "#E81123" and designs.is_current(saved)
    designs.delete("Rot")
    assert not [t for t in designs.saved() if t["name"] == "Rot"]


def test_fonts_install_and_remove(tmp_path):
    font = tmp_path / "MyFont.ttf"
    font.write_bytes(b"\0" * 10)
    target = tmp_path / "fonts"
    installed, errors = fonts.install([str(font), str(tmp_path / "notes.txt")], str(target))
    assert installed == ["MyFont.ttf"] and errors == ["notes.txt"]
    assert fonts.user_fonts(str(target)) == ["MyFont.ttf"]
    assert fonts.remove("MyFont.ttf", str(target)) and fonts.user_fonts(str(target)) == []
    assert fonts.filter_families(["Selawik", "DejaVu Sans"], "deja") == ["DejaVu Sans"]


def test_contrast_palette_is_complete():
    s = get_settings()
    base = theme.palette(s)
    s.set("appearance.contrast", "contrast-white")
    try:
        contrast = theme.palette(s)
        assert set(base) == set(contrast)
        assert contrast["app_bg"] == "#ffffff" and contrast["accent"] == "#37006e"
        for name in ("shell", "settings", "explorer", "taskmgr"):
            assert "$" not in theme.render_css(name, s)
        from tenwin import session
        assert session.theme_name(s) == "Tenwin-Contrast-White"
    finally:
        s.set("appearance.contrast", "")


def test_privacy_values():
    from tenwin import privacy
    assert privacy.is_allowed("camera", ["yes"]) and not privacy.is_allowed("camera", ["no"])
    assert privacy.is_allowed("location", ["EXACT", "0"]) and not privacy.is_allowed("location", ["NONE", "0"])


# -- integration ------------------------------------------------------------------------------

def test_qt_scheme():
    pal = theme.palette(get_settings())
    scheme = integration.qt_scheme(pal)
    active = scheme.splitlines()[1].split("=", 1)[1].split(", ")
    assert len(active) == len(integration.QT_ROLES)
    assert all(len(c) == 9 and c.startswith("#ff") for c in active)
    assert integration._hex6("rgba(16, 32, 48, 0.5)") == "102030"


def test_mozilla_profiles_are_changed_and_restored(tmp_path, monkeypatch):
    root = tmp_path / ".mozilla" / "firefox"
    profile = root / "abc.default-release"
    profile.mkdir(parents=True)
    (root / "profiles.ini").write_text("[Profile0]\nName=default\nIsRelative=1\nPath=abc.default-release\n")
    (profile / "user.js").write_text('user_pref("a", 1);\n')
    monkeypatch.setattr(integration, "MOZILLA_ROOTS", [str(root)])
    s = get_settings()
    pal = theme.palette(s)
    s.set("integration.mozilla", True)
    try:
        integration.apply_mozilla(s, pal)
        chrome = (profile / "chrome" / "userChrome.css").read_text()
        assert chrome.startswith(integration.MARKER) and s["appearance.accent"] in chrome
        assert integration.USERJS_LINE in (profile / "user.js").read_text()
    finally:
        s.set("integration.mozilla", False)
    integration.apply_mozilla(s, pal)
    assert not (profile / "chrome" / "userChrome.css").exists()
    assert (profile / "user.js").read_text() == 'user_pref("a", 1);\n'


def test_foreign_userchrome_is_kept(tmp_path, monkeypatch):
    root = tmp_path / "tb"
    profile = root / "p"
    (profile / "chrome").mkdir(parents=True)
    (root / "profiles.ini").write_text("[Profile0]\nIsRelative=1\nPath=p\n")
    own = "/* my own style */\n"
    (profile / "chrome" / "userChrome.css").write_text(own)
    monkeypatch.setattr(integration, "MOZILLA_ROOTS", [str(root)])
    s = get_settings()
    s.set("integration.mozilla", True)
    try:
        integration.apply_mozilla(s, theme.palette(s))
    finally:
        s.set("integration.mozilla", False)
    integration.apply_mozilla(s, theme.palette(s))
    assert (profile / "chrome" / "userChrome.css").read_text() == own
