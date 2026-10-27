import xml.etree.ElementTree as ET

from tenwin import config, session


def settings(**overrides):
    data = dict(config.DEFAULTS)
    data.update(overrides)
    return data


def test_rc_xml_is_well_formed_and_binds_win_shortcuts():
    root = ET.fromstring(session.rc_xml(settings()))
    keys = {kb.get("key"): kb for kb in root.iter("keybind")}
    for key in ("Super_L", "W-e", "W-r", "W-i", "W-a", "W-d", "W-l", "W-Tab", "W-x", "A-Tab",
                "W-Left", "W-Right", "C-W-Left", "C-W-Right", "A-F4"):
        assert key in keys, key
    command = keys["W-e"].find("action").get("command")
    assert command.endswith("tenwin-ctl explorer")
    # labwc-internal Win shortcuts must cancel a pending Start menu first.
    actions = keys["W-Left"].findall("action")
    assert actions[0].get("command", "").endswith("tenwin-ctl cancel")
    assert actions[1].get("name") == "SnapToEdge"


def test_rc_xml_theme_and_desktops():
    root = ET.fromstring(session.rc_xml(settings(**{"appearance.app_mode": "dark", "desktops.count": 3})))
    assert root.find("theme/name").text == "Tenwin-Dark"
    assert len(root.findall("desktops/names/name")) == 3


def test_rc_xml_escapes_values():
    xml = session.rc_xml(settings())
    ET.fromstring(xml)  # quoteattr/escape keep it valid
    assert "<windowRules>" in xml


def test_environment_keyboard_layouts():
    env = session.environment(settings(**{"input.keyboard_layouts": "de,us"}))
    assert "XKB_DEFAULT_LAYOUT=de,us\n" in env
    assert "XKB_DEFAULT_OPTIONS=grp:win_space_toggle\n" in env
    single = session.environment(settings(**{"input.keyboard_layouts": "de"}))
    assert "XKB_DEFAULT_OPTIONS" not in single


def test_menu_xml_has_client_menu():
    root = ET.fromstring(session.menu_xml())
    menu = root.find("menu[@id='client-menu']")
    assert menu is not None
    assert any(item.find("action").get("name") == "Close" for item in menu.findall("item"))


def test_write_labwc_config(tmp_path, monkeypatch):
    monkeypatch.setattr(session.paths, "LABWC_CONFIG_DIR", tmp_path / "labwc")
    target = session.write_labwc_config(settings())
    for name in ("rc.xml", "menu.xml", "environment", "autostart", "themerc-override"):
        assert (target / name).exists(), name
    assert (target / "autostart").stat().st_mode & 0o100
    assert "window.active.border.color: #0078D7" in (target / "themerc-override").read_text()
