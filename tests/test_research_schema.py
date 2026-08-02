import time
from datetime import datetime, timedelta, timezone

import pytest

from backend.jobs.research_trend_v1 import register_research_prune_job
from backend.jobs.runner import JobRegistry
from backend.research import (
    ResearchValidationError,
    TrendRecordStore,
    generate_dedupe_key,
    validate_research_record,
)


def _record(topic: str = "compare ai tools", freshness_ts: str | None = None) -> dict:
    ts = freshness_ts or datetime(2026, 1, 1, 10, 12, tzinfo=timezone.utc).isoformat()
    return {
        "topic": topic,
        "intent": "compare",
        "velocity": 0.9,
        "competition": 0.4,
        "source": "google_trends_v1",
        "freshness_ts": ts,
        "confidence": 0.8,
        "raw": {"topic": topic},
    }


def test_validation_rejects_missing_fields_and_out_of_range_values():
    with pytest.raises(ResearchValidationError) as err:
        validate_research_record(
            {
                "topic": "",
                "intent": "bad_intent",
                "velocity": 0.1,
                "competition": 1.5,
                "source": "google_trends_v1",
                "freshness_ts": "not-a-date",
                "confidence": -0.1,
                "raw": [],
            }
        )

    fields = {item["field"] for item in err.value.errors}
    assert {"topic", "intent", "competition", "freshness_ts", "confidence", "raw"}.issubset(fields)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True])
def test_validation_rejects_non_finite_or_boolean_numeric_values(value):
    record = _record()
    record["velocity"] = value
    with pytest.raises(ResearchValidationError) as err:
        validate_research_record(record)
    assert any(item["field"] == "velocity" for item in err.value.errors)


def test_dedupe_key_generation_is_deterministic():
    ts = datetime(2026, 1, 1, 10, 59, tzinfo=timezone.utc).isoformat()
    left = generate_dedupe_key("google_trends_v1", "Compare AI Tools", ts)
    right = generate_dedupe_key("google_trends_v1", "Compare AI Tools", ts)
    assert left == right
    assert left == "google_trends_v1:compare ai tools:2026-01-01-10"


def test_upsert_inserts_then_updates_on_same_dedupe_key(tmp_path):
    store = TrendRecordStore(path=str(tmp_path / "research.db"))
    first = store.upsert(_record(topic="laptop deals"))
    second = store.upsert(_record(topic="laptop deals"))

    assert first["id"] == second["id"]
    assert len(store.findTopN(10)) == 1
    assert store.metrics.counters["research_dedupe_hits_total"] == 1


def test_insert_query_and_dedupe_end_to_end(tmp_path):
    store = TrendRecordStore(path=str(tmp_path / "research.db"))
    ts = datetime(2026, 1, 1, 10, 10, tzinfo=timezone.utc).isoformat()
    store.upsert(_record(topic="topic a", freshness_ts=ts))
    store.upsert(_record(topic="topic a", freshness_ts=ts))
    store.upsert(_record(topic="topic b", freshness_ts=datetime(2026, 1, 1, 11, 10, tzinfo=timezone.utc).isoformat()))

    top = store.findTopN(5)
    by_source = store.findBySource("google_trends_v1")

    assert len(top) == 2
    assert len(by_source) == 2
    assert all(item["source"] == "google_trends_v1" for item in by_source)
    fetched = store.findById(top[0]["id"])
    assert fetched is not None


def test_top_n_query_is_fast_for_velocity_confidence_ordering(tmp_path):
    store = TrendRecordStore(path=str(tmp_path / "research.db"))
    for idx in range(400):
        current = _record(
            topic=f"topic-{idx}",
            freshness_ts=(datetime.now(timezone.utc) + timedelta(minutes=idx)).isoformat(),
        )
        current["velocity"] = float(idx) / 10
        current["confidence"] = min(1.0, 0.5 + idx / 1000)
        store.upsert(current)

    start = time.perf_counter()
    top = store.findTopN(25)
    elapsed = time.perf_counter() - start

    assert len(top) == 25
    assert elapsed < 1.0


def test_top_n_zero_returns_empty(tmp_path):
    store = TrendRecordStore(path=str(tmp_path / "research.db"))
    store.upsert(_record(topic="one"))
    assert store.findTopN(0) == []


def test_unknown_competition_is_persisted_and_can_be_excluded(tmp_path):
    store = TrendRecordStore(path=str(tmp_path / "research.db"))
    unknown = _record(topic="unknown competition")
    unknown["competition"] = None
    known = _record(topic="known competition")
    store.upsert(unknown)
    store.upsert(known)

    assert {item["topic"] for item in store.findTopN(10)} == {"unknown competition", "known competition"}
    assert [item["topic"] for item in store.findTopN(10, require_competition=True)] == ["known competition"]


def test_existing_not_null_database_is_migrated_without_data_loss(tmp_path):
    import sqlite3

    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE research_records (
                id TEXT PRIMARY KEY, topic TEXT NOT NULL, intent TEXT NOT NULL,
                velocity REAL NOT NULL, competition REAL NOT NULL, source TEXT NOT NULL,
                freshness_ts TEXT NOT NULL, confidence REAL NOT NULL, raw TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, dedupe_key TEXT NOT NULL UNIQUE
            );
            INSERT INTO research_records VALUES
            ('legacy-id', 'legacy topic', 'research', 0.5, 0.2, 'legacy',
             '2026-01-01T10:00:00+00:00', 0.7, '{}',
             '2026-01-01T10:00:00+00:00', '2026-01-01T10:00:00+00:00', 'legacy:legacy topic:2026-01-01-10');
            """
        )

    store = TrendRecordStore(path=str(path))
    assert store.findById("legacy-id")["topic"] == "legacy topic"


def test_opportunities_aggregate_normalized_topics_and_preserve_unknown_competition(tmp_path):
    store = TrendRecordStore(path=str(tmp_path / "research.db"))
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    first = _record(topic="Wireless Earbuds!", freshness_ts=now.isoformat())
    first["source"] = "reddit"
    first["competition"] = None
    first["velocity"] = 0.8
    second = _record(topic="wireless earbuds", freshness_ts=(now - timedelta(minutes=5)).isoformat())
    second["source"] = "mercadolibre"
    second["competition"] = 0.4
    second["confidence"] = 0.9
    store.upsert(first)
    store.upsert(second)

    opportunities = store.find_opportunities(10, max_age_hours=24, now=now)

    assert len(opportunities) == 1
    opportunity = opportunities[0]
    assert opportunity["topic_key"] == "wireless earbuds"
    assert opportunity["topic"] == "Wireless Earbuds!"
    assert opportunity["source_count"] == 2
    assert opportunity["sources"] == ["mercadolibre", "reddit"]
    assert opportunity["competition"] == pytest.approx(0.4)
    assert opportunity["competition_coverage"] == pytest.approx(0.5)
    assert 0.0 < opportunity["rank_score"] <= 1.0


def test_opportunity_source_floor_and_source_summary(tmp_path):
    store = TrendRecordStore(path=str(tmp_path / "research.db"))
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    record = _record(topic="single source", freshness_ts=now.isoformat())
    record["source"] = "reddit"
    store.upsert(record)

    assert store.find_opportunities(10, min_sources=2, now=now) == []
    summary = store.source_summary(max_age_hours=24, now=now)
    assert summary == [{
        "source": "reddit",
        "record_count": 1,
        "topic_count": 1,
        "confidence": 0.8,
        "freshness_ts": now.isoformat(),
    }]
    nullable = _record(topic="new nullable")
    nullable["competition"] = None
    persisted = store.upsert(nullable)
    assert persisted["competition"] is None
    assert any(item["topic"] == "new nullable" for item in store.findTopN(10))


def test_append_many_persists_valid_records_when_one_record_is_invalid(tmp_path):
    store = TrendRecordStore(path=str(tmp_path / "research.db"))
    invalid = _record(topic="invalid")
    invalid["velocity"] = float("nan")

    assert store.append_many([_record(topic="kept"), invalid]) == 1
    assert [record["topic"] for record in store.findTopN(10)] == ["kept"]


def test_nullable_topic_key_is_backfilled_for_existing_database(tmp_path):
    import sqlite3

    path = tmp_path / "legacy_topic_key.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE research_records (
                id TEXT PRIMARY KEY, topic TEXT NOT NULL, topic_key TEXT, intent TEXT NOT NULL,
                velocity REAL NOT NULL, competition REAL, source TEXT NOT NULL,
                freshness_ts TEXT NOT NULL, confidence REAL NOT NULL, raw TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, dedupe_key TEXT NOT NULL UNIQUE
            );
            INSERT INTO research_records VALUES
            ('legacy-id', 'Wireless Earbuds!', NULL, 'research', 0.5, NULL, 'legacy',
             '2026-01-01T10:00:00+00:00', 0.7, '{}',
             '2026-01-01T10:00:00+00:00', '2026-01-01T10:00:00+00:00', 'legacy:wireless:2026-01-01-10');
            """
        )

    store = TrendRecordStore(path=str(path))
    assert store.find_opportunities(10, now=datetime(2026, 1, 1, 12, tzinfo=timezone.utc))[0]["topic_key"] == "wireless earbuds"


def test_research_prune_job_uses_retention_window(tmp_path):
    store = TrendRecordStore(path=str(tmp_path / "research.db"), retention_days=30)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    new_ts = datetime.now(timezone.utc).isoformat()
    store.upsert(_record(topic="old", freshness_ts=old_ts))
    store.upsert(_record(topic="new", freshness_ts=new_ts))

    registry = JobRegistry(max_retries=0)
    register_research_prune_job(registry, store=store)
    result = registry.run("research.prune")

    assert result["status"] == "succeeded"
    assert len(store.findTopN(10)) == 1
