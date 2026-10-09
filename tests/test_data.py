"""Prüft die mitgelieferten Daten: labwc-XML, Desktop-Dateien und Tastenkürzel → prisma-msg."""

import configparser
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from prisma import msg

ROOT = Path(__file__).resolve().parent.parent
LABWC = ROOT / "data" / "labwc"
# Aktionen, die die Shell als Gio-Aktionen anbietet (siehe prisma/shell/app.py)
SHELL_ACTIONS = {"kompass", "quicksettings", "daypanel", "dnd", "lock", "reload", "facet-next", "facet-prev",
                 "theme-cycle", "kompass-query", "facet", "move-to-facet", "focus", "volume", "brightness",
                 "screenshot", "power"}


@pytest.mark.parametrize("name", ["rc.xml", "menu.xml"])
def test_labwc_xml_is_well_formed(name):
    ET.parse(LABWC / name)  # wirft bei Fehlern, z. B. „--“ in Kommentaren


def test_keybinds_only_use_known_commands():
    tree = ET.parse(LABWC / "rc.xml")
    commands = [a.get("command") for a in tree.iter("action") if a.get("name") == "Execute"]
    tree = ET.parse(LABWC / "menu.xml")
    commands += [a.get("command") for a in tree.iter("action") if a.get("name") == "Execute"]
    assert commands
    for command in commands:
        program, *args = command.split()
        assert program in {"prisma-msg", "prisma-launch", "prisma-settings"}, command
        if program == "prisma-msg":
            assert args[0] in SHELL_ACTIONS, command
            assert args[0] in msg.USAGE or args[0] in msg.WITH_ARGUMENT, command


def test_shell_registers_documented_actions():
    source = (ROOT / "prisma" / "shell" / "app.py").read_text()
    for action in SHELL_ACTIONS:
        assert re.search(rf'"{re.escape(action)}":', source), action


@pytest.mark.parametrize("path", sorted((ROOT / "data").rglob("*.desktop")))
def test_desktop_files(path):
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read(path, encoding="utf-8")
    entry = parser["Desktop Entry"]
    assert entry["Type"] == "Application"
    assert entry["Name"] and entry["Exec"]
    assert (ROOT / "bin" / entry["Exec"].split()[0]).exists()


def test_bin_scripts_point_to_existing_modules():
    for script in (ROOT / "bin").iterdir():
        text = script.read_text()
        match = re.search(r"-m (prisma[\w.]*)", text)
        if match:
            module = ROOT / (match.group(1).replace(".", "/") + ".py")
            assert module.exists(), f"{script.name}: {module}"
