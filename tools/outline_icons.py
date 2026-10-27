#!/usr/bin/env python3
"""Convert the stroked symbolic icons into filled outlines.

GTK 3 recolours *-symbolic.svg icons by forcing ``fill`` on every path, rect
and circle, so stroke-only artwork turns into blobs. This tool buffers all
strokes into polygons (with shapely) and writes fill-only SVGs.

Only needed when regenerating assets:

    python3 -m venv /tmp/toolenv && /tmp/toolenv/bin/pip install shapely svgelements
    /tmp/toolenv/bin/python tools/outline_icons.py
"""

import sys
from pathlib import Path

from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import unary_union
from svgelements import SVG, Close, Line, Move, Path as SvgPath, Shape

ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = ROOT / "data" / "icons" / "hicolor" / "scalable" / "actions"
SAMPLES = 24


def subpaths(path):
    """Yield (points, closed) for each subpath of an svgelements Path."""
    points, closed = [], False
    for seg in path:
        if isinstance(seg, Move):
            if len(points) > 1:
                yield points, closed
            points, closed = [(seg.end.x, seg.end.y)], False
        elif isinstance(seg, Close):
            closed = True
            if points and seg.end is not None:
                points.append((seg.end.x, seg.end.y))
        elif isinstance(seg, Line):
            points.append((seg.end.x, seg.end.y))
        else:
            for i in range(1, SAMPLES + 1):
                p = seg.point(i / SAMPLES)
                points.append((p.x, p.y))
    if len(points) > 1:
        yield points, closed


def element_geometry(element):
    path = abs(SvgPath(element))
    fill = element.fill is not None and element.fill.value is not None and element.fill.alpha > 0
    stroke = element.stroke is not None and element.stroke.value is not None and element.stroke.alpha > 0
    width = element.stroke_width or 1.0
    cap = {"round": 1, "square": 3}.get(element.values.get("stroke-linecap"), 2)
    join = {"round": 1, "bevel": 3}.get(element.values.get("stroke-linejoin"), 2)
    shapes = []
    for points, closed in subpaths(path):
        if fill and len(points) >= 3:
            poly = Polygon(points)
            if not poly.is_valid:
                poly = poly.buffer(0)
            shapes.append(poly)
        if stroke:
            line = LineString(points)
            if closed and len(points) >= 3:
                line = Polygon(points).exterior
            shapes.append(line.buffer(width / 2.0, cap_style=cap, join_style=join, mitre_limit=4))
    return unary_union(shapes) if shapes else None


def to_d(geometry):
    polys = geometry.geoms if isinstance(geometry, MultiPolygon) else [geometry]
    parts = []
    for poly in polys:
        if poly.is_empty or not isinstance(poly, Polygon):
            continue
        for ring in [poly.exterior] + list(poly.interiors):
            coords = list(ring.coords)
            parts.append("M" + " L".join("%.2f %.2f" % c for c in coords[:-1]) + "Z")
    return "".join(parts)


def outline(svg_path):
    doc = SVG.parse(str(svg_path))
    layers = {}
    for element in doc.elements():
        if not isinstance(element, Shape):
            continue
        geometry = element_geometry(element)
        if geometry is None or geometry.is_empty:
            continue
        opacity = round(float(element.values.get("opacity", 1.0)), 3)
        layers.setdefault(opacity, []).append(geometry)
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">']
    for opacity, geoms in sorted(layers.items(), reverse=True):
        d = to_d(unary_union(geoms))
        if d:
            attr = "" if opacity >= 1 else ' opacity="%s"' % opacity
            out.append('<path fill="#bebebe" fill-rule="evenodd"%s d="%s"/>' % (attr, d))
    out.append("</svg>")
    svg_path.write_text("".join(out) + "\n", encoding="utf-8")


def main(argv):
    files = [Path(a) for a in argv] or sorted(ICON_DIR.glob("*-symbolic.svg"))
    for path in files:
        outline(path)
    print("outlined %d icons" % len(files))


if __name__ == "__main__":
    main(sys.argv[1:])
