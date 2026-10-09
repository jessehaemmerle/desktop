"""Entscheidungslogik für Facetten-Fenster und Benachrichtigungen."""

from __future__ import annotations

from dataclasses import dataclass, field

URGENCY_LOW, URGENCY_NORMAL, URGENCY_CRITICAL = 0, 1, 2


def notification_route(
    urgency: int,
    app_name: str,
    facet_policy: str,
    focus_active: bool,
    dnd: bool,
    allow_apps: tuple[str, ...] | list[str] = (),
) -> str:
    """Bestimmt, ob eine Benachrichtigung als Popup erscheint oder still gesammelt wird.

    * ``popup`` – sofort anzeigen
    * ``quiet`` – nur im Benachrichtigungszentrum (und im Fokus-Rückblick)
    """
    if urgency >= URGENCY_CRITICAL:
        return "popup"
    allowed = app_name.lower() in {a.lower() for a in allow_apps}
    if dnd:
        return "quiet"
    if focus_active and not allowed:
        return "quiet"
    if facet_policy == "silent":
        return "quiet"
    if facet_policy == "important" and not allowed:
        # „Nur Wichtiges“: kritische Meldungen (oben) und freigegebene Apps.
        return "quiet"
    return "popup"


@dataclass
class FacetWindowPolicy:
    """Ordnet Fenster Facetten zu und berechnet, was beim Wechsel passieren muss.

    Fenster anderer Facetten werden minimiert; nur Fenster, die *Prisma* versteckt hat,
    werden beim Zurückwechseln wiederhergestellt – manuell minimierte bleiben minimiert.
    """

    assignment: dict = field(default_factory=dict)  # window id -> facet id
    hidden: set = field(default_factory=set)  # von Prisma minimierte Fenster
    last_active: dict = field(default_factory=dict)  # facet id -> window id

    def add(self, window_id, facet_id: str) -> None:
        self.assignment[window_id] = facet_id

    def remove(self, window_id) -> None:
        facet = self.assignment.pop(window_id, None)
        self.hidden.discard(window_id)
        if facet is not None and self.last_active.get(facet) == window_id:
            del self.last_active[facet]

    def facet_of(self, window_id) -> str | None:
        return self.assignment.get(window_id)

    def windows_in(self, facet_id: str) -> list:
        return [w for w, f in self.assignment.items() if f == facet_id]

    def focused(self, window_id) -> None:
        facet = self.assignment.get(window_id)
        if facet is not None:
            self.last_active[facet] = window_id
            self.hidden.discard(window_id)

    def switch(self, old: str, new: str, minimized: dict) -> list[tuple[str, object]]:
        """Liefert Aktionen ('minimize'|'unminimize'|'activate', window_id)."""
        if old == new:
            return []
        actions: list[tuple[str, object]] = []
        for window in self.windows_in(old):
            if not minimized.get(window, False):
                actions.append(("minimize", window))
                self.hidden.add(window)
        for window in self.windows_in(new):
            if window in self.hidden:
                actions.append(("unminimize", window))
                self.hidden.discard(window)
        target = self.last_active.get(new)
        if target is not None and self.assignment.get(target) == new:
            restored = ("unminimize", target) in actions
            if restored or not minimized.get(target, False):
                actions.append(("activate", target))
        return actions

    def move(self, window_id, target: str, current: str) -> list[tuple[str, object]]:
        """Verschiebt ein Fenster in eine andere Facette."""
        if window_id not in self.assignment or self.assignment[window_id] == target:
            return []
        self.assignment[window_id] = target
        if self.last_active.get(current) == window_id:
            del self.last_active[current]
        self.last_active[target] = window_id
        if target != current:
            self.hidden.add(window_id)
            return [("minimize", window_id)]
        return []

    def retire_facet(self, facet_id: str, fallback: str) -> None:
        """Facette gelöscht: deren Fenster wandern in ``fallback``."""
        for window, facet in list(self.assignment.items()):
            if facet == facet_id:
                self.assignment[window] = fallback
        self.last_active.pop(facet_id, None)
