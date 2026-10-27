import re
import subprocess
from pathlib import Path

import pytest

from tenwin.shell.notifications import sanitize_markup

ROOT = Path(__file__).resolve().parent.parent


def test_sanitize_markup_keeps_basic_tags():
    assert sanitize_markup("Hello <b>World</b>") == "Hello <b>World</b>"


def test_sanitize_markup_escapes_everything_else():
    out = sanitize_markup('<a href="x">link</a> & <img src=x onerror=1> <i>ok</i>')
    assert "<a" not in out and "<img" not in out
    assert "&amp;" in out and "<i>ok</i>" in out


def test_sanitize_markup_handles_broken_markup():
    out = sanitize_markup("<b>unclosed")
    assert "unclosed" in out


def test_german_catalog_complete():
    po = (ROOT / "po" / "de.po").read_text(encoding="utf-8")
    empty = re.findall(r'\nmsgid "(.+)"\nmsgstr ""\n', po)
    assert empty == []
    result = subprocess.run(["msgfmt", "--check", "-o", "/dev/null", str(ROOT / "po" / "de.po")],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("name", ["common", "shell", "desktop", "explorer", "settings", "greeter"])
def test_css_templates_have_no_unknown_placeholders(name):
    from tenwin import theme
    css = theme.render_css(name)
    assert "$" not in css, "unfilled placeholder in %s.css" % name


def test_symbolic_icons_have_no_strokes():
    """GTK recolours symbolic icons via fill only (see tools/outline_icons.py)."""
    icons = list((ROOT / "data/icons/hicolor/scalable/actions").glob("*-symbolic.svg"))
    assert icons
    for icon in icons:
        assert "stroke" not in icon.read_text(), icon.name


def test_desktop_files_valid():
    for path in (ROOT / "data").rglob("*.desktop"):
        text = path.read_text(encoding="utf-8")
        assert text.startswith("[Desktop Entry]"), path
        assert "\nName=" in text and "\nExec=" in text, path
