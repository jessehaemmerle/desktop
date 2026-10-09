"""Kleine Emoji-Auswahl für den Kompass (Präfix ':') – mit deutschen und englischen Stichworten."""

from __future__ import annotations

from .fuzzy import best

EMOJI: list[tuple[str, str]] = [
    ("😀", "grinsen lachen grin smile"),
    ("😂", "tränen lachen joy lol"),
    ("😊", "lächeln freundlich blush smile"),
    ("😉", "zwinkern wink"),
    ("😍", "verliebt herzaugen love"),
    ("😎", "cool sonnenbrille sunglasses"),
    ("🤔", "nachdenken denken thinking hmm"),
    ("😅", "puh erleichtert sweat"),
    ("😢", "traurig weinen sad cry"),
    ("😡", "wütend sauer angry"),
    ("😴", "müde schlafen sleep"),
    ("🥳", "party feiern celebrate"),
    ("🤯", "kopf explodiert mindblown"),
    ("🙈", "affe nichts sehen monkey"),
    ("👍", "daumen hoch gut ok thumbs up"),
    ("👎", "daumen runter schlecht thumbs down"),
    ("👏", "klatschen applaus clap"),
    ("🙏", "danke bitte beten thanks please"),
    ("👋", "winken hallo tschüss wave hello"),
    ("💪", "stark muskel strong"),
    ("✌️", "frieden victory peace"),
    ("👀", "augen schauen eyes look"),
    ("❤️", "herz liebe heart love"),
    ("💔", "gebrochenes herz broken heart"),
    ("🔥", "feuer heiß fire lit"),
    ("✨", "funkeln glitzer sparkles"),
    ("⭐", "stern star"),
    ("🎉", "konfetti party tada"),
    ("🎂", "geburtstag kuchen birthday cake"),
    ("🎁", "geschenk gift present"),
    ("☕", "kaffee coffee"),
    ("🍕", "pizza"),
    ("🍺", "bier beer prost"),
    ("🍷", "wein wine"),
    ("🌞", "sonne sun"),
    ("🌧️", "regen rain"),
    ("❄️", "schnee kalt snow"),
    ("🌈", "regenbogen rainbow"),
    ("🌍", "welt erde earth world"),
    ("🚀", "rakete start launch rocket"),
    ("💡", "idee glühbirne idea"),
    ("📌", "pin anheften"),
    ("📅", "kalender termin calendar"),
    ("⏰", "wecker zeit alarm"),
    ("✅", "erledigt fertig haken done check"),
    ("❌", "nein falsch kreuz no cross"),
    ("⚠️", "warnung achtung warning"),
    ("❓", "frage question"),
    ("💯", "hundert perfekt hundred"),
    ("🐛", "bug käfer fehler"),
    ("💻", "laptop computer"),
    ("🐧", "pinguin linux tux penguin"),
    ("🔒", "schloss gesperrt lock"),
    ("🎵", "musik note music"),
    ("📷", "kamera foto camera"),
    ("🏠", "haus zuhause home"),
    ("🚗", "auto car"),
    ("✈️", "flugzeug reise plane travel"),
    ("🐶", "hund dog"),
    ("🐱", "katze cat"),
    ("🦄", "einhorn unicorn"),
    ("🤝", "handschlag deal handshake"),
    ("🫶", "herzhände heart hands"),
    ("🙌", "hände hoch hooray"),
    ("😬", "grimasse awkward"),
    ("🤷", "achselzucken keine ahnung shrug"),
    ("🤦", "facepalm"),
]


def search(query: str, limit: int = 8) -> list[tuple[str, str]]:
    query = query.strip()
    if not query:
        return EMOJI[:limit]
    scored = []
    for char, words in EMOJI:
        s = max(best(query, w) for w in words.split())
        if s > 60:
            scored.append((s, char, words))
    scored.sort(key=lambda item: -item[0])
    return [(char, words) for _, char, words in scored[:limit]]
