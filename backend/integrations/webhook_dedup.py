"""Bounded in-process deduplication for retried sidecar webhook events."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
import sqlite3


class WebhookEventLedger:
    def __init__(self, *, max_entries: int = 10_000, ttl_s: float = 86_400.0, db_path: str = ":memory:"):
        self.max_entries = max(1, max_entries)
        self.ttl_s = max(0.0, ttl_s)
        self._events: OrderedDict[str, float] = OrderedDict()
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS webhook_events (event_key TEXT PRIMARY KEY, seen_at REAL NOT NULL)")
        self._db.commit()

    def accept(self, source: str, event_id: str) -> bool:
        """Return True once for an event; repeated/expired events are rejected."""
        key = f"{source}:{event_id}".strip()
        if not event_id:
            return False
        # Persist wall-clock timestamps. ``monotonic()`` is only meaningful
        # inside one process and would make durable deduplication incorrect
        # after a restart.
        now = time.time()
        with self._lock:
            row = self._db.execute("SELECT seen_at FROM webhook_events WHERE event_key = ?", (key,)).fetchone()
            if row is not None and now - float(row[0]) < self.ttl_s:
                return False
            self._db.execute("DELETE FROM webhook_events WHERE seen_at <= ?", (now - self.ttl_s,))
            self._db.execute("INSERT OR REPLACE INTO webhook_events(event_key, seen_at) VALUES (?, ?)", (key, now))
            self._db.commit()
            expired = [item for item, seen in self._events.items() if now - seen >= self.ttl_s]
            for item in expired:
                self._events.pop(item, None)
            if key in self._events:
                self._events.move_to_end(key)
                return False
            self._events[key] = now
            while len(self._events) > self.max_entries:
                self._events.popitem(last=False)
            self._db.execute("DELETE FROM webhook_events WHERE event_key NOT IN (SELECT event_key FROM webhook_events ORDER BY seen_at DESC LIMIT ?)", (self.max_entries,))
            self._db.commit()
            return True

    def release(self, source: str, event_id: str) -> None:
        """Allow a failed delivery to be retried by the upstream sender."""
        key = f"{source}:{event_id}".strip()
        if not event_id:
            return
        with self._lock:
            self._events.pop(key, None)
            self._db.execute("DELETE FROM webhook_events WHERE event_key = ?", (key,))
            self._db.commit()

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._db.execute("DELETE FROM webhook_events")
            self._db.commit()
