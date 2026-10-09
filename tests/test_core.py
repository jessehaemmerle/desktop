import json
import math
from datetime import datetime

import pytest

from prisma.core import appmatch, calc, colors, config, emoji, fuzzy, parsers, schedule, theme, units
from prisma.core.focus import BREAK, IDLE, WORK, FocusTimer
from prisma.core.frecency import Frecency
from prisma.core.policy import FacetWindowPolicy, notification_route


# ---------------------------------------------------------------- Rechner
@pytest.mark.parametrize("expr, expected", [
    ("1+2*3", 7),
    ("3,5*2", 7),
    ("2^10", 1024),
    ("(1+2)(3+4)", 21),
    ("sqrt(16)+1", 5),
    ("20% von 150", 30),
    ("50%", 0.5),
    ("2pi", 2 * math.pi),
    ("= 10/4", 2.5),
    ("1.234,5 + 0,5", 1235),
    ("fak(5)", 120),
])
def test_calculate(expr, expected):
    assert calc.calculate(expr) == pytest.approx(expected)


@pytest.mark.parametrize("expr", ["__import__('os')", "1/0", "2**99999", "a.b", "fak(1000)", "", "open('x')"])
def test_calculate_rejects_unsafe_or_invalid(expr):
    with pytest.raises(calc.CalcError):
        calc.calculate(expr)


def test_looks_like_math():
    assert calc.looks_like_math("3+4")
    assert calc.looks_like_math("=pi")
    assert calc.looks_like_math("sqrt(2)")
    assert not calc.looks_like_math("firefox")
    assert not calc.looks_like_math("2024")
    assert not calc.looks_like_math("gimp 2")


def test_format_number_german():
    assert calc.format_number(1234567) == "1.234.567"
    assert calc.format_number(3.5) == "3,5"
    assert calc.format_number(1234.25) == "1.234,25"
    assert calc.format_number(2.0) == "2"
    assert calc.format_number(0.1 + 0.2) == "0,3"


# ---------------------------------------------------------------- Einheiten
def test_units_length_and_mass():
    value, _src, result, dst = units.convert("5 km in mi")
    assert value == 5 and dst == "mi" and result == pytest.approx(3.10686, rel=1e-4)
    assert units.convert("1 kg nach lb")[2] == pytest.approx(2.20462, rel=1e-4)
    assert units.convert("1,5 h in min")[2] == pytest.approx(90)


def test_units_temperature_and_data():
    assert units.convert("100 c in f")[2] == pytest.approx(212)
    assert units.convert("32 f to c")[2] == pytest.approx(0)
    assert units.convert("1 gib in mb")[2] == pytest.approx(1073.741824)


def test_units_rejects_mismatch():
    assert units.convert("5 km in kg") is None
    assert units.convert("hallo welt") is None


# ---------------------------------------------------------------- Unscharfe Suche
def test_fuzzy_ranking():
    assert fuzzy.score("fire", "Firefox") > fuzzy.score("fire", "Bonfire Editor")
    assert fuzzy.score("lw", "LibreOffice Writer") > 0
    assert fuzzy.score("xyz", "Firefox") == 0
    assert fuzzy.score("einst", "Einstellungen") > fuzzy.score("einst", "Mein Stundenplan")


def test_fuzzy_folds_umlauts():
    assert fuzzy.score("ubersicht", "Übersicht") >= 150
    assert fuzzy.fold("Straße") == "strasse"


def test_emoji_search():
    chars = [c for c, _ in emoji.search("herz")]
    assert "❤️" in chars
    assert emoji.search("") and len(emoji.search("", limit=3)) == 3


# ---------------------------------------------------------------- Frecency
def test_frecency_prefers_recent_and_frequent(tmp_path):
    now = [1_000_000.0]
    store = Frecency(tmp_path / "f.json", clock=lambda: now[0])
    store.record("app:old")
    now[0] += 30 * 86400
    store.record("app:new")
    assert store.score("app:new") > store.score("app:old")
    reloaded = Frecency(tmp_path / "f.json", clock=lambda: now[0])
    assert reloaded.top()[0] == "app:new"


def test_frecency_survives_corrupt_file(tmp_path):
    path = tmp_path / "f.json"
    path.write_text("{kaputt")
    assert Frecency(path).data == {}


# ---------------------------------------------------------------- Konfiguration
def test_config_merge_and_normalize(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "facets": [{"name": "Uni", "color": "nicht-hex"}, {"name": "Uni"}],
        "appearance": {"dock_icon_size": 500, "mode": "bunt"},
        "focus": {"work_minutes": "abc"},
    }))
    cfg = config.load(path)
    ids = [f["id"] for f in cfg["facets"]]
    assert ids == ["uni", "uni-2"]
    assert cfg["facets"][0]["color"].startswith("#")
    assert cfg["appearance"]["dock_icon_size"] == 96
    assert cfg["appearance"]["mode"] == "auto"
    assert cfg["focus"]["work_minutes"] == 25
    assert cfg["kompass"]["web_search"]  # Standardwert ergänzt


def test_config_save_roundtrip(tmp_path):
    path = tmp_path / "sub" / "config.json"
    cfg = config.load(path)
    cfg["facets"][0]["name"] = "Büro"
    config.save(cfg, path)
    assert config.load(path)["facets"][0]["name"] == "Büro"


def test_find_facet():
    cfg = config.normalize(config.deep_merge(config.DEFAULT_CONFIG, {}))
    assert config.find_facet(cfg, "2")["id"] == "kreativ"
    assert config.find_facet(cfg, "FREIZEIT")["id"] == "freizeit"
    assert config.find_facet(cfg, "arb")["id"] == "arbeit"
    assert config.find_facet(cfg, "99") is None


# ---------------------------------------------------------------- Zeitplan
def test_dark_mode_schedule():
    assert schedule.is_dark("auto", datetime(2026, 1, 1, 22, 0))
    assert not schedule.is_dark("auto", datetime(2026, 1, 1, 12, 0))
    assert schedule.is_dark("dark", datetime(2026, 1, 1, 12, 0))
    assert not schedule.is_dark("light", datetime(2026, 1, 1, 23, 0))


def test_rules_and_overnight_windows():
    rules = [{"facet": "arbeit", "days": [0, 1, 2, 3, 4], "from": "08:00", "to": "17:00"},
             {"facet": "freizeit", "from": "22:00", "to": "06:00"}]
    monday_morning = datetime(2026, 10, 5, 9, 30)
    saturday_morning = datetime(2026, 10, 10, 9, 30)
    late_night = datetime(2026, 10, 6, 2, 0)
    assert schedule.facet_for_time(rules, monday_morning) == "arbeit"
    assert schedule.facet_for_time(rules, saturday_morning) is None
    assert schedule.facet_for_time(rules, late_night) == "freizeit"


def test_greeting_and_duration():
    assert schedule.greeting(datetime(2026, 1, 1, 8), "Jesse") == "Guten Morgen, Jesse"
    assert schedule.greeting(datetime(2026, 1, 1, 20)).startswith("Guten Abend")
    assert schedule.format_duration(3725) == "1 h 02 min"
    assert schedule.format_duration(90) == "1 min"


# ---------------------------------------------------------------- Fokus
def test_focus_timer_phases():
    now = [0.0]
    timer = FocusTimer(clock=lambda: now[0])
    timer.start(25, break_minutes=5)
    assert timer.phase == WORK and timer.label() == "25:00"
    now[0] += 25 * 60
    assert timer.tick() == "work-done"
    assert timer.phase == BREAK and timer.completed_sessions == 1
    now[0] += 5 * 60
    assert timer.tick() == "break-done"
    assert timer.phase == IDLE


# ---------------------------------------------------------------- Richtlinien
def test_notification_routes():
    route = notification_route
    assert route(2, "Kalender", "silent", True, True) == "popup"  # kritisch geht immer durch
    assert route(1, "Chat", "all", False, True) == "quiet"  # Nicht stören
    assert route(1, "Chat", "all", True, False) == "quiet"  # Fokus
    assert route(1, "Chat", "all", True, False, ["chat"]) == "popup"  # erlaubte App
    assert route(1, "Chat", "important", False, False) == "quiet"
    assert route(1, "Chat", "all", False, False) == "popup"


def test_facet_switch_minimizes_and_restores():
    policy = FacetWindowPolicy()
    policy.add("a", "arbeit")
    policy.add("b", "arbeit")
    policy.add("c", "freizeit")
    policy.focused("b")
    policy.focused("c")
    # Zu Freizeit: a und b werden versteckt; c war minimiert, aber nicht von Prisma
    actions = policy.switch("arbeit", "freizeit", {"a": False, "b": False, "c": True})
    assert ("minimize", "a") in actions and ("minimize", "b") in actions
    assert ("unminimize", "c") not in actions and ("activate", "c") not in actions
    # Zurück: a und b kommen wieder, b war zuletzt aktiv
    actions = policy.switch("freizeit", "arbeit", {"a": True, "b": True, "c": True})
    assert actions[:2] == [("unminimize", "a"), ("unminimize", "b")]
    assert actions[-1] == ("activate", "b")


def test_facet_move_and_retire():
    policy = FacetWindowPolicy()
    policy.add("a", "arbeit")
    assert policy.move("a", "kreativ", current="arbeit") == [("minimize", "a")]
    assert policy.facet_of("a") == "kreativ"
    policy.retire_facet("kreativ", "arbeit")
    assert policy.facet_of("a") == "arbeit"
    policy.remove("a")
    assert policy.windows_in("arbeit") == []


# ---------------------------------------------------------------- Farben & Thema
def test_colors_and_contrast():
    assert colors.hex_to_rgb("#fff") == (1.0, 1.0, 1.0)
    assert colors.mix("#000000", "#ffffff", 0.5) == "#808080"
    assert colors.contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert colors.readable_on("#ffffff") != "#ffffff"


@pytest.mark.parametrize("accent", ["#4f8cff", "#ffe600", "#101010", "#b26bff"])
@pytest.mark.parametrize("dark", [True, False])
def test_palette_keeps_accent_readable(accent, dark):
    palette = theme.make_palette(accent, dark)
    assert colors.contrast(palette.accent, palette.bg) >= 2.9
    css = theme.shell_css(palette)
    assert "$" not in css and palette.accent in css
    rc = theme.labwc_themerc(palette)
    assert "window.active.border.color: " + palette.accent in rc


# ---------------------------------------------------------------- Parser
def test_parsers():
    assert parsers.parse_wpctl_volume("Volume: 0.45 [MUTED]") == (0.45, True)
    assert parsers.parse_wpctl_volume("Volume: 1.00") == (1.0, False)
    assert parsers.parse_pactl_volume("Volume: front-left: 32768 /  50% / -18 dB, front-right: 32768 /  50%", "Mute: no") == (0.5, False)
    assert parsers.parse_brightnessctl("intel_backlight,backlight,600,50%,1200") == 0.5
    info = parsers.parse_nmcli_devices("wifi:connected:Heim\\:Netz\nethernet:unavailable:\nloopback:connected (externally):lo")
    assert info == {"kind": "wifi", "connected": True, "name": "Heim:Netz"}
    assert parsers.parse_wifi_signal("no:40\nyes:72") == 72
    assert parsers.parse_bluetoothctl_show("Controller X\n\tPowered: yes") is True
    assert parsers.network_icon(info, 72) == "network-wireless-signal-good-symbolic"
    assert parsers.battery_icon(76, True) == "battery-level-80-charging-symbolic"
    assert parsers.volume_icon(0.5, False) == "audio-volume-medium-symbolic"


def test_read_battery(tmp_path):
    bat = tmp_path / "BAT0"
    bat.mkdir()
    (bat / "type").write_text("Battery\n")
    (bat / "capacity").write_text("64\n")
    (bat / "status").write_text("Discharging\n")
    assert parsers.read_battery(tmp_path) == {"percent": 64, "charging": False, "status": "Discharging"}
    assert parsers.read_battery(tmp_path / "fehlt") is None


# ---------------------------------------------------------------- App-Zuordnung
def test_app_matching():
    apps = [
        appmatch.AppRecord("org.gnome.Nautilus", "Dateien", "nautilus"),
        appmatch.AppRecord("firefox_firefox", "Firefox", "firefox"),
        appmatch.AppRecord("code", "Visual Studio Code", "/usr/share/code/code", wm_class="Code"),
        appmatch.AppRecord("org.codeberg.dnkl.foot", "Foot", "foot"),
    ]
    assert appmatch.match_app("org.gnome.Nautilus", apps).name == "Dateien"
    assert appmatch.match_app("firefox", apps).name == "Firefox"
    assert appmatch.match_app("Code", apps).desktop_id == "code"
    assert appmatch.match_app("foot", apps).desktop_id == "org.codeberg.dnkl.foot"
    assert appmatch.match_app("unbekannt", apps) is None
    assert appmatch.resolve_pin("nicht-da|org.gnome.Nautilus", {"org.gnome.nautilus"}) == "org.gnome.nautilus"
    assert appmatch.resolve_pin("weg", set()) is None
