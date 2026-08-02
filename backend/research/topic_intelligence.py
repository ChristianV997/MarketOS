"""Deterministic cross-source opportunity ranking for market research."""
from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

_NON_ALNUM = re.compile(r"[^\w\s]+", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def normalize_topic(topic: str) -> str:
    """Return a stable, conservative identity key for cross-source matching."""
    normalized = unicodedata.normalize("NFKC", str(topic)).casefold().strip()
    normalized = _NON_ALNUM.sub(" ", normalized)
    return _WHITESPACE.sub(" ", normalized).strip()


def velocity_signal(velocity: float) -> float:
    """Bound heterogeneous source velocity scales without discarding order."""
    value = max(0.0, float(velocity))
    return value / (1.0 + value)


def rank_opportunity(
    *,
    velocity: float,
    confidence: float,
    source_count: int,
    age_hours: float,
    competition: float | None,
    freshness_half_life_hours: float,
) -> float:
    """Rank a corroborated topic with transparent bounded components.

    Confidence and source diversity keep a high-volume single feed from
    dominating the opportunity list. Competition applies only where there is
    direct source evidence; unknown competition is never treated as low.
    """
    half_life = max(0.1, float(freshness_half_life_hours))
    freshness = math.exp(-max(0.0, age_hours) * math.log(2.0) / half_life)
    consensus = min(1.0, math.log1p(max(0, source_count)) / math.log(4.0))
    base = (
        0.35 * velocity_signal(velocity)
        + 0.25 * min(1.0, max(0.0, float(confidence)))
        + 0.25 * consensus
        + 0.15 * freshness
    )
    competition_penalty = 0.0 if competition is None else 0.20 * min(1.0, max(0.0, float(competition)))
    return round(max(0.0, base * (1.0 - competition_penalty)), 6)


def summarize_opportunity(
    row: dict[str, Any], *, now: datetime, freshness_half_life_hours: float
) -> dict[str, Any]:
    freshness = datetime.fromisoformat(str(row["freshness_ts"]).replace("Z", "+00:00"))
    if freshness.tzinfo is None:
        freshness = freshness.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (now - freshness.astimezone(timezone.utc)).total_seconds() / 3600.0)
    competition = row.get("competition")
    return {
        "topic": row["topic"],
        "topic_key": row["topic_key"],
        "intent": row["intent"],
        "source_count": int(row["source_count"]),
        "record_count": int(row["record_count"]),
        "sources": sorted(str(row["sources"]).split(",")) if row.get("sources") else [],
        "velocity": float(row["velocity"]),
        "confidence": float(row["confidence"]),
        "competition": None if competition is None else float(competition),
        "competition_coverage": round(float(row["competition_coverage"]), 4),
        "freshness_ts": row["freshness_ts"],
        "age_hours": round(age_hours, 4),
        "rank_score": rank_opportunity(
            velocity=float(row["velocity"]),
            confidence=float(row["confidence"]),
            source_count=int(row["source_count"]),
            age_hours=age_hours,
            competition=None if competition is None else float(competition),
            freshness_half_life_hours=freshness_half_life_hours,
        ),
    }
