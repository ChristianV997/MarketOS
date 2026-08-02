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
