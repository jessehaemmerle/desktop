"""Flow-Timer: Fokusphasen mit anschließender Pause – ohne GTK, mit injizierbarer Uhr."""

from __future__ import annotations

import time
from typing import Callable

IDLE, WORK, BREAK = "idle", "work", "break"


class FocusTimer:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self.phase = IDLE
        self._ends_at = 0.0
        self.duration = 0.0
        self.break_minutes = 5
        self.completed_sessions = 0

    @property
    def active(self) -> bool:
        return self.phase != IDLE

    def start(self, minutes: float, break_minutes: float = 5) -> None:
        self.phase = WORK
        self.duration = max(1.0, minutes * 60.0)
        self._ends_at = self._clock() + self.duration
        self.break_minutes = break_minutes

    def stop(self) -> None:
        self.phase = IDLE
        self._ends_at = 0.0
        self.duration = 0.0

    def remaining(self) -> float:
        if not self.active:
            return 0.0
        return max(0.0, self._ends_at - self._clock())

    def progress(self) -> float:
        if not self.active or self.duration <= 0:
            return 0.0
        return 1.0 - self.remaining() / self.duration

    def tick(self) -> str | None:
        """Prüft auf Phasenwechsel. Gibt 'work-done' oder 'break-done' zurück, sonst None."""
        if not self.active or self.remaining() > 0:
            return None
        if self.phase == WORK:
            self.completed_sessions += 1
            if self.break_minutes > 0:
                self.phase = BREAK
                self.duration = self.break_minutes * 60.0
                self._ends_at = self._clock() + self.duration
            else:
                self.stop()
            return "work-done"
        self.stop()
        return "break-done"

    def label(self) -> str:
        rem = int(round(self.remaining()))
        return f"{rem // 60:02d}:{rem % 60:02d}"
