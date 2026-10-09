"""``prisma-lock`` – sperrt den Bildschirm mit swaylock in den Farben der aktiven Facette."""

from __future__ import annotations

import json
import os
import shutil
import sys

from .core import config as cfg
from .core.theme import make_palette


def swaylock_args(accent: str) -> list[str]:
    palette = make_palette(accent, True)  # Sperrbildschirm ist immer dunkel – schont die Augen nachts
    strip = lambda color: color.lstrip("#")  # noqa: E731
    return [
        "swaylock", "-f", "-F",
        "-c", strip(palette.bg),
        "--ring-color", strip(palette.accent),
        "--ring-ver-color", strip(palette.accent),
        "--inside-ver-color", strip(palette.surface_solid),
        "--key-hl-color", "ffffff",
        "--bs-hl-color", "ff8a8a",
        "--inside-color", strip(palette.surface_solid),
        "--inside-clear-color", strip(palette.surface_solid),
        "--line-color", "00000000",
        "--separator-color", "00000000",
        "--text-color", "eef0f6",
        "--indicator-radius", "90",
        "--indicator-thickness", "8",
    ]


def current_accent() -> str:
    config = cfg.load()
    facet_id = ""
    try:
        with open(cfg.state_dir() / "state.json", encoding="utf-8") as fh:
            facet_id = json.load(fh).get("facet", "")
    except (OSError, ValueError, AttributeError):
        pass
    facet = cfg.find_facet(config, facet_id) or config["facets"][0]
    return facet["color"]


def main() -> int:
    if shutil.which("swaylock") is None:
        os.execvp("loginctl", ["loginctl", "lock-session"])
    args = swaylock_args(current_accent())
    os.execvp(args[0], args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
