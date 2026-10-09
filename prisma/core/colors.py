"""Farbwerkzeuge: Mischen, Kontrast und Farbtonverschiebung für die Facetten-Paletten."""

from __future__ import annotations

import colorsys

RGB = tuple[float, float, float]


def hex_to_rgb(value: str) -> RGB:
    value = value.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        raise ValueError(f"Ungültige Farbe: #{value}")
    return tuple(int(value[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def rgb_to_hex(rgb: RGB) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02x}" for c in rgb)


def mix(a: str, b: str, t: float) -> str:
    """Lineare Mischung: t=0 → a, t=1 → b."""
    ra, rb = hex_to_rgb(a), hex_to_rgb(b)
    return rgb_to_hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))  # type: ignore[arg-type]


def lighten(color: str, t: float) -> str:
    return mix(color, "#ffffff", t)


def darken(color: str, t: float) -> str:
    return mix(color, "#000000", t)


def shift_hue(color: str, degrees: float, saturation: float = 1.0, value: float = 1.0) -> str:
    r, g, b = hex_to_rgb(color)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    h = (h + degrees / 360.0) % 1.0
    return rgb_to_hex(colorsys.hsv_to_rgb(h, min(1.0, s * saturation), min(1.0, v * value)))


def luminance(color: str) -> float:
    """Relative Leuchtdichte nach WCAG 2.x."""

    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in hex_to_rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def readable_on(background: str, light: str = "#ffffff", dark: str = "#14161c") -> str:
    """Textfarbe für einen Hintergrund – helle Schrift, solange sie gut lesbar bleibt (≥ 2,8:1)."""
    if contrast(background, light) >= 2.8:
        return light
    return light if contrast(background, light) >= contrast(background, dark) else dark


def rgba(color: str, alpha: float) -> str:
    r, g, b = hex_to_rgb(color)
    return f"rgba({round(r * 255)}, {round(g * 255)}, {round(b * 255)}, {alpha:.3f})"
