"""Small-sample-safe creative experiment evaluation.

Statistical rigor: rather than a hard ROAS threshold, per-variant
significance is tested against the break-even point (ROAS == 1.0) with a
one-sample t-test over per-observation ROAS. ``status`` only becomes
"winner"/"loser" when the result both clears a minimum-detectable-effect
margin AND is statistically significant at ``significance_level`` — a
3-conversion variant at ROAS 1.6 no longer gets the same "winner" label as
one with 300 conversions; with too few usable ROAS points the t-test can't
run at all and status stays "undetermined" regardless of the point estimate.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import sqrt
from statistics import mean, stdev
from typing import Iterable
from scipy import stats as _scipy_stats
from .contracts import CampaignObservation
from .quality import deduplicate_observations, quality_reasons

# Break-even ROAS: the null hypothesis every variant is tested against.
_BREAKEVEN_ROAS = 1.0
# Minimum mean ROAS required (on top of significance) to call a "winner" —
# an economically-meaningful margin above break-even, not just non-zero.
_MIN_EFFECT_ROAS = 1.5

@dataclass(frozen=True)
class ExperimentResult:
    variant_id: str; observations: int; spend: float; revenue: float; conversions: int
    ctr: float | None; cvr: float | None; roas: float | None; confidence: float
    status: str; reasons: tuple[str, ...]
    mean_roas: float | None = None
    roas_stderr: float | None = None
    p_value: float | None = None
    significant: bool = False
    def to_dict(self) -> dict: return {**self.__dict__, "reasons": list(self.reasons)}

def _significance_test(per_observation_roas: list[float], *, significance_level: float) -> tuple[float | None, float | None, float | None, bool]:
    """One-sample t-test of per-observation ROAS against break-even.

    Returns (mean_roas, roas_stderr, p_value, significant). Needs at least
    two usable (spend > 0) observations with non-zero variance to produce a
    meaningful test; otherwise returns Nones / significant=False so callers
    fall back to "undetermined" rather than trusting a point estimate.
    """
    n = len(per_observation_roas)
    if n < 2:
        return (per_observation_roas[0], None, None, False) if n == 1 else (None, None, None, False)
    sample_mean = mean(per_observation_roas)
    sample_stdev = stdev(per_observation_roas)
    if sample_stdev == 0.0:
        # Zero variance: every observation identical. Treat as significant
        # only if it differs from break-even (a degenerate but valid case).
        significant = sample_mean != _BREAKEVEN_ROAS
        p_value = 0.0 if significant else 1.0
        return round(sample_mean, 6), 0.0, p_value, significant and p_value <= significance_level
    stderr = sample_stdev / sqrt(n)
    t_stat = (sample_mean - _BREAKEVEN_ROAS) / stderr
    p_value = float(2 * (1 - _scipy_stats.t.cdf(abs(t_stat), df=n - 1)))
    return round(sample_mean, 6), round(stderr, 6), round(p_value, 6), p_value <= significance_level

def evaluate_experiment(observations: Iterable[CampaignObservation], *, min_observations: int = 3, min_conversions: int = 3, significance_level: float = 0.05) -> list[ExperimentResult]:
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

        per_observation_roas = [
            (r.revenue - r.refunds) / r.spend for r in rows if r.spend > 0
        ]
        mean_roas, roas_stderr, p_value, significant = _significance_test(
            per_observation_roas, significance_level=significance_level
        )

        confidence = round(1.0 - p_value, 4) if p_value is not None else round(min(1.0, sqrt(max(conversions, 0) / 30.0)), 4)
        status = "undetermined"
        if not reasons and mean_roas is not None and significant:
            status = "winner" if mean_roas >= _MIN_EFFECT_ROAS else "loser" if mean_roas < _BREAKEVEN_ROAS else "undetermined"

        results.append(ExperimentResult(
            variant_id, len(rows), spend, revenue, conversions, ctr, cvr, roas, confidence, status,
            tuple(sorted(set(reasons))), mean_roas, roas_stderr, p_value, significant,
        ))
    return results
