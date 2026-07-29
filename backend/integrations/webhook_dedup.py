"""Bounded in-process deduplication for retried sidecar webhook events."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict


class WebhookEventLedger:
    def __init__(self, *, max_entries: int = 10_000, ttl_s: float = 86_400.0):
        self.max_entries = max(1, max_entries)
        self.ttl_s = max(0.0, ttl_s)
        self._events: OrderedDict[str, float] = OrderedDict()
        self._lock = threading.Lock()

    def accept(self, source: str, event_id: str) -> bool:
        """Return True once for an event; repeated/expired events are rejected."""
        key = f"{source}:{event_id}".strip()
        if not event_id:
            return False
        now = time.monotonic()
        with self._lock:
            expired = [item for item, seen in self._events.items() if now - seen >= self.ttl_s]
            for item in expired:
                self._events.pop(item, None)
            if key in self._events:
                self._events.move_to_end(key)
                return False
            self._events[key] = now
            while len(self._events) > self.max_entries:
                self._events.popitem(last=False)
            return True

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
