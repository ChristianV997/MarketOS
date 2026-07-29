"""Data-quality checks shared by product and campaign evaluations."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Iterable
from .contracts import CampaignObservation, DataQuality

def quality_reasons(quality: DataQuality, *, max_age_hours: float = 48.0) -> list[str]:
    reasons: list[str] = []
    if quality.provenance in {"mock", "simulated", "fallback"}: reasons.append("synthetic_only")
    if quality.attribution in {"unattributed", "unknown"}: reasons.append("unattributed")
    if quality.completeness != "complete": reasons.append("incomplete_data")
    age = (datetime.now(timezone.utc) - quality.observed_at).total_seconds() / 3600
    if age > max_age_hours: reasons.append("stale_data")
    return reasons

def deduplicate_observations(observations: Iterable[CampaignObservation]) -> list[CampaignObservation]:
    seen: set[str] = set(); result: list[CampaignObservation] = []
    for observation in observations:
        if observation.observation_id in seen: continue
        seen.add(observation.observation_id); result.append(observation)
    return result
