"""Bounded persistent cache and source-health telemetry for research runs."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from backend.core.persistence import save_json_atomic, state_path


class ResearchCache:
    def __init__(self, path: str | Path | None = None, *, max_entries: int = 2000) -> None:
        self.path = Path(path) if path else Path(state_path("research_cache.json"))
        self.max_entries = max_entries

    def _read(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {"entries": {}, "sources": {}}

    def get(self, key: str, *, ttl_s: float) -> Any | None:
        data = self._read()
        item = data.get("entries", {}).get(key)
        if not item or time.time() - float(item.get("stored_at", 0)) > ttl_s:
            return None
        item["hits"] = int(item.get("hits", 0)) + 1
        save_json_atomic(self.path, data)
        return item.get("value")

    def put(self, key: str, value: Any) -> None:
        data = self._read()
        entries = data.setdefault("entries", {})
        entries[key] = {"stored_at": time.time(), "hits": 0, "value": value}
        if len(entries) > self.max_entries:
            oldest = sorted(entries, key=lambda k: entries[k].get("stored_at", 0))
            for old_key in oldest[: len(entries) - self.max_entries]:
                entries.pop(old_key, None)
        save_json_atomic(self.path, data)

    def record_source(self, name: str, *, ok: bool, duration_s: float, count: int = 0, error: str = "") -> None:
        data = self._read()
        source = data.setdefault("sources", {}).setdefault(name, {
            "calls": 0, "successes": 0, "failures": 0, "items": 0,
            "total_duration_s": 0.0, "last_error": "", "last_checked_at": 0.0,
        })
        source["calls"] += 1
        source["successes"] += int(ok)
        source["failures"] += int(not ok)
        source["items"] += int(count)
        source["total_duration_s"] = round(source["total_duration_s"] + duration_s, 4)
        source["last_error"] = error if not ok else ""
        source["last_checked_at"] = time.time()
        source["health"] = "healthy" if ok else "degraded"
        save_json_atomic(self.path, data)

    def health(self) -> dict[str, Any]:
        data = self._read()
        for source in data.get("sources", {}).values():
            calls = max(int(source.get("calls", 0)), 1)
            source["success_rate"] = round(int(source.get("successes", 0)) / calls, 4)
            source["avg_duration_s"] = round(float(source.get("total_duration_s", 0.0)) / calls, 4)
        return data.get("sources", {})
