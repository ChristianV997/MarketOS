"""Locations for committed synthetic shadow-evaluation fixtures."""
from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass


FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "shadow_evaluation"


@dataclass(frozen=True)
class FixtureScenario:
    filename: str
    feature_id: str
    expected_classification: str
    purpose: str


def fixture_scenarios() -> tuple[FixtureScenario, ...]:
    """Human-auditable inventory; fixtures remain the source of actual evidence."""
    return (
        FixtureScenario("attribution_pass_candidate.jsonl", "attribution_reconciliation", "PROMOTE", "Deduplicated revenue equals order ground truth after sufficient synthetic coverage."),
        FixtureScenario("attribution_revenue_inflation_blocker.jsonl", "attribution_reconciliation", "REWORK", "Revenue exceeding order ground truth is a hard safety blocker."),
        FixtureScenario("capital_policy_cap_violation.jsonl", "capital_policy", "REWORK", "Candidate exceeds a budget cap despite primary-metric improvement."),
        FixtureScenario("capital_policy_risk_adjusted_improvement.jsonl", "capital_policy", "KEEP_SHADOW", "Positive result is held because its evidence count is below the policy threshold."),
        FixtureScenario("normalized_scoring_unbounded_dominance.jsonl", "normalized_scoring", "REWORK", "A single unbounded score term cannot silently dominate rankings."),
        FixtureScenario("normalized_scoring_stable_improvement.jsonl", "normalized_scoring", "KEEP_SHADOW", "Bounded improvement remains shadow-only below the required sample."),
        FixtureScenario("adaptive_risk_safety_blocker.jsonl", "adaptive_risk", "REWORK", "Risk cap cannot loosen when volatility or concentration worsens."),
        FixtureScenario("adaptive_risk_loss_prevention.jsonl", "adaptive_risk", "KEEP_SHADOW", "Loss prevention evidence remains insufficient for promotion."),
        FixtureScenario("supplier_geo_negative_margin_blocker.jsonl", "supplier_geo_economics", "REWORK", "Raw-ROAS expansion is blocked when landed contribution is negative."),
        FixtureScenario("supplier_geo_margin_improvement.jsonl", "supplier_geo_economics", "KEEP_SHADOW", "Better landed economics needs a larger evidence set."),
        FixtureScenario("calibration_regime_confidence_overconfidence.jsonl", "calibration_regime_confidence", "REWORK", "Confidence cannot increase while out-of-sample error worsens."),
        FixtureScenario("calibration_regime_confidence_insufficient.jsonl", "calibration_regime_confidence", "KEEP_SHADOW", "Calibration improvement remains below its larger threshold."),
    )


def default_fixture_paths() -> list[Path]:
    paths = {path.name: path for path in FIXTURE_ROOT.glob("*.jsonl") if path.is_file()}
    return [paths[item.filename] for item in fixture_scenarios() if item.filename in paths]
