import json
import logging
import math
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.research.topic_intelligence import normalize_topic, summarize_opportunity

logger = logging.getLogger(__name__)

VALID_INTENTS = {"buy", "research", "compare", "unknown"}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS research_records (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    topic_key TEXT NOT NULL,
    intent TEXT NOT NULL,
    velocity REAL NOT NULL,
    competition REAL,
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
CREATE INDEX IF NOT EXISTS idx_research_topic_key ON research_records (topic_key, freshness_ts DESC);
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

    for numeric_field in ("velocity", "confidence"):
        if numeric_field in record and (
            isinstance(record[numeric_field], bool)
            or not isinstance(record[numeric_field], (int, float))
        ):
            errors.append({"field": numeric_field, "error": "invalid_type", "expected": "float"})
        elif numeric_field in record and not math.isfinite(float(record[numeric_field])):
            errors.append({"field": numeric_field, "error": "non_finite", "expected": "finite float"})

    competition = record.get("competition")
    if competition is not None:
        if isinstance(competition, bool) or not isinstance(competition, (int, float)):
            errors.append({"field": "competition", "error": "invalid_type", "expected": "finite float or null"})
        elif not math.isfinite(float(competition)):
            errors.append({"field": "competition", "error": "non_finite", "expected": "finite float or null"})
    if isinstance(competition, (int, float)) and not 0.0 <= float(competition) <= 1.0:
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

    @contextmanager
    def _connect(self):
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
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
            conn.execute("PRAGMA journal_mode = WAL")
            table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'research_records'"
            ).fetchone()
            if table is None:
                conn.executescript(SCHEMA_SQL)
                return

            columns = {row[1]: row for row in conn.execute("PRAGMA table_info(research_records)")}
            competition = columns.get("competition")
            topic_key_needs_backfill = (
                "topic_key" not in columns
                or columns.get("topic_key", (None, None, None, 0))[3] != 1
            )
            rebuilt_for_nullable_competition = False
            if competition is not None and competition[3] == 1:
                # SQLite cannot alter a NOT NULL column in place. Rebuild the
                # local table while preserving all existing records.
                conn.executescript(
                    """
                    DROP INDEX IF EXISTS idx_research_velocity;
                    DROP INDEX IF EXISTS idx_research_confidence;
                    DROP INDEX IF EXISTS idx_research_freshness_ts;
                    DROP INDEX IF EXISTS idx_research_rank;
                    DROP INDEX IF EXISTS idx_research_topic_key;
                    ALTER TABLE research_records RENAME TO research_records_legacy;
                    """
                )
                conn.executescript(SCHEMA_SQL)
                conn.execute(
                    """
                    INSERT INTO research_records
                    (id, topic, topic_key, intent, velocity, competition, source, freshness_ts,
                     confidence, raw, created_at, updated_at, dedupe_key)
                    SELECT id, topic, lower(trim(topic)), intent, velocity, competition, source, freshness_ts,
                           confidence, raw, created_at, updated_at, dedupe_key
                    FROM research_records_legacy
                    """
                )
                conn.execute("DROP TABLE research_records_legacy")
                topic_key_needs_backfill = True
                rebuilt_for_nullable_competition = True
            if "topic_key" not in columns and not rebuilt_for_nullable_competition:
                conn.execute("ALTER TABLE research_records ADD COLUMN topic_key TEXT")
            if topic_key_needs_backfill:
                rows = conn.execute("SELECT id, topic FROM research_records").fetchall()
                conn.executemany(
                    "UPDATE research_records SET topic_key = ? WHERE id = ?",
                    [(normalize_topic(row["topic"]), row["id"]) for row in rows],
                )
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
            "topic_key": normalize_topic(str(record["topic"])),
            "intent": record["intent"],
            "velocity": float(record["velocity"]),
            "competition": None if record["competition"] is None else float(record["competition"]),
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
                    id, topic, topic_key, intent, velocity, competition, source, freshness_ts,
                    confidence, raw, created_at, updated_at, dedupe_key
                ) VALUES (
                    :id, :topic, :topic_key, :intent, :velocity, :competition, :source, :freshness_ts,
                    :confidence, :raw, :created_at, :updated_at, :dedupe_key
                )
                """,
                payload,
            )
        return self._payload_to_record(payload)

    def upsert(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = self._serialize(record)
        with self._connect() as conn:
            row = self._upsert_payload(conn, payload)
        return self._row_to_record(row) or {}

    def _upsert_payload(self, conn: sqlite3.Connection, payload: dict[str, Any]) -> sqlite3.Row | None:
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
                    topic_key = :topic_key,
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
                    id, topic, topic_key, intent, velocity, competition, source, freshness_ts,
                    confidence, raw, created_at, updated_at, dedupe_key
                ) VALUES (
                    :id, :topic, :topic_key, :intent, :velocity, :competition, :source, :freshness_ts,
                    :confidence, :raw, :created_at, :updated_at, :dedupe_key
                )
                """,
                payload,
            )
        return conn.execute(
            "SELECT * FROM research_records WHERE dedupe_key = ?", (payload["dedupe_key"],)
        ).fetchone()

    def findById(self, record_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM research_records WHERE id = ?", (record_id,)).fetchone()
        return self._row_to_record(row)

    def findTopN(self, n: int, *, require_competition: bool = False) -> list[dict[str, Any]]:
        limit = int(n)
        if limit <= 0:
            return []
        with self._connect() as conn:
            filter_sql = "WHERE competition IS NOT NULL" if require_competition else ""
            rows = conn.execute(
                f"""
                SELECT * FROM research_records
                {filter_sql}
                ORDER BY velocity DESC, confidence DESC, freshness_ts DESC, id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def find_opportunities(
        self,
        n: int,
        *,
        max_age_hours: float | None = None,
        min_sources: int = 1,
        intent: str | None = None,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Return corroborated, freshness-aware opportunities across sources."""
        limit = int(n)
        if limit <= 0:
            return []
        source_floor = max(1, int(min_sources))
        if intent is not None and intent not in VALID_INTENTS:
            raise ValueError(f"unsupported intent: {intent}")
        now = now or datetime.now(timezone.utc)
        filters: list[str] = []
        parameters: list[Any] = []
        if max_age_hours is not None:
            age = max(0.0, float(max_age_hours))
            filters.append("freshness_ts >= ?")
            parameters.append((now - timedelta(hours=age)).isoformat())
        if intent is not None:
            filters.append("intent = ?")
            parameters.append(intent)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                WITH filtered AS (
                    SELECT * FROM research_records
                    {where}
                ), grouped AS (
                    SELECT
                        topic_key,
                        COUNT(*) AS record_count,
                        COUNT(DISTINCT source) AS source_count,
                        GROUP_CONCAT(DISTINCT source) AS sources,
                        MAX(velocity) AS velocity,
                        AVG(confidence) AS confidence,
                        AVG(competition) AS competition,
                        AVG(CASE WHEN competition IS NULL THEN 0.0 ELSE 1.0 END) AS competition_coverage,
                        MAX(freshness_ts) AS freshness_ts
                    FROM filtered
                    GROUP BY topic_key
                    HAVING COUNT(DISTINCT source) >= ?
                )
                SELECT
                    grouped.*,
                    (SELECT topic FROM filtered f WHERE f.topic_key = grouped.topic_key
                     ORDER BY freshness_ts DESC, lower(topic) ASC, topic ASC, id ASC LIMIT 1) AS topic,
                    (SELECT intent FROM filtered f WHERE f.topic_key = grouped.topic_key
                     ORDER BY freshness_ts DESC, lower(topic) ASC, topic ASC, id ASC LIMIT 1) AS intent
                FROM grouped
                """,
                [*parameters, source_floor],
            ).fetchall()
        half_life = self._freshness_half_life_hours()
        opportunities = [
            summarize_opportunity(dict(row), now=now, freshness_half_life_hours=half_life)
            for row in rows
        ]
        return sorted(
            opportunities,
            key=lambda item: (-item["rank_score"], -item["source_count"], item["topic_key"]),
        )[:limit]

    def source_summary(self, *, max_age_hours: float | None = None, now: datetime | None = None) -> list[dict[str, Any]]:
        """Return per-source coverage and freshness diagnostics for operators."""
        now = now or datetime.now(timezone.utc)
        parameters: list[Any] = []
        where = ""
        if max_age_hours is not None:
            where = "WHERE freshness_ts >= ?"
            parameters.append((now - timedelta(hours=max(0.0, float(max_age_hours)))).isoformat())
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT source, COUNT(*) AS record_count, COUNT(DISTINCT topic_key) AS topic_count,
                       AVG(confidence) AS confidence, MAX(freshness_ts) AS freshness_ts
                FROM research_records
                {where}
                GROUP BY source
                ORDER BY freshness_ts DESC, source ASC
                """,
                parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _freshness_half_life_hours() -> float:
        try:
            return max(0.1, float(os.getenv("RESEARCH_FRESHNESS_HALF_LIFE_HOURS", "24")))
        except (TypeError, ValueError):
            return 24.0

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
        with self._connect() as conn:
            for record in records:
                try:
                    self._upsert_payload(conn, self._serialize(record))
                    persisted += 1
                except ResearchValidationError as err:
                    logger.error(
                        "Research record rejected",
                        extra={"event": "research_record_rejected", "errors": err.errors, "source": record.get("source")},
                    )
        return persisted
