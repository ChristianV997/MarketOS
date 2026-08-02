import json
import logging
import math
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

VALID_INTENTS = {"buy", "research", "compare", "unknown"}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS research_records (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    intent TEXT NOT NULL,
    velocity REAL NOT NULL,
    competition REAL NOT NULL,
    source TEXT NOT NULL,
    freshness_ts TEXT NOT NULL,
    confidence REAL NOT NULL,
    raw TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    dedupe_key TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_research_velocity ON research_records (velocity DESC);
CREATE INDEX IF NOT EXISTS idx_research_confidence ON research_records (confidence DESC);
CREATE INDEX IF NOT EXISTS idx_research_freshness_ts ON research_records (freshness_ts DESC);
CREATE INDEX IF NOT EXISTS idx_research_rank ON research_records (velocity DESC, confidence DESC, freshness_ts DESC, id ASC);
"""


class ResearchValidationError(ValueError):
    def __init__(self, errors: list[dict[str, Any]]):
        super().__init__("invalid research record")
        self.errors = errors


class ResearchMetrics:
    def __init__(self):
        self.counters = {"research_dedupe_hits_total": 0}

    def record_dedupe_hit(self) -> None:
        self.counters["research_dedupe_hits_total"] += 1


def generate_dedupe_key(source: str, topic: str, freshness_ts: str) -> str:
    hour = _parse_iso_timestamp(freshness_ts).strftime("%Y-%m-%d-%H")
    normalized_topic = str(topic).strip().lower()
    return f"{source}:{normalized_topic}:{hour}"


def _parse_iso_timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise ResearchValidationError([{"field": "freshness_ts", "error": "invalid_iso_timestamp", "value": value}]) from err


def validate_research_record(record: dict[str, Any]) -> None:
    errors = []
    required_fields = ("topic", "intent", "velocity", "competition", "source", "freshness_ts", "confidence", "raw")
    for field in required_fields:
        if field not in record:
            errors.append({"field": field, "error": "missing"})

    if "topic" in record and (not isinstance(record["topic"], str) or not record["topic"].strip()):
        errors.append({"field": "topic", "error": "invalid_type_or_empty", "expected": "non-empty string"})

    if "intent" in record and record["intent"] not in VALID_INTENTS:
        errors.append({"field": "intent", "error": "invalid_enum", "allowed": sorted(VALID_INTENTS)})

    for numeric_field in ("velocity", "competition", "confidence"):
        if numeric_field in record and (
            isinstance(record[numeric_field], bool)
            or not isinstance(record[numeric_field], (int, float))
        ):
            errors.append({"field": numeric_field, "error": "invalid_type", "expected": "float"})
        elif numeric_field in record and not math.isfinite(float(record[numeric_field])):
            errors.append({"field": numeric_field, "error": "non_finite", "expected": "finite float"})

    if isinstance(record.get("competition"), (int, float)) and not 0.0 <= float(record["competition"]) <= 1.0:
        errors.append({"field": "competition", "error": "out_of_range", "expected": "[0,1]"})

    if isinstance(record.get("confidence"), (int, float)) and not 0.0 <= float(record["confidence"]) <= 1.0:
        errors.append({"field": "confidence", "error": "out_of_range", "expected": "[0,1]"})

    freshness_ts = record.get("freshness_ts")
    if freshness_ts is not None:
        if not isinstance(freshness_ts, str):
            errors.append({"field": "freshness_ts", "error": "invalid_type", "expected": "ISO timestamp"})
        else:
            try:
                _parse_iso_timestamp(freshness_ts)
            except ResearchValidationError:
                errors.append({"field": "freshness_ts", "error": "invalid_iso_timestamp"})

    if "raw" in record and not isinstance(record["raw"], dict):
        errors.append({"field": "raw", "error": "invalid_type", "expected": "json object"})

    if errors:
        raise ResearchValidationError(errors)


class TrendRecordStore:
    def __init__(
        self,
        path: str = "backend/state/research.db",
        *,
        retention_days: int | None = None,
        metrics: ResearchMetrics | None = None,
    ):
        self.path = path
        self.retention_days = self._retention_days(retention_days)
        self.metrics = metrics or ResearchMetrics()
        self._ensure_schema()

    def _retention_days(self, value: int | None) -> int:
        try:
            if value is not None:
                return max(1, int(value))
            return max(1, int(os.getenv("RESEARCH_RETENTION_DAYS", "30")))
        except (TypeError, ValueError):
            return 30

    def _connect(self) -> sqlite3.Connection:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def _row_to_record(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["raw"] = json.loads(item["raw"])
        return item

    def _payload_to_record(self, payload: dict[str, Any]) -> dict[str, Any]:
        item = dict(payload)
        item["raw"] = json.loads(item["raw"])
        return item

    def _serialize(self, record: dict[str, Any]) -> dict[str, Any]:
        validate_research_record(record)
        freshness_ts = record["freshness_ts"]
        dedupe_key = record.get("dedupe_key") or generate_dedupe_key(record["source"], record["topic"], freshness_ts)
        now = datetime.now(timezone.utc).isoformat()
        return {
            "id": record.get("id") or str(uuid.uuid4()),
            "topic": str(record["topic"]).strip(),
            "intent": record["intent"],
            "velocity": float(record["velocity"]),
            "competition": float(record["competition"]),
            "source": str(record["source"]).strip(),
            "freshness_ts": freshness_ts,
            "confidence": float(record["confidence"]),
            "raw": json.dumps(record["raw"], ensure_ascii=False),
            "created_at": record.get("created_at") or now,
            "updated_at": now,
            "dedupe_key": dedupe_key,
        }

    def insert(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = self._serialize(record)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO research_records (
                    id, topic, intent, velocity, competition, source, freshness_ts,
                    confidence, raw, created_at, updated_at, dedupe_key
                ) VALUES (
                    :id, :topic, :intent, :velocity, :competition, :source, :freshness_ts,
                    :confidence, :raw, :created_at, :updated_at, :dedupe_key
                )
                """,
                payload,
            )
        return self._payload_to_record(payload)

    def upsert(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = self._serialize(record)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id, created_at FROM research_records WHERE dedupe_key = ?",
                (payload["dedupe_key"],),
            ).fetchone()
            if existing:
                payload["id"] = existing["id"]
                payload["created_at"] = existing["created_at"]
                conn.execute(
                    """
                    UPDATE research_records
                    SET topic = :topic,
                        intent = :intent,
                        velocity = :velocity,
                        competition = :competition,
                        source = :source,
                        freshness_ts = :freshness_ts,
                        confidence = :confidence,
                        raw = :raw,
                        updated_at = :updated_at
                    WHERE dedupe_key = :dedupe_key
                    """,
                    payload,
                )
                self.metrics.record_dedupe_hit()
            else:
                conn.execute(
                    """
                    INSERT INTO research_records (
                        id, topic, intent, velocity, competition, source, freshness_ts,
                        confidence, raw, created_at, updated_at, dedupe_key
                    ) VALUES (
                        :id, :topic, :intent, :velocity, :competition, :source, :freshness_ts,
                        :confidence, :raw, :created_at, :updated_at, :dedupe_key
                    )
                    """,
                    payload,
                )
            row = conn.execute("SELECT * FROM research_records WHERE dedupe_key = ?", (payload["dedupe_key"],)).fetchone()
        return self._row_to_record(row) or {}

    def findById(self, record_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM research_records WHERE id = ?", (record_id,)).fetchone()
        return self._row_to_record(row)

    def findTopN(self, n: int) -> list[dict[str, Any]]:
        limit = int(n)
        if limit <= 0:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM research_records
                ORDER BY velocity DESC, confidence DESC, freshness_ts DESC, id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def findBySource(self, source: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM research_records
                WHERE source = ?
                ORDER BY freshness_ts DESC
                """,
                (source,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def deleteOlderThan(self, iso_timestamp: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM research_records WHERE freshness_ts < ?", (iso_timestamp,))
            return int(cursor.rowcount or 0)

    def pruneOldRecords(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=self.retention_days)).isoformat()
        return self.deleteOlderThan(cutoff)

    def append_many(self, records: list[dict[str, Any]]) -> int:
        persisted = 0
        for record in records:
            try:
                self.upsert(record)
                persisted += 1
            except ResearchValidationError as err:
                logger.error(
                    "Research record rejected",
                    extra={"event": "research_record_rejected", "errors": err.errors, "source": record.get("source")},
                )
        return persisted
