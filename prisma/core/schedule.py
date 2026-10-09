"""Zeitlogik: Tageslicht-Modus und zeitbasierte Facetten-Regeln."""

from __future__ import annotations

from datetime import datetime


def parse_hm(value: str) -> int:
    """'07:30' → Minuten seit Mitternacht."""
    hours, _, minutes = str(value).strip().partition(":")
    h, m = int(hours), int(minutes or 0)
    if not (0 <= h <= 24 and 0 <= m < 60):
        raise ValueError(f"Ungültige Uhrzeit: {value}")
    return min(h * 60 + m, 24 * 60)


def in_window(minute: int, start: int, end: int) -> bool:
    """Liegt ``minute`` in [start, end)? Fenster über Mitternacht werden unterstützt."""
    if start == end:
        return True
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end


def minute_of(now: datetime) -> int:
    return now.hour * 60 + now.minute


def is_dark(mode: str, now: datetime, light_from: str = "07:00", dark_from: str = "19:00") -> bool:
    if mode == "dark":
        return True
    if mode == "light":
        return False
    try:
        return not in_window(minute_of(now), parse_hm(light_from), parse_hm(dark_from))
    except ValueError:
        return True


def rule_matches(rule: dict, now: datetime) -> bool:
    days = rule.get("days")
    if days is not None and now.weekday() not in days:
        return False
    try:
        start = parse_hm(rule.get("from", "00:00"))
        end = parse_hm(rule.get("to", "24:00"))
    except ValueError:
        return False
    return in_window(minute_of(now), start, end)


def facet_for_time(rules: list[dict], now: datetime, fallback: str | None = None) -> str | None:
    """Erste passende Regel gewinnt; sonst ``fallback``."""
    for rule in rules:
        if rule.get("facet") and rule_matches(rule, now):
            return rule["facet"]
    return fallback


def greeting(now: datetime, name: str = "") -> str:
    hour = now.hour
    if 5 <= hour < 11:
        text = "Guten Morgen"
    elif 11 <= hour < 14:
        text = "Mahlzeit"
    elif 14 <= hour < 18:
        text = "Schönen Nachmittag"
    elif 18 <= hour < 23:
        text = "Guten Abend"
    else:
        text = "Gute Nacht"
    return f"{text}, {name}" if name else text


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    if hours:
        return f"{hours} h {minutes:02d} min"
    return f"{minutes} min"
