"""Zentraler Zustand der Shell: Konfiguration, Facetten, Fokus, Theme – mit GObject-Signalen."""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime

from gi.repository import Gio, GLib, GObject

from ..core import config as cfg
from ..core import schedule
from ..core.focus import BREAK, WORK, FocusTimer
from ..core.frecency import Frecency
from .apps import AppIndex
from .styling import Styling

STATS_DAYS = 14


class Hub(GObject.Object):
    __gsignals__ = {
        "config-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "theme-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "facet-changed": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
        "focus-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "dnd-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "toast": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
    }

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.config = cfg.load()
        self.apps = AppIndex()
        state_dir = cfg.state_dir()
        self.frecency = Frecency(state_dir / "frecency.json")
        self._state_path = state_dir / "state.json"
        self._state = self._load_state()
        saved = cfg.find_facet(self.config, self._state.get("facet", ""))
        self.facet_id = saved["id"] if saved else self.config["facets"][0]["id"]
        self.dnd = bool(self._state.get("dnd", False))
        self.focus = FocusTimer()
        self._focus_source = 0
        self.dark = self._compute_dark()
        self._rule_facet = schedule.facet_for_time(self.config["rules"], datetime.now())
        self._last_tick = time.monotonic()
        self.styling = Styling(self)
        self.styling.apply()

        # Diese Dienste brauchen den Hub und werden danach angelegt.
        from .notifications import NotificationStore
        from .windows import WindowManager

        self.notifications = NotificationStore(self)
        self.windows = WindowManager(self)

        GLib.timeout_add_seconds(30, self._periodic)
        self._watch_config()

    # ------------------------------------------------------------ Facetten
    @property
    def facets(self) -> list[dict]:
        return self.config["facets"]

    @property
    def facet(self) -> dict:
        return self.facet_by_id(self.facet_id) or self.facets[0]

    def facet_by_id(self, facet_id: str) -> dict | None:
        return next((f for f in self.facets if f["id"] == facet_id), None)

    def facet_index(self, facet_id: str | None = None) -> int:
        facet_id = facet_id or self.facet_id
        return next((i for i, f in enumerate(self.facets) if f["id"] == facet_id), 0)

    def switch_facet(self, key, activate=None) -> None:
        facet = cfg.find_facet(self.config, key) if not isinstance(key, dict) else key
        if facet is None:
            self.emit("toast", "dialog-warning-symbolic", f"Facette „{key}“ gibt es nicht")
            return
        old = self.facet_id
        if facet["id"] == old:
            if activate is not None:
                self.windows.activate(activate)
            return
        self._account_time()
        self.facet_id = facet["id"]
        self.windows.on_facet_switch(old, facet["id"], activate)
        self.styling.apply()
        self.emit("theme-changed")
        self.emit("facet-changed", old, facet["id"])
        self._state["facet"] = facet["id"]
        self._save_state()

    def cycle_facet(self, delta: int) -> None:
        index = (self.facet_index() + delta) % len(self.facets)
        self.switch_facet(self.facets[index])

    # ------------------------------------------------------------- Theme
    def _compute_dark(self) -> bool:
        a = self.config["appearance"]
        return schedule.is_dark(a.get("mode", "auto"), datetime.now(), a.get("light_from", "07:00"), a.get("dark_from", "19:00"))

    def set_mode(self, mode: str) -> None:
        self.config["appearance"]["mode"] = mode
        cfg.save(self.config)  # Dateibeobachter ruft reload_config auf
        self._refresh_theme()
        labels = {"auto": "Automatisch (Tageslicht)", "light": "Hell", "dark": "Dunkel"}
        self.emit("toast", "weather-clear-night-symbolic" if self.dark else "weather-clear-symbolic",
                  f"Erscheinungsbild: {labels.get(mode, mode)}")

    def cycle_mode(self) -> None:
        order = ["auto", "light", "dark"]
        current = self.config["appearance"].get("mode", "auto")
        self.set_mode(order[(order.index(current) + 1) % 3] if current in order else "auto")

    def _refresh_theme(self, force: bool = False) -> None:
        dark = self._compute_dark()
        if force or dark != self.dark:
            self.dark = dark
            self.styling.apply()
            self.emit("theme-changed")

    # ------------------------------------------------------------- Fokus
    def start_focus(self, minutes: float | None = None) -> None:
        f = self.config["focus"]
        self.focus.start(minutes or f["work_minutes"], f["break_minutes"])
        self.notifications.begin_focus()
        if not self._focus_source:
            self._focus_source = GLib.timeout_add_seconds(1, self._focus_tick)
        self.emit("toast", "alarm-symbolic", f"Fokus für {int(minutes or f['work_minutes'])} Minuten – Benachrichtigungen pausiert")
        self.emit("focus-changed")

    def stop_focus(self) -> None:
        was_work = self.focus.phase == WORK
        self.focus.stop()
        if was_work:
            self.notifications.end_focus(completed=False)
        self.emit("focus-changed")

    def toggle_focus(self, minutes: float | None = None) -> None:
        if self.focus.active:
            self.stop_focus()
        else:
            self.start_focus(minutes)

    def _focus_tick(self) -> bool:
        event = self.focus.tick()
        if event == "work-done":
            self.notifications.end_focus(completed=True)
        elif event == "break-done":
            self.notifications.post_internal("Pause vorbei", "Bereit für die nächste Fokus-Runde?", "alarm-symbolic")
        self.emit("focus-changed")
        if not self.focus.active:
            self._focus_source = 0
            return False
        return True

    @property
    def in_focus(self) -> bool:
        return self.focus.phase == WORK

    @property
    def on_break(self) -> bool:
        return self.focus.phase == BREAK

    # --------------------------------------------------------- Nicht stören
    def set_dnd(self, value: bool) -> None:
        self.dnd = bool(value)
        self._state["dnd"] = self.dnd
        self._save_state()
        self.emit("dnd-changed")
        self.emit("toast", "notifications-disabled-symbolic" if self.dnd else "preferences-system-notifications-symbolic",
                  "Nicht stören aktiv" if self.dnd else "Benachrichtigungen aktiv")

    # ------------------------------------------------------------ Statistik
    def _account_time(self) -> None:
        now = time.monotonic()
        elapsed = min(now - self._last_tick, 120.0)  # Standby nicht mitzählen
        self._last_tick = now
        today = date.today().isoformat()
        stats = self._state.setdefault("stats", {})
        day = stats.setdefault(today, {})
        day[self.facet_id] = day.get(self.facet_id, 0.0) + elapsed
        for old in sorted(stats)[:-STATS_DAYS]:
            del stats[old]

    def stats_today(self) -> dict:
        self._account_time()
        return dict(self._state.get("stats", {}).get(date.today().isoformat(), {}))

    # ------------------------------------------------------------ Zyklus
    def _periodic(self) -> bool:
        self._account_time()
        self._refresh_theme()
        if self.config.get("auto_switch"):
            wanted = schedule.facet_for_time(self.config["rules"], datetime.now())
            # flankengesteuert: nur beim Wechsel der Regel umschalten, manuelle Wahl bleibt sonst bestehen
            if wanted != self._rule_facet:
                self._rule_facet = wanted
                if wanted and wanted != self.facet_id and self.facet_by_id(wanted):
                    self.switch_facet(wanted)
                    self.emit("toast", self.facet.get("icon", "view-grid-symbolic"),
                              f"Automatisch zu „{self.facet['name']}“ gewechselt")
        self._save_state()
        return True

    # ------------------------------------------------------------ Konfiguration
    def _watch_config(self) -> None:
        path = cfg.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._config_monitor = Gio.File.new_for_path(str(path.parent)).monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self._reload_pending = 0

        def changed(_monitor, file, _other, _event):
            if file.get_basename() != "config.json":
                return
            if self._reload_pending:
                GLib.source_remove(self._reload_pending)
            self._reload_pending = GLib.timeout_add(200, self._reload_from_disk)

        self._config_monitor.connect("changed", changed)

    def _reload_from_disk(self) -> bool:
        self._reload_pending = 0
        self.reload_config()
        return False

    def reload_config(self) -> None:
        new = cfg.load()
        if new == self.config:
            return
        old_ids = {f["id"] for f in self.facets}
        self.config = new
        new_ids = {f["id"] for f in self.facets}
        for gone in old_ids - new_ids:
            self.windows.policy.retire_facet(gone, self.facets[0]["id"])
        if self.facet_id not in new_ids:
            self.facet_id = self.facets[0]["id"]
        self.dark = self._compute_dark()
        self.styling.apply()
        self.emit("config-changed")
        self.emit("theme-changed")

    # ------------------------------------------------------------ Persistenz
    def _load_state(self) -> dict:
        try:
            with open(self._state_path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_state(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._state, fh)
            os.replace(tmp, self._state_path)
        except OSError:
            pass

    def shutdown(self) -> None:
        self._account_time()
        self._save_state()

    def user_name(self) -> str:
        name = self.config.get("user_name") or GLib.get_real_name() or GLib.get_user_name()
        if not name or name == "Unknown":
            name = GLib.get_user_name()
        return name.split()[0] if name else ""
