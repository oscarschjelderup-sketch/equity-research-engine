"""Tiny on-disk cache.

Every raw API payload is cached (pickle) so a case can be re-run instantly, run
offline, and reproduced later with the exact same inputs.
"""
from __future__ import annotations

import pickle
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


class DiskCache:
    def __init__(self, root: str | Path = ".cache", ttl_hours: float = 24.0, enabled: bool = True):
        self.root = Path(root)
        self.ttl = float(ttl_hours) * 3600.0
        self.enabled = enabled
        if enabled:
            self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = "".join(c if (c.isalnum() or c in "-_.=") else "_" for c in key)
        return self.root / f"{safe}.pkl"

    def get(self, key: str) -> Any | None:
        if not self.enabled:
            return None
        path = self._path(key)
        if not path.exists():
            return None
        if self.ttl > 0 and (time.time() - path.stat().st_mtime) > self.ttl:
            return None
        try:
            with path.open("rb") as fh:
                return pickle.load(fh)
        except Exception:
            return None

    def set(self, key: str, value: Any) -> None:
        if not self.enabled:
            return
        try:
            with self._path(key).open("wb") as fh:
                pickle.dump(value, fh)
        except Exception:
            pass

    def get_or(self, key: str, producer: Callable[[], Any]) -> Any:
        hit = self.get(key)
        if hit is not None:
            return hit
        value = producer()
        if value is not None:
            self.set(key, value)
        return value
