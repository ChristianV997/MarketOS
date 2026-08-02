"""Durable run history for the market-research ingestion scheduler."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any


class IngestionRunStore:
    def __init__(self, path: str = "backend/state/research.db") -> None:
        self.path = path
        self._ensure_schema()

    @contextmanager
    def _connect(self):
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        else:
            conn.commit()
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS research_ingestion_runs (
                    run_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    idempotency_key TEXT,
                    window TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_research_ingestion_ended "
                "ON research_ingestion_runs (ended_at DESC)"
            )

    def append(self, result: dict[str, Any], *, window: str, idempotency_key: str | None = None) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "run_id": str(uuid.uuid4()),
            "started_at": str(result.get("startedAt") or now),
            "ended_at": str(result.get("endedAt") or now),
            "status": str(result.get("status", "unknown")),
            "idempotency_key": idempotency_key,
            "window": window,
            "payload": result,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO research_ingestion_runs
                (run_id, started_at, ended_at, status, idempotency_key, window, payload)
                VALUES (:run_id, :started_at, :ended_at, :status, :idempotency_key, :window, :payload)
                """,
                {**record, "payload": json.dumps(result, ensure_ascii=False, allow_nan=False)},
            )
        return record

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM research_ingestion_runs ORDER BY ended_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._decode(row) for row in rows]

    def latest(self) -> dict[str, Any] | None:
        rows = self.list(1)
        return rows[0] if rows else None

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["payload"] = json.loads(item["payload"])
        return item
