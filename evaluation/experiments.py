"""Small-sample-safe creative experiment evaluation."""
from __future__ import annotations
from dataclasses import dataclass
from math import sqrt
from typing import Iterable
from .contracts import CampaignObservation
from .quality import deduplicate_observations, quality_reasons

@dataclass(frozen=True)
class ExperimentResult:
    variant_id: str; observations: int; spend: float; revenue: float; conversions: int
    ctr: float | None; cvr: float | None; roas: float | None; confidence: float
    status: str; reasons: tuple[str, ...]
    def to_dict(self) -> dict: return {**self.__dict__, "reasons": list(self.reasons)}

def evaluate_experiment(observations: Iterable[CampaignObservation], *, min_observations: int = 3, min_conversions: int = 3) -> list[ExperimentResult]:
    grouped: dict[str, list[CampaignObservation]] = {}
    for row in deduplicate_observations(observations): grouped.setdefault(row.creative_id or row.campaign_id, []).append(row)
    results: list[ExperimentResult] = []
    for variant_id, rows in sorted(grouped.items()):
        spend = round(sum(r.spend for r in rows), 4); revenue = round(sum(max(r.revenue - r.refunds, 0.0) for r in rows), 4)
        impressions = sum(r.impressions for r in rows); clicks = sum(r.clicks for r in rows); conversions = sum(r.conversions for r in rows)
        reasons = sorted({reason for r in rows for reason in quality_reasons(r.quality)})
        if len(rows) < min_observations: reasons.append("insufficient_observations")
        if conversions < min_conversions: reasons.append("insufficient_conversions")
        if spend <= 0: reasons.append("missing_spend")
        if any(r.quality.is_synthetic for r in rows): reasons.append("synthetic_only")
        ctr = round(clicks / impressions, 6) if impressions else None; cvr = round(conversions / clicks, 6) if clicks else None; roas = round(revenue / spend, 6) if spend else None
        confidence = round(min(1.0, sqrt(max(conversions, 0) / 30.0)), 4); status = "undetermined"
        if not reasons and roas is not None: status = "winner" if roas >= 1.5 else "loser" if roas < 1.0 else "undetermined"
        results.append(ExperimentResult(variant_id, len(rows), spend, revenue, conversions, ctr, cvr, roas, confidence, status, tuple(sorted(set(reasons)))))
    return results
