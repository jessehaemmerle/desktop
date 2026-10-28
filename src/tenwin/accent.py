"""Accent colour from the desktop background (Windows 10's "Automatically
pick an accent color from my background") and the neutral dark accent."""

import colorsys
import logging

from tenwin.theme import hex_to_rgb, rgb_to_hex

log = logging.getLogger(__name__)

DARK_ACCENT = "#3C3C3C"      # "Dark": neutral graphite instead of a colour
FALLBACK_ACCENT = "#0078D7"
HUE_BINS = 36


def usable(rgb):
    """Make a colour work as an accent: readable with white text, not washed out."""
    h, l, s = colorsys.rgb_to_hls(*rgb)
    if s < 0.12:
        # Grey picture: a neutral grey accent in the same brightness family.
        return rgb_to_hex(colorsys.hls_to_rgb(h, max(0.28, min(0.42, l)), s))
    l = max(0.30, min(0.46, l))
    s = max(0.45, min(0.90, s))
    return rgb_to_hex(colorsys.hls_to_rgb(h, l, s))


def dominant_color(pixels):
    """Most prominent vivid colour of an iterable of (r, g, b) floats in 0..1.

    Pixels are binned by hue and weighted by saturation and by how far they
    are from black/white, so a small saturated area beats a large grey sky.
    """
    weights = [0.0] * HUE_BINS
    sums = [[0.0, 0.0, 0.0] for _ in range(HUE_BINS)]
    total = grey_total = 0.0
    grey_sum = [0.0, 0.0, 0.0]
    for r, g, b in pixels:
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        total += 1
        weight = s * s * (1.0 - abs(v - 0.65)) if v > 0.12 else 0.0
        if weight < 0.02:
            grey_total += 1
            grey_sum[0] += r
            grey_sum[1] += g
            grey_sum[2] += b
            continue
        index = int(h * HUE_BINS) % HUE_BINS
        weights[index] += weight
        sums[index][0] += r * weight
        sums[index][1] += g * weight
        sums[index][2] += b * weight
    if not total:
        return None
    # Merge each bin with its neighbours so a hue split across bins still wins.
    best, best_score = None, 0.0
    for i in range(HUE_BINS):
        score = weights[i] + 0.5 * (weights[i - 1] + weights[(i + 1) % HUE_BINS])
        if score > best_score:
            best, best_score = i, score
    if best is None or best_score < total * 0.004:
        if grey_total:
            return tuple(c / grey_total for c in grey_sum)
        return None
    w = weights[best]
    return tuple(c / w for c in sums[best])


def from_picture(path, size=64):
    """Accent for a picture file (None if it can't be read)."""
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf, GLib
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, True)
    except (GLib.Error, TypeError) as exc:
        log.info("cannot read %s: %s", path, exc)
        return None
    data = pixbuf.get_pixels()
    n = pixbuf.get_n_channels()
    stride = pixbuf.get_rowstride()
    width, height = pixbuf.get_width(), pixbuf.get_height()

    def pixels():
        for y in range(height):
            row = y * stride
            for x in range(width):
                i = row + x * n
                yield data[i] / 255.0, data[i + 1] / 255.0, data[i + 2] / 255.0

    rgb = dominant_color(pixels())
    return usable(rgb) if rgb else None


def for_settings(settings):
    """The accent the current settings ask for, or None for "manual"."""
    mode = settings["appearance.accent_mode"]
    if mode == "dark":
        return DARK_ACCENT
    if mode != "wallpaper":
        return None
    if settings["background.type"] == "color":
        return usable(hex_to_rgb(settings["background.color"]))
    from tenwin import paths
    path = settings["background.picture"] or paths.default_wallpaper()
    return from_picture(path) or FALLBACK_ACCENT
