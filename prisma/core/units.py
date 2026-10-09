"""Einheitenumrechnung für den Kompass: „5 km in mi“, „180 cm nach ft“, „20 c in f“."""

from __future__ import annotations

import re

# Faktor zur Basiseinheit je Dimension
_UNITS: dict[str, tuple[str, float]] = {}


def _register(dimension: str, factor: float, *names: str) -> None:
    for name in names:
        _UNITS[name] = (dimension, factor)


# Länge (Basis: Meter)
_register("length", 1e-3, "mm", "millimeter")
_register("length", 1e-2, "cm", "zentimeter", "centimeter")
_register("length", 1.0, "m", "meter", "metre")
_register("length", 1e3, "km", "kilometer")
_register("length", 0.0254, "in", "inch", "zoll", '"')
_register("length", 0.3048, "ft", "foot", "feet", "fuß", "fuss")
_register("length", 0.9144, "yd", "yard", "yards")
_register("length", 1609.344, "mi", "mile", "miles", "meile", "meilen")
_register("length", 1852.0, "sm", "seemeile", "nmi")
# Masse (Basis: Kilogramm)
_register("mass", 1e-6, "mg", "milligramm")
_register("mass", 1e-3, "g", "gramm", "gram")
_register("mass", 1.0, "kg", "kilo", "kilogramm", "kilogram")
_register("mass", 1e3, "t", "tonne", "tonnen")
_register("mass", 0.45359237, "lb", "lbs", "pound", "pounds", "pfund")
_register("mass", 0.028349523125, "oz", "ounce", "unze")
_register("mass", 6.35029318, "st", "stone")
# Volumen (Basis: Liter)
_register("volume", 1e-3, "ml", "milliliter")
_register("volume", 1e-2, "cl", "zentiliter")
_register("volume", 1.0, "l", "liter", "litre")
_register("volume", 1e3, "m3", "m³", "kubikmeter")
_register("volume", 3.785411784, "gal", "gallon", "gallone")
_register("volume", 0.473176473, "pint", "pt")
_register("volume", 0.2365882365, "cup", "tasse")
_register("volume", 0.0295735295625, "floz", "fl oz")
# Zeit (Basis: Sekunde)
_register("time", 1e-3, "ms", "millisekunde", "millisekunden")
_register("time", 1.0, "s", "sek", "sekunde", "sekunden", "sec", "second", "seconds")
_register("time", 60.0, "min", "minute", "minuten", "minutes")
_register("time", 3600.0, "h", "std", "stunde", "stunden", "hour", "hours")
_register("time", 86400.0, "d", "tag", "tage", "tagen", "day", "days")
_register("time", 604800.0, "wo", "woche", "wochen", "week", "weeks")
_register("time", 31557600.0, "a", "jahr", "jahre", "year", "years")
# Daten (Basis: Byte)
_register("data", 1 / 8, "bit", "bits")
_register("data", 1.0, "b", "byte", "bytes")
for _i, _prefix in enumerate(("k", "m", "g", "t", "p"), start=1):
    _register("data", 1000.0**_i, f"{_prefix}b", f"{_prefix}byte")
    _register("data", 1024.0**_i, f"{_prefix}ib")
# Geschwindigkeit (Basis: m/s)
_register("speed", 1.0, "m/s", "mps")
_register("speed", 1 / 3.6, "km/h", "kmh", "kph")
_register("speed", 0.44704, "mph")
_register("speed", 0.514444, "kn", "knoten", "knots")
# Fläche (Basis: m²)
_register("area", 1.0, "m2", "m²", "qm", "quadratmeter")
_register("area", 1e4, "ha", "hektar")
_register("area", 1e6, "km2", "km²")
_register("area", 4046.8564224, "acre", "acres")
_register("area", 0.09290304, "ft2", "ft²", "sqft")
# Energie (Basis: Joule)
_register("energy", 1.0, "j", "joule")
_register("energy", 1e3, "kj", "kilojoule")
_register("energy", 4.184, "cal")
_register("energy", 4184.0, "kcal", "kalorien")
_register("energy", 3.6e6, "kwh")

_TEMPERATURE = {
    "c": "c", "°c": "c", "celsius": "c", "grad": "c",
    "f": "f", "°f": "f", "fahrenheit": "f",
    "k": "k", "kelvin": "k",
}

_PATTERN = re.compile(
    r"^\s*(-?[\d.,]+)\s*([^\s\d][\w°²³/\"]*(?:\s?oz)?)\s+(?:in|to|nach|zu|als|->|=)\s+([\w°²³/\"]+(?:\s?oz)?)\s*$",
    re.IGNORECASE,
)


def _to_kelvin(value: float, unit: str) -> float:
    return {"c": value + 273.15, "f": (value - 32) * 5 / 9 + 273.15, "k": value}[unit]


def _from_kelvin(value: float, unit: str) -> float:
    return {"c": value - 273.15, "f": (value - 273.15) * 9 / 5 + 32, "k": value}[unit]


def _number(text: str) -> float:
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")
    return float(text)


def convert(query: str) -> tuple[float, str, float, str] | None:
    """Gibt (wert, von, ergebnis, nach) zurück oder None, wenn keine Umrechnung erkannt wurde."""
    match = _PATTERN.match(query)
    if not match:
        return None
    try:
        value = _number(match.group(1))
    except ValueError:
        return None
    src, dst = match.group(2).lower().strip(), match.group(3).lower().strip()
    if src in _TEMPERATURE and dst in _TEMPERATURE:
        result = _from_kelvin(_to_kelvin(value, _TEMPERATURE[src]), _TEMPERATURE[dst])
        return value, _TEMPERATURE[src].upper() if src != "k" else "K", result, _TEMPERATURE[dst].upper()
    if src not in _UNITS or dst not in _UNITS:
        return None
    (dim_a, fac_a), (dim_b, fac_b) = _UNITS[src], _UNITS[dst]
    if dim_a != dim_b:
        return None
    return value, match.group(2).strip(), value * fac_a / fac_b, match.group(3).strip()
