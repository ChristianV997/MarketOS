"""Small local cache for public signal observations; no network behavior."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


class PublicSignalCache:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def _path(self, source: str, query: str) -> Path:
        digest = hashlib.sha256(f"{source}:{query.strip().lower()}".encode("utf-8")).hexdigest()[:20]
        return self.directory / f"{source}-{digest}.json"

    def load(self, source: str, query: str) -> dict[str, Any] | None:
        try:
            payload = json.loads(self._path(source, query).read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def save(self, source: str, query: str, signals: list[dict[str, Any]], source_url: str, *, saved_at: float | None = None) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self._path(source, query)
        temporary = target.with_suffix(".tmp")
        payload = {"saved_at": float(time.time() if saved_at is None else saved_at), "source_url": source_url, "signals": signals}
        temporary.write_text(json.dumps(payload, sort_keys=True, ensure_ascii=False), encoding="utf-8")
        temporary.replace(target)

    def readiness(self, source: str, query: str = "") -> dict[str, Any]:
        cached = self.load(source, query)
        return {
            "cache_available": cached is not None,
            "last_success": cached.get("saved_at") if cached else None,
            "cached_signal_count": len(cached.get("signals", [])) if cached else 0,
        }
