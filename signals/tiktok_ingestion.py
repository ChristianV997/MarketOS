"""tiktok_ingestion — deterministic, idempotent TikTok trend ingestion."""
from __future__ import annotations
from signals.schemas import TikTokSignal


def normalize(raw: dict) -> TikTokSignal:
    return TikTokSignal(
        source="tiktok",
        video_id=str(raw.get("video_id") or ""),
        url=str(raw.get("url") or ""),
        description=str(raw.get("description") or ""),
        author=str(raw.get("author") or ""),
        likes=int(raw.get("likes") or 0),
        comments=int(raw.get("comments") or 0),
        shares=int(raw.get("shares") or 0),
        views=int(raw.get("views") or 0),
        created_at=str(raw.get("created_at") or ""),
    )


def _dedup(items: list[TikTokSignal]) -> list[TikTokSignal]:
    """Keep one record per video_id: highest views; tie-break by video_id asc."""
    best: dict[str, TikTokSignal] = {}
    for item in items:
        vid = item["video_id"]
        prev = best.get(vid)
        if prev is None:
            best[vid] = item
        elif item["views"] > prev["views"] or (
            item["views"] == prev["views"] and item["video_id"] < prev["video_id"]
        ):
            best[vid] = item
    return list(best.values())


def _sort_stable(items: list[TikTokSignal]) -> list[TikTokSignal]:
    """Sort deterministically: created_at asc, then video_id asc."""
    return sorted(items, key=lambda x: (x["created_at"], x["video_id"]))


def _emit_telemetry(count_ingested: int, count_deduped: int, video_ids: list[str]) -> None:
    payload = {
        "source": "tiktok",
        "count_ingested": count_ingested,
        "count_deduped": count_deduped,
        "video_ids": video_ids[:50],
    }
    try:
        from backend.pubsub.broker import broker
        broker.publish("signals.ingested", payload)
    except Exception:
        pass


def ingest(raw_items: list[dict]) -> tuple[list[TikTokSignal], dict]:
    """Normalize, dedup, and sort raw TikTok items.

    Returns:
        (normalized_items, telemetry_payload)
    """
    normalized = [normalize(raw) for raw in raw_items]
    before_count = len(normalized)
    deduped = _dedup(normalized)
    after_count = len(deduped)
    sorted_items = _sort_stable(deduped)

    telemetry: dict = {
        "source": "tiktok",
        "count_ingested": after_count,
        "count_deduped": before_count - after_count,
        "video_ids": [item["video_id"] for item in sorted_items[:50]],
    }
    _emit_telemetry(
        count_ingested=after_count,
        count_deduped=before_count - after_count,
        video_ids=telemetry["video_ids"],
    )
    return sorted_items, telemetry
