"""Ordnet Wayland-``app_id``s den passenden .desktop-Einträgen zu."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class AppRecord:
    desktop_id: str  # ohne ".desktop"
    name: str
    executable: str = ""
    wm_class: str = ""
    keywords: list[str] = field(default_factory=list)


def _norm(value: str) -> str:
    value = (value or "").strip().lower()
    if value.endswith(".desktop"):
        value = value[:-8]
    return value


def match_app(app_id: str, apps: list[AppRecord]) -> AppRecord | None:
    """Mehrstufige Zuordnung – von exakt bis heuristisch."""
    wanted = _norm(app_id)
    if not wanted:
        return None
    by_id = {_norm(a.desktop_id): a for a in apps}
    if wanted in by_id:
        return by_id[wanted]
    # Snap-Pakete: firefox → firefox_firefox
    snap = f"{wanted}_{wanted}"
    if snap in by_id:
        return by_id[snap]
    for app in apps:
        if app.wm_class and _norm(app.wm_class) == wanted:
            return app
    # Letztes Segment des Reverse-DNS-Namens: org.gnome.Nautilus ↔ nautilus
    for app in apps:
        if _norm(app.desktop_id).rsplit(".", 1)[-1] == wanted.rsplit(".", 1)[-1]:
            return app
    for app in apps:
        if app.executable and os.path.basename(app.executable).lower() == wanted.rsplit(".", 1)[-1]:
            return app
    for app in apps:
        if _norm(app.name) == wanted:
            return app
    return None


def resolve_pin(pin: str, available: set[str]) -> str | None:
    """'a|b|c' → erste Alternative, die installiert ist."""
    for candidate in pin.split("|"):
        candidate = _norm(candidate)
        if candidate and candidate in available:
            return candidate
    return None
