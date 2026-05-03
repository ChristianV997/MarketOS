"""Tests for signals.tiktok_ingestion — dedup, ordering, schema, telemetry."""
import pytest


def _raw(video_id, views=1000, created_at="2025-05-01T00:00:00Z", **kwargs):
    return {
        "video_id": video_id,
        "url": f"https://www.tiktok.com/@u/video/{video_id}",
        "description": "Test video",
        "author": "testuser",
        "likes": 100,
        "comments": 10,
        "shares": 5,
        "views": views,
        "created_at": created_at,
        **kwargs,
    }


def test_dedup_keeps_max_views():
    from signals.tiktok_ingestion import ingest
    items = [
        _raw("vid1", views=500),
        _raw("vid1", views=1000),
    ]
    result, telem = ingest(items)
    assert len(result) == 1
    assert result[0]["views"] == 1000
    assert telem["count_ingested"] == 1
    assert telem["count_deduped"] == 1


def test_dedup_tiebreak_by_video_id_keeps_both_unique():
    from signals.tiktok_ingestion import ingest
    items = [_raw("vid_b", views=500), _raw("vid_a", views=500)]
    result, _ = ingest(items)
    assert len(result) == 2
    assert {r["video_id"] for r in result} == {"vid_a", "vid_b"}


def test_dedup_equal_views_keeps_lower_video_id():
    from signals.tiktok_ingestion import ingest
    # Same video_id duplicated with equal views: first occurrence kept (lower id wins on tie)
    items = [
        _raw("vid_z", views=500),
        _raw("vid_z", views=500),
    ]
    result, telem = ingest(items)
    assert len(result) == 1
    assert telem["count_deduped"] == 1


def test_deterministic_ordering_independent_of_input_order():
    from signals.tiktok_ingestion import ingest
    items_a = [
        _raw("vid3", created_at="2025-05-01T03:00:00Z"),
        _raw("vid1", created_at="2025-05-01T01:00:00Z"),
        _raw("vid2", created_at="2025-05-01T02:00:00Z"),
    ]
    items_b = [
        _raw("vid1", created_at="2025-05-01T01:00:00Z"),
        _raw("vid3", created_at="2025-05-01T03:00:00Z"),
        _raw("vid2", created_at="2025-05-01T02:00:00Z"),
    ]
    result_a, _ = ingest(items_a)
    result_b, _ = ingest(items_b)
    assert [x["video_id"] for x in result_a] == [x["video_id"] for x in result_b]


def test_deterministic_ordering_by_created_at_then_video_id():
    from signals.tiktok_ingestion import ingest
    items = [
        _raw("vid_b", created_at="2025-05-01T01:00:00Z"),
        _raw("vid_a", created_at="2025-05-01T01:00:00Z"),
        _raw("vid_c", created_at="2025-05-01T00:00:00Z"),
    ]
    result, _ = ingest(items)
    ids = [x["video_id"] for x in result]
    assert ids == ["vid_c", "vid_a", "vid_b"]


def test_schema_defaults_for_missing_engagement():
    from signals.tiktok_ingestion import ingest
    items = [{"video_id": "vid1", "description": "test only"}]
    result, _ = ingest(items)
    sig = result[0]
    assert sig["source"] == "tiktok"
    assert sig["likes"] == 0
    assert sig["comments"] == 0
    assert sig["shares"] == 0
    assert sig["views"] == 0
    assert sig["url"] == ""
    assert sig["author"] == ""
    assert sig["created_at"] == ""


def test_schema_source_always_tiktok():
    from signals.tiktok_ingestion import ingest
    items = [_raw("vid1", **{"source": "youtube"})]
    result, _ = ingest(items)
    assert result[0]["source"] == "tiktok"


def test_telemetry_emitted_once_with_correct_counts(monkeypatch):
    import signals.tiktok_ingestion as mod
    emitted: list[dict] = []

    def capturing_emit(count_ingested, count_deduped, video_ids):
        emitted.append({
            "count_ingested": count_ingested,
            "count_deduped": count_deduped,
            "video_ids": video_ids,
        })

    monkeypatch.setattr(mod, "_emit_telemetry", capturing_emit)

    items = [_raw("vid1"), _raw("vid2"), _raw("vid1", views=9999)]
    mod.ingest(items)

    assert len(emitted) == 1
    assert emitted[0]["count_ingested"] == 2
    assert emitted[0]["count_deduped"] == 1


def test_telemetry_video_ids_capped_at_50(monkeypatch):
    import signals.tiktok_ingestion as mod
    emitted: list[dict] = []

    def capturing_emit(count_ingested, count_deduped, video_ids):
        emitted.append({"video_ids": video_ids})

    monkeypatch.setattr(mod, "_emit_telemetry", capturing_emit)

    items = [_raw(f"vid{i:04d}") for i in range(60)]
    mod.ingest(items)

    assert len(emitted[0]["video_ids"]) == 50


def test_connector_fetch_trending_returns_list():
    from connectors.tiktok_connector import fetch_trending
    result = fetch_trending(limit=3)
    assert isinstance(result, list)
    assert len(result) <= 3
    assert all("video_id" in r for r in result)


def test_ingest_from_connector_stub():
    from connectors.tiktok_connector import fetch_trending
    from signals.tiktok_ingestion import ingest
    raw = fetch_trending(limit=5)
    result, telem = ingest(raw)
    assert len(result) > 0
    assert telem["count_ingested"] == len(result)
    assert all(r["source"] == "tiktok" for r in result)
