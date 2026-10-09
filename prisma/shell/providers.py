"""Ergebnisquellen des Kompass: Apps, Rechner, Einheiten, Dateien, Fenster, Facetten, Aktionen …"""

from __future__ import annotations

import os
import re
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Callable

from gi.repository import Gdk, Gio, GLib, Gtk

from ..core import calc, emoji, fuzzy, units
from . import util

PREFIXES = {
    "=": "Rechnen",
    ">": "Facetten",
    "/": "Dateien",
    "$": "Befehl",
    "?": "Web",
    ":": "Emoji",
}


@dataclass
class Result:
    title: str
    subtitle: str = ""
    icon: object = None
    kind: str = ""
    score: float = 0.0
    action: Callable | None = None
    key: str = ""  # Schlüssel für die lernende Reihenfolge
    big: bool = False
    keep_open: bool = False
    extra: dict = field(default_factory=dict)


def copy_text(text: str) -> None:
    Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
    Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).store()
    if util.has("wl-copy"):
        util.spawn(["wl-copy", "--", text])


# ---------------------------------------------------------------- Dateiindex
class FileIndex:
    """Durchsucht das Home-Verzeichnis im Hintergrund (begrenzte Tiefe, ohne versteckte Ordner)."""

    SKIP = {"node_modules", "__pycache__", "venv", ".venv", "snap", "site-packages", "target", "build", "dist"}
    MAX_FILES = 25000
    MAX_DEPTH = 5

    def __init__(self):
        self.entries: list[tuple[str, str]] = []  # (gefalteter Name, Pfad)
        self.recent: list[str] = []
        self._built = 0.0
        self._lock = threading.Lock()

    def ensure(self) -> None:
        if time.monotonic() - self._built > 300 or not self._built:
            self._built = time.monotonic()
            threading.Thread(target=self._build, daemon=True).start()

    def _build(self) -> None:
        home = os.path.expanduser("~")
        entries: list[tuple[str, str]] = []
        for root, dirs, files in os.walk(home):
            depth = root[len(home):].count(os.sep)
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in self.SKIP and depth < self.MAX_DEPTH]
            for name in dirs + files:
                if not name.startswith("."):
                    entries.append((fuzzy.fold(name), os.path.join(root, name)))
            if len(entries) > self.MAX_FILES:
                break
        recent = self._read_recent()
        with self._lock:
            self.entries, self.recent = entries, recent

    @staticmethod
    def _read_recent() -> list[str]:
        path = os.path.join(GLib.get_user_data_dir(), "recently-used.xbel")
        try:
            tree = ET.parse(path)
        except (OSError, ET.ParseError):
            return []
        items = []
        for bookmark in tree.getroot().iter("bookmark"):
            href = bookmark.get("href", "")
            if href.startswith("file://"):
                local = urllib.parse.unquote(href[7:])
                items.append((bookmark.get("visited") or bookmark.get("modified") or "", local))
        items.sort(reverse=True)
        return [p for _t, p in items[:300] if os.path.exists(p)]

    def search(self, query: str, limit: int = 6) -> list[tuple[float, str]]:
        folded = fuzzy.fold(query.strip())
        if not folded:
            return [(100.0, p) for p in self.recent[:limit]]
        with self._lock:
            entries, recent = self.entries, self.recent
        results: dict[str, float] = {}
        for path in recent:
            name = fuzzy.fold(os.path.basename(path))
            if folded in name:
                results[path] = fuzzy.score(folded, name) + 25
        for name, path in entries:
            if folded in name and path not in results:
                results[path] = fuzzy.score(folded, name) - path.count(os.sep) * 0.5
        return sorted(((s, p) for p, s in results.items()), reverse=True)[:limit]


def file_icon(path: str) -> Gio.Icon:
    if os.path.isdir(path):
        return Gio.ThemedIcon.new("folder")
    content_type, _uncertain = Gio.content_type_guess(path, None)
    return Gio.content_type_get_icon(content_type)


def open_path(path: str) -> None:
    try:
        Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(),
                                           Gdk.Display.get_default().get_app_launch_context())
    except GLib.Error as exc:
        print(f"prisma: {path} lässt sich nicht öffnen: {exc.message}")


# ------------------------------------------------------------------ Provider
class Providers:
    def __init__(self, app, hub, services):
        self.app, self.hub, self.services = app, hub, services
        self.files = FileIndex()

    def warm_up(self) -> None:
        if self.hub.config["kompass"].get("index_files", True):
            self.files.ensure()

    def query(self, text: str) -> list[Result]:
        stripped = text.strip()
        prefix = stripped[:1] if stripped[:1] in PREFIXES else ""
        rest = stripped[1:].strip() if prefix else stripped
        if prefix == "=":
            return self._calc(rest, forced=True)
        if prefix == ">":
            return self._facets(rest, forced=True)
        if prefix == "/":
            return self._files(rest, forced=True)
        if prefix == "$":
            return self._command(rest)
        if prefix == "?":
            return self._web(rest, forced=True)
        if prefix == ":":
            return self._emoji(rest)
        if not stripped:
            return self._suggestions()
        results: list[Result] = []
        results += self._calc(stripped)
        results += self._units(stripped)
        results += self._apps(stripped)
        results += self._facets(stripped)
        results += self._windows(stripped)
        results += self._actions(stripped)
        results += self._settings(stripped)
        if len(stripped) >= 3:
            results += self._files(stripped)
        results += self._web(stripped)
        for result in results:
            if result.key:
                result.score += min(45.0, 15.0 * self.hub.frecency.score(result.key))
        results.sort(key=lambda r: -r.score)
        return results[:9]

    # ------------------------------------------------------------ Vorschläge
    def _suggestions(self) -> list[Result]:
        results = []
        for key in self.hub.frecency.top(6):
            kind, _, ident = key.partition(":")
            if kind == "app":
                app = self.hub.apps.get(ident)
                if app is not None:
                    results.append(self._app_result(app, 100))
        if not self.hub.focus.active:
            minutes = self.hub.config["focus"]["work_minutes"]
            results.append(Result(f"Fokus-Session starten ({minutes} Min.)", "Benachrichtigungen werden gesammelt",
                                  "alarm-symbolic", "Fokus", 50, lambda: self.hub.start_focus()))
        for facet in self.hub.facets:
            if facet["id"] != self.hub.facet_id:
                results.append(self._facet_result(facet, 40))
        return results[:9]

    # ------------------------------------------------------------ Apps
    def _app_result(self, app, score: float) -> Result:
        def launch():
            if app.launch():
                self.hub.frecency.record(f"app:{app.id}")

        windows = self.hub.windows.for_app(app)
        subtitle = app.generic or app.description or ""
        if windows:
            subtitle = f"Läuft · {subtitle}" if subtitle else "Läuft"
        return Result(app.name, subtitle, app.icon, "App", score, launch, key=f"app:{app.id}")

    def _apps(self, query: str) -> list[Result]:
        results = []
        for app in self.hub.apps.apps.values():
            score = fuzzy.best(query, app.name, app.generic, " ".join(app.keywords), app.executable,
                               weights=(1.0, 0.75, 0.7, 0.6))
            if score > 45:
                results.append(self._app_result(app, score))
                if score >= 150:
                    for action, title in app.actions()[:3]:
                        results.append(Result(f"{app.name}: {title}", "App-Aktion", app.icon, "Aktion",
                                              score - 40, lambda a=app, ac=action: a.launch_action(ac)))
        return results

    # ------------------------------------------------------------ Rechnen
    def _calc(self, query: str, forced: bool = False) -> list[Result]:
        if not (forced or calc.looks_like_math(query)):
            return []
        try:
            value = calc.calculate(query)
        except calc.CalcError as exc:
            return [Result("…", f"Ungültig: {exc}", "accessories-calculator-symbolic", "Rechner", 300)] if forced else []
        text = calc.format_number(value)
        plain = calc.format_number(value, decimal_comma=False).replace(",", "")
        return [Result(f"= {text}", f"{query.strip().lstrip('=').strip()}  ·  Enter kopiert das Ergebnis",
                       "accessories-calculator-symbolic", "Rechner", 300,
                       lambda: (copy_text(plain), self.hub.emit("toast", "edit-copy-symbolic", f"{text} kopiert")),
                       big=True)]

    def _units(self, query: str) -> list[Result]:
        converted = units.convert(query)
        if converted is None:
            return []
        value, src, result, dst = converted
        text = f"{calc.format_number(round(result, 6))} {dst}"
        plain = f"{round(result, 6)}"
        return [Result(f"= {text}", f"{calc.format_number(value)} {src}  ·  Enter kopiert",
                       "accessories-calculator-symbolic", "Einheiten", 290,
                       lambda: (copy_text(plain), self.hub.emit("toast", "edit-copy-symbolic", f"{text} kopiert")),
                       big=True)]

    # ------------------------------------------------------------ Facetten & Fenster
    def _facet_result(self, facet: dict, score: float) -> Result:
        index = self.hub.facet_index(facet["id"]) + 1
        count = len(self.hub.windows.in_facet(facet["id"]))
        subtitle = f"Super+{index}  ·  {count} Fenster" if count else f"Super+{index}"
        return Result(f"Zu „{facet['name']}“ wechseln", subtitle, None, "Facette", score,
                      lambda f=facet: self.hub.switch_facet(f["id"]), key=f"facet:{facet['id']}",
                      extra={"facet": facet})

    def _facets(self, query: str, forced: bool = False) -> list[Result]:
        results = []
        active = self.hub.windows.active()
        for facet in self.hub.facets:
            score = fuzzy.best(query, facet["name"], f"facette {facet['name']}") if query else 100
            if score > (40 if forced else 110) and facet["id"] != self.hub.facet_id:
                results.append(self._facet_result(facet, score + 20))
            if forced and active is not None and facet["id"] != self.hub.facet_id and score > 40:
                results.append(Result(f"„{active.title[:40]}“ nach „{facet['name']}“ verschieben", "Aktives Fenster",
                                      "window-new-symbolic", "Facette", score,
                                      lambda f=facet, w=active: self.hub.windows.move_to_facet(w, f["id"])))
        return results

    def _windows(self, query: str) -> list[Result]:
        results = []
        for window in self.hub.windows.all():
            app = window.extra.get("app")
            score = fuzzy.best(query, window.title, app.name if app else window.app_id, weights=(0.9, 0.85))
            if score > 70:
                facet = self.hub.facet_by_id(self.hub.windows.facet_of(window) or "") or {}
                results.append(Result(window.title or window.app_id, f"Fenster in „{facet.get('name', '?')}“",
                                      app.icon if app else window.app_id, "Fenster", score - 15,
                                      lambda w=window: self.hub.windows.activate(w)))
        return results

    # ------------------------------------------------------------ Aktionen
    def _action_list(self, query: str) -> list[tuple[str, str, str, Callable, str]]:
        hub, app = self.hub, self.app
        minutes_match = re.search(r"(\d{1,3})", query)
        minutes = int(minutes_match.group(1)) if minutes_match else hub.config["focus"]["work_minutes"]
        items = [
            ("Bildschirm sperren", "sperren lock bildschirm", "system-lock-screen-symbolic", lambda: app.activate_action("lock", None), "System"),
            ("Abmelden", "abmelden logout ausloggen beenden", "system-log-out-symbolic", lambda: app.activate_action("power", GLib.Variant("s", "logout")), "System"),
            ("Bereitschaft", "bereitschaft standby suspend schlafen", "media-playback-pause-symbolic", lambda: app.activate_action("power", GLib.Variant("s", "suspend")), "System"),
            ("Neu starten", "neustart neu starten reboot restart", "system-reboot-symbolic", lambda: app.activate_action("power", GLib.Variant("s", "reboot")), "System"),
            ("Ausschalten", "ausschalten herunterfahren shutdown poweroff", "system-shutdown-symbolic", lambda: app.activate_action("power", GLib.Variant("s", "poweroff")), "System"),
            ("Bildschirmfoto", "bildschirmfoto screenshot foto aufnahme", "camera-photo-symbolic", lambda: app.activate_action("screenshot", GLib.Variant("s", "full")), "Werkzeug"),
            ("Bildschirmfoto eines Bereichs", "bildschirmfoto bereich screenshot area auswahl", "camera-photo-symbolic", lambda: app.activate_action("screenshot", GLib.Variant("s", "area")), "Werkzeug"),
            ("Nicht stören " + ("ausschalten" if hub.dnd else "einschalten"), "nicht stören dnd ruhe stumm benachrichtigungen", "notifications-disabled-symbolic", lambda: hub.set_dnd(not hub.dnd), "Einstellung"),
            ("Erscheinungsbild wechseln (Auto → Hell → Dunkel)", "dunkel hell dark light modus theme nacht tag erscheinungsbild", "weather-clear-night-symbolic", hub.cycle_mode, "Einstellung"),
            ("Benachrichtigungen löschen", "benachrichtigungen löschen clear notifications", "edit-clear-all-symbolic", hub.notifications.clear, "Aktion"),
            ("Tagesüberblick öffnen", "tag überblick statistik zeit kalender rückblick", "x-office-calendar-symbolic", lambda: app.activate_action("daypanel", None), "Prisma"),
            ("Prisma-Einstellungen", "einstellungen settings prisma konfiguration facetten anpassen", "preferences-system-symbolic", lambda: util.spawn(util.prisma_command("prisma.settings.app")), "Prisma"),
            ("Shell neu laden", "neu laden reload shell prisma", "view-refresh-symbolic", lambda: app.activate_action("reload", None), "Prisma"),
        ]
        if hub.focus.active:
            items.insert(0, ("Fokus-Session beenden", "fokus beenden stop focus pomodoro", "alarm-symbolic", hub.stop_focus, "Fokus"))
        else:
            items.insert(0, (f"Fokus-Session starten ({minutes} Min.)", "fokus focus pomodoro konzentrieren flow", "alarm-symbolic", lambda: hub.start_focus(minutes), "Fokus"))
        if self.services.nightlight.available:
            items.append(("Nachtlicht umschalten", "nachtlicht night light warm blaulicht", "night-light-symbolic", self.services.nightlight.toggle, "Einstellung"))
        return items

    def _actions(self, query: str) -> list[Result]:
        words = re.sub(r"\d+", "", query).strip() or query
        results = []
        for title, keywords, icon, callback, kind in self._action_list(query):
            # Stichworte zählen nur am Wortanfang – „ter“ soll nicht „herunterfahren“ finden.
            keyword = max(fuzzy.score(words, k) for k in keywords.split())
            score = max(fuzzy.best(words, title), keyword - 5 if keyword >= 120 else 0)
            if score > 85:
                results.append(Result(title, kind, icon, kind, score - 5, callback, key=f"action:{title}"))
        return results

    def _settings(self, query: str) -> list[Result]:
        panels = []
        if util.has("gnome-control-center"):
            for title, keywords, panel, icon in (
                ("WLAN-Einstellungen", "wlan wifi netzwerk internet", "wifi", "network-wireless-symbolic"),
                ("Bluetooth-Einstellungen", "bluetooth geräte kopfhörer", "bluetooth", "bluetooth-symbolic"),
                ("Ton-Einstellungen", "ton sound audio lautsprecher mikrofon", "sound", "audio-speakers-symbolic"),
                ("Drucker", "drucker printer drucken", "printers", "printer-symbolic"),
                ("Benutzer", "benutzer konto passwort users", "user-accounts", "system-users-symbolic"),
                ("Datum & Uhrzeit", "datum uhrzeit zeitzone time", "datetime", "preferences-system-time-symbolic"),
            ):
                panels.append((title, keywords, icon,
                               lambda p=panel: util.spawn(["env", "XDG_CURRENT_DESKTOP=GNOME", "gnome-control-center", p])))
        if util.has("wdisplays"):
            panels.append(("Bildschirme anordnen", "bildschirm monitor auflösung display", "video-display-symbolic",
                           lambda: util.spawn(["wdisplays"])))
        if util.has("nm-connection-editor"):
            panels.append(("Netzwerkverbindungen", "netzwerk vpn verbindung lan", "network-workgroup-symbolic",
                           lambda: util.spawn(["nm-connection-editor"])))
        results = []
        for title, keywords, icon, callback in panels:
            keyword = max(fuzzy.score(query, k) for k in keywords.split())
            score = max(fuzzy.best(query, title), keyword - 5 if keyword >= 120 else 0)
            if score > 80:
                results.append(Result(title, "Systemeinstellungen", icon, "Einstellung", score - 10, callback))
        return results

    # ------------------------------------------------------------ Dateien, Web, Befehle, Emoji
    def _files(self, query: str, forced: bool = False) -> list[Result]:
        if not self.hub.config["kompass"].get("index_files", True):
            return []
        self.files.ensure()
        home = os.path.expanduser("~")
        results = []
        for score, path in self.files.search(query, 8 if forced else 4):
            directory = os.path.dirname(path)
            shown = "~" + directory[len(home):] if directory.startswith(home) else directory
            results.append(Result(os.path.basename(path), shown, file_icon(path), "Datei",
                                  score if forced else min(score, 110) - 30, lambda p=path: open_path(p)))
        return results

    def _web(self, query: str, forced: bool = False) -> list[Result]:
        if not query:
            return []
        template = self.hub.config["kompass"].get("web_search") or "https://duckduckgo.com/?q={query}"
        url = template.replace("{query}", urllib.parse.quote_plus(query)).replace("{}", urllib.parse.quote_plus(query))
        looks_like_url = re.match(r"^(https?://)?[\w-]+(\.[\w-]+)+(/\S*)?$", query) and " " not in query
        results = []
        if looks_like_url:
            target = query if query.startswith("http") else f"https://{query}"
            results.append(Result(f"{query} öffnen", "Webseite", "web-browser-symbolic", "Web", 160,
                                  lambda: Gio.AppInfo.launch_default_for_uri(target, None)))
        results.append(Result(f"Im Web suchen: „{query}“", template.split("/")[2] if "//" in template else "Web",
                              "system-search-symbolic", "Web", 200 if forced else 5,
                              lambda: Gio.AppInfo.launch_default_for_uri(url, None)))
        return results

    def _command(self, command: str) -> list[Result]:
        if not command:
            return [Result("Befehl eingeben …", "z. B. „$ htop“ – läuft im Terminal oder im Hintergrund",
                           "utilities-terminal-symbolic", "Befehl", 10, None, keep_open=True)]
        configured = self.hub.config.get("terminal", "")
        return [
            Result(f"Im Terminal ausführen: {command}", " ".join(util.terminal_command(configured)),
                   "utilities-terminal-symbolic", "Befehl", 200, lambda: util.run_in_terminal(command, configured)),
            Result(f"Im Hintergrund starten: {command}", "Ohne Fenster, Ausgabe wird verworfen",
                   "system-run-symbolic", "Befehl", 190, lambda: util.spawn(["sh", "-c", command])),
        ]

    def _emoji(self, query: str) -> list[Result]:
        results = []
        for index, (char, words) in enumerate(emoji.search(query)):
            results.append(Result(f"{char}   {words.split()[0].capitalize()}", "Enter kopiert das Emoji", None, "Emoji",
                                  100 - index, lambda c=char: (copy_text(c), self.hub.emit("toast", "edit-copy-symbolic", f"{c} kopiert")),
                                  extra={"glyph": char}))
        return results
