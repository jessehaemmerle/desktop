"""Unscharfe Suche mit Bonus für Wortanfänge, Präfixe und zusammenhängende Treffer."""

from __future__ import annotations

import unicodedata


def fold(text: str) -> str:
    """Kleinschreibung + Umlaute/Akzente vereinheitlichen (ä→a, é→e, ß→ss)."""
    text = text.lower().replace("ß", "ss")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def score(query: str, text: str) -> float:
    """0 = kein Treffer; höher = besser. Bewertung bleibt unter ~200."""
    if not query:
        return 1.0
    q, t = fold(query.strip()), fold(text)
    if not q or not t:
        return 0.0
    if t == q:
        return 200.0
    if t.startswith(q):
        return 150.0 + 20.0 * len(q) / len(t)
    words = t.replace("-", " ").replace("_", " ").replace(".", " ").split()
    if any(w.startswith(q) for w in words):
        return 120.0 + 10.0 * len(q) / len(t)
    position = t.find(q)
    if position >= 0:
        return 90.0 - min(position, 30) * 0.5
    # Initialen: "lw" → "LibreOffice Writer"
    initials = "".join(w[0] for w in words if w)
    if len(q) >= 2 and initials.startswith(q):
        return 85.0
    # Teilfolge mit Bonus für Nachbarschaft und Wortgrenzen
    total, last, ti = 0.0, -2, 0
    for ch in q:
        found = t.find(ch, ti)
        if found < 0:
            return 0.0
        bonus = 3.0 if found == last + 1 else 1.0
        if found == 0 or t[found - 1] in " -_.":
            bonus += 2.0
        total += bonus
        last, ti = found, found + 1
    return min(80.0, 20.0 + total * 40.0 / (len(q) * 5.0) + 10.0 * len(q) / len(t))


def best(query: str, *fields: str, weights: tuple[float, ...] | None = None) -> float:
    weights = weights or tuple(1.0 for _ in fields)
    return max((score(query, f) * w for f, w in zip(fields, weights) if f), default=0.0)
