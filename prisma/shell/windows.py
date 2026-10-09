"""Verbindet die Wayland-Fensterliste mit den Facetten."""

from __future__ import annotations

import time

from gi.repository import GLib, GObject

from ..core.policy import FacetWindowPolicy
from ..wayland.toplevel import Toplevel, ToplevelTracker, WaylandError

SUPPRESS_SECONDS = 0.8


class WindowManager(GObject.Object):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self.policy = FacetWindowPolicy()
        self._suppress_until = 0.0
        self.tracker: ToplevelTracker | None = None
        self._connect()
        hub.apps.connect("changed", lambda *_: self._rematch())

    def _connect(self) -> None:
        try:
            self.tracker = ToplevelTracker(on_added=self._added, on_changed=self._changed, on_removed=self._removed)
        except (OSError, WaylandError) as exc:
            print(f"prisma: Fensterliste nicht verfügbar ({exc}) – Dock zeigt nur angeheftete Apps")
            self.tracker = None
            return
        GLib.io_add_watch(
            self.tracker.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self._on_io
        )

    def _on_io(self, _fd, condition) -> bool:
        if self.tracker is None:
            return False
        try:
            alive = self.tracker.dispatch() and not (condition & (GLib.IO_HUP | GLib.IO_ERR))
        except WaylandError as exc:
            print(f"prisma: {exc}")
            alive = False
        if not alive:
            print("prisma: Verbindung zum Compositor verloren")
            self.tracker = None
            self.emit("changed")
        return alive

    # ----------------------------------------------------------- Ereignisse
    def _added(self, top: Toplevel) -> None:
        top.extra["app"] = self.hub.apps.for_app_id(top.app_id)
        self.policy.add(top.handle, self.hub.facet_id)
        if top.activated:
            self.policy.focused(top.handle)
        self.emit("changed")

    def _changed(self, top: Toplevel) -> None:
        if "app_id" not in top.extra or top.extra.get("app_id") != top.app_id:
            top.extra["app_id"] = top.app_id
            top.extra["app"] = self.hub.apps.for_app_id(top.app_id)
        if top.activated and not top.minimized:
            facet = self.policy.facet_of(top.handle)
            self.policy.focused(top.handle)
            # Wurde ein Fenster einer anderen Facette aktiviert (z. B. per Alt+Tab), folgt Prisma dorthin.
            if facet and facet != self.hub.facet_id and time.monotonic() > self._suppress_until:
                self.hub.switch_facet(facet)
        self.emit("changed")

    def _removed(self, top: Toplevel) -> None:
        self.policy.remove(top.handle)
        self.emit("changed")

    # -------------------------------------------------------------- Abfragen
    @property
    def available(self) -> bool:
        return self.tracker is not None and self.tracker.available

    def all(self) -> list[Toplevel]:
        if self.tracker is None:
            return []
        return [t for t in self.tracker.toplevels.values() if t.ready]

    def in_facet(self, facet_id: str | None = None) -> list[Toplevel]:
        facet_id = facet_id or self.hub.facet_id
        return [t for t in self.all() if self.policy.facet_of(t.handle) == facet_id]

    def active(self) -> Toplevel | None:
        return self.tracker.active() if self.tracker else None

    def facet_of(self, top: Toplevel) -> str | None:
        return self.policy.facet_of(top.handle)

    def for_app(self, app, facet_id: str | None = None) -> list[Toplevel]:
        if app is None:
            return []
        return [t for t in self.in_facet(facet_id) if getattr(t.extra.get("app"), "id", None) == app.id]

    def _rematch(self) -> None:
        """Nach dem Neuladen des App-Index die Zuordnung Fenster → App erneuern."""
        for top in self.all():
            top.extra["app"] = self.hub.apps.for_app_id(top.app_id)
        self.emit("changed")

    # -------------------------------------------------------------- Aktionen
    def on_facet_switch(self, old: str, new: str, activate: Toplevel | None = None) -> None:
        if self.tracker is None:
            return
        self._suppress_until = time.monotonic() + SUPPRESS_SECONDS
        by_handle = {t.handle: t for t in self.all()}
        minimized = {h: t.minimized for h, t in by_handle.items()}
        for action, handle in self.policy.switch(old, new, minimized):
            top = by_handle.get(handle)
            if top is None:
                continue
            if action == "minimize":
                self.tracker.set_minimized(top, True)
            elif action == "unminimize":
                self.tracker.set_minimized(top, False)
            elif action == "activate" and activate is None:
                self.tracker.activate(top)
        if activate is not None:
            self.tracker.activate(activate)

    def activate(self, top: Toplevel) -> None:
        if self.tracker is None:
            return
        facet = self.policy.facet_of(top.handle)
        if facet and facet != self.hub.facet_id:
            self.hub.switch_facet(facet, activate=top)
        else:
            self.tracker.activate(top)

    def minimize(self, top: Toplevel) -> None:
        if self.tracker:
            self.tracker.set_minimized(top, True)

    def close(self, top: Toplevel) -> None:
        if self.tracker:
            self.tracker.close(top)

    def toggle_maximize(self, top: Toplevel) -> None:
        if self.tracker:
            self.tracker.set_maximized(top, not top.maximized)

    def move_to_facet(self, top: Toplevel | None, facet_id: str) -> bool:
        if self.tracker is None or top is None:
            return False
        self._suppress_until = time.monotonic() + SUPPRESS_SECONDS
        for action, handle in self.policy.move(top.handle, facet_id, self.hub.facet_id):
            if action == "minimize" and handle == top.handle:
                self.tracker.set_minimized(top, True)
        self.emit("changed")
        return True
