"""simulation.ranking — SimulationResult dataclass and ranking utilities."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SimulationResult:
    """Scored and ranked candidate from the simulation layer."""

    signal: dict  # original signal dict
    product: str
    hook: str
    angle: str

    # Model outputs
    predicted_engagement: float = 0.0
    predicted_roas: float = 0.0
    predicted_ctr: float = 0.0

    # Uncertainty / risk
    confidence: float = 0.0   # 0–1; higher = more data behind prediction
    risk_score: float = 0.0   # 0–1; higher = more uncertain/volatile

    # Calibration-corrected ROAS
    corrected_roas: float = 0.0

    # Composite rank score (higher = preferred)
    rank_score: float = 0.0
    rank: int = 0

    # Feature vector used
    features: list[float] = field(default_factory=list)

    # Phase 7: Monte Carlo prediction interval (bootstrap over model
    # residuals), populated by simulation.engine when available; 0.0 when
    # the model is cold-started or the signal wasn't scored with intervals.
    mc_interval_width: float = 0.0
    mc_ci_lower: float = 0.0
    mc_ci_upper: float = 0.0

    # Metadata
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "product": self.product,
            "hook": self.hook,
            "angle": self.angle,
            "predicted_engagement": round(self.predicted_engagement, 4),
            "predicted_roas": round(self.predicted_roas, 4),
            "predicted_ctr": round(self.predicted_ctr, 4),
            "corrected_roas": round(self.corrected_roas, 4),
            "confidence": round(self.confidence, 4),
            "risk_score": round(self.risk_score, 4),
            "rank_score": round(self.rank_score, 4),
            "rank": self.rank,
            "mc_interval_width": round(self.mc_interval_width, 4),
            "mc_ci_lower": round(self.mc_ci_lower, 4),
            "mc_ci_upper": round(self.mc_ci_upper, 4),
            "ts": self.ts,
        }


# ── ranking functions ─────────────────────────────────────────────────────────

def _confidence_from_history(history: list[dict]) -> float:
    """Smoothed confidence: n / (n + 10) where n = historical sample count."""
    n = len(history) if history else 0
    return n / (n + 10.0)


def _risk_from_history(history: list[dict]) -> float:
    """Risk as inverse of win-rate stability.  High variance → high risk."""
    if not history:
        return 1.0
    roas_vals = [float(r.get("roas", 0) or 0) for r in history]
    if len(roas_vals) < 2:
        return 0.8
    mean = sum(roas_vals) / len(roas_vals)
    variance = sum((v - mean) ** 2 for v in roas_vals) / len(roas_vals)
    std = math.sqrt(variance)
    return float(min(1.0, std / max(mean, 0.1)))


def _roas_from_engagement(eng: float, patterns: dict | None = None) -> float:
    """Rough ROAS estimate from engagement score using pattern-calibrated scale."""
    base = eng * 3.0  # engagement 1.0 ≈ ROAS 3.0
    if patterns:
        top_hook_scores = list(patterns.get("hook_scores", {}).values())
        if top_hook_scores:
            pattern_boost = max(top_hook_scores) * 0.5
            base = base * (1.0 + pattern_boost)
    return float(min(base, 10.0))


def _ctr_from_engagement(eng: float) -> float:
    return float(min(eng * 0.05, 0.10))


def rank_results(results: list[SimulationResult]) -> list[SimulationResult]:
    """Assign rank_score and rank (1 = best) to a list of SimulationResults.

    Rank score formula:
        0.50 * predicted_engagement
      + 0.30 * (corrected_roas / 3.0 clamped to 1)
      + 0.10 * confidence
      - 0.10 * risk_score
    """
    for r in results:
        r.rank_score = (
            0.50 * r.predicted_engagement
            + 0.30 * min(r.corrected_roas / 3.0, 1.0)
            + 0.10 * r.confidence
            - 0.10 * r.risk_score
        )

    results.sort(key=lambda r: r.rank_score, reverse=True)
    for i, r in enumerate(results):
        r.rank = i + 1
    return results


def build_result(
    signal: dict,
    predicted_engagement: float,
    history: list[dict] | None = None,
    patterns: dict | None = None,
    calibrator: Any | None = None,
) -> SimulationResult:
    """Construct a SimulationResult from model output and context."""
    product = signal.get("product", "")
    conf = _confidence_from_history(history or [])
    risk = _risk_from_history(history or [])
    pred_roas = _roas_from_engagement(predicted_engagement, patterns)
    pred_ctr = _ctr_from_engagement(predicted_engagement)

    corrected = pred_roas
    if calibrator is not None:
        corrected = calibrator.correct(product, pred_roas)

    return SimulationResult(
        signal=signal,
        product=product,
        hook=signal.get("hook", ""),
        angle=signal.get("angle", ""),
        predicted_engagement=predicted_engagement,
        predicted_roas=pred_roas,
        predicted_ctr=pred_ctr,
        corrected_roas=max(0.0, corrected),
        confidence=conf,
        risk_score=risk,
    )
