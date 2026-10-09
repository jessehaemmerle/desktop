"""Lernende Reihenfolge: häufig *und* kürzlich genutzte Einträge steigen im Kompass auf."""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

HALF_LIFE_DAYS = 7.0
MAX_HITS = 30


class Frecency:
    def __init__(self, path: Path | None, clock=time.time):
        self.path = path
        self.clock = clock
        self.data: dict[str, list[float]] = {}
        if path is not None:
            try:
                with open(path, encoding="utf-8") as fh:
                    raw = json.load(fh)
                self.data = {k: [float(x) for x in v][-MAX_HITS:] for k, v in raw.items() if isinstance(v, list)}
            except (OSError, ValueError, TypeError, AttributeError):
                self.data = {}

    def record(self, key: str) -> None:
        hits = self.data.setdefault(key, [])
        hits.append(self.clock())
        del hits[:-MAX_HITS]
        self.save()

    def score(self, key: str) -> float:
        now = self.clock()
        decay = math.log(2) / (HALF_LIFE_DAYS * 86400.0)
        return sum(math.exp(-decay * max(0.0, now - t)) for t in self.data.get(key, ()))

    def top(self, limit: int = 8) -> list[str]:
        ranked = sorted(self.data, key=self.score, reverse=True)
        return [k for k in ranked if self.score(k) > 0.05][:limit]

    def save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh)
            os.replace(tmp, self.path)
        except OSError:
            pass
