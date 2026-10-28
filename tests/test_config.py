import json

from tenwin import config


def test_defaults_when_file_missing(tmp_path):
    data = config.load_file(tmp_path / "missing.json")
    assert data == config.DEFAULTS


def test_save_writes_only_changed_values(tmp_path):
    path = tmp_path / "settings.json"
    data = dict(config.DEFAULTS)
    data["appearance.app_mode"] = "dark"
    config.save_file(data, path)
    assert json.loads(path.read_text()) == {"appearance.app_mode": "dark"}
    assert config.load_file(path)["appearance.app_mode"] == "dark"


def test_coerce_rejects_wrong_types(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "taskbar.small_icons": 1,
        "power.lock_after_min": "15",
        "input.pointer_speed": "fast",
        "taskbar.pinned": "firefox.desktop",
        "display.outputs": [],
        "appearance.accent": 42,
    }))
    data = config.load_file(path)
    assert data["taskbar.small_icons"] is True
    assert data["power.lock_after_min"] == 15
    assert data["input.pointer_speed"] == config.DEFAULTS["input.pointer_speed"]
    assert data["taskbar.pinned"] == config.DEFAULTS["taskbar.pinned"]
    assert data["display.outputs"] == {}
    assert data["appearance.accent"] == config.DEFAULTS["appearance.accent"]


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    assert config.load_file(path) == config.DEFAULTS


def test_settings_update_reports_changes(tmp_path):
    settings = config._SettingsBase(tmp_path / "s.json")
    seen = []
    settings._emit = seen.append
    assert settings.update({"taskbar.position": "top"}) == {"taskbar.position"}
    assert settings.update({"taskbar.position": "top"}) == set()
    assert seen == [{"taskbar.position"}]


def test_accent_palette_has_48_colors():
    assert len(config.ACCENT_COLORS) == 48
    assert len(set(config.ACCENT_COLORS)) == 48


def test_bool_strings_are_parsed(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"power.lock_on_suspend": "false", "notifications.enabled": "0",
                                "desktop.show_this_pc": "yes", "taskbar.small_icons": "maybe"}))
    data = config.load_file(path)
    assert data["power.lock_on_suspend"] is False
    assert data["notifications.enabled"] is False
    assert data["desktop.show_this_pc"] is True
    assert data["taskbar.small_icons"] is config.DEFAULTS["taskbar.small_icons"]


def test_state_modify_does_not_lose_other_writers(tmp_path):
    path = tmp_path / "state.json"
    a = config.State(path)
    b = config.State(path)  # e.g. another process with an old snapshot
    a.modify("usage", lambda u: {**(u or {}), "x.desktop": 1})
    b.modify("run_history", lambda h: ["firefox"])
    fresh = config.State(path)
    assert fresh.get("usage") == {"x.desktop": 1}
    assert fresh.get("run_history") == ["firefox"]
