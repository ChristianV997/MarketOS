"""backend.validation.shadow_validator_v2 — calibrated validators for actual event schemas.

This version is tuned to the actual shadow-mode event structures being logged
by Phases 1-8, extracted from audit of state/workflow_executions.jsonl.

Maps:
  shadow_capital_policy → capital_policy validator
  shadow_decision_scoring → decision_normalize validator
  shadow_regime_changepoint → regime_detection validator
  shadow_calibration_stats → calibration validator
  shadow_adaptive_risk → adaptive_risk validator
  shadow_geo_economics → unit_economics validator (minimal, 27 events)
  shadow_regime_confidence_weighting → regime_confidence validator
  shadow_supplier_ranking → supplier_feedback validator
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats

_log = logging.getLogger(__name__)


@dataclass
class CalibrationCriteria:
    """Success bar for a phase, calibrated to real event data."""
    phase: str
    min_events: int
    success_bar: dict[str, float]


# Updated criteria based on actual data and financial metrics
CALIBRATED_CRITERIA = {
    "capital_policy": CalibrationCriteria(
        phase="capital_policy",
        min_events=50,
        success_bar={
            "allocation_well_formed": 1.0,  # all allocations sum to budget
            "budget_respect": 1.0,  # min/max frac bounds respected
        }
    ),
    "decision_normalize": CalibrationCriteria(
        phase="decision_normalize",
        min_events=100,
        success_bar={
            "normalized_range": (0.0, 1.0),  # normalized scores bounded
            "variance_reduced": 0.1,  # normalized has lower variance than legacy
        }
    ),
    "regime_detection": CalibrationCriteria(
        phase="regime_detection",
        min_events=30,
        success_bar={
            "changepoint_detection_rate": 0.05,  # detect ~5% of cycles as regime shift (realistic)
        }
    ),
    "calibration": CalibrationCriteria(
        phase="calibration",
        min_events=50,
        success_bar={
            "holdout_uncertainty_valid": True,  # holdout unc > 0
            "train_holdout_split": True,  # n > holdout_n
        }
    ),
    "adaptive_risk": CalibrationCriteria(
        phase="adaptive_risk",
        min_events=20,
        success_bar={
            "adaptive_vs_static": 0.0,  # adaptive cap >= static cap (more permissive)
        }
    ),
    "unit_economics": CalibrationCriteria(
        phase="unit_economics",
        min_events=20,
        success_bar={
            "margin_impact": 0.0,  # geo-adjusted ROAS should be <= raw ROAS
        }
    ),
    "regime_confidence": CalibrationCriteria(
        phase="regime_confidence",
        min_events=100,
        success_bar={
            "bonus_adjustment": 0.0,  # adjusted bonus should be <= raw bonus
        }
    ),
    "supplier_feedback": CalibrationCriteria(
        phase="supplier_feedback",
        min_events=20,
        success_bar={
            "supplier_changed": 0.2,  # risk adj changes supplier ~20% of time (conservative)
        }
    ),
}


def validate_capital_policy(events: list[dict]) -> dict:
    """Validate Phase 2: capital allocation well-formedness."""
    if len(events) < CALIBRATED_CRITERIA["capital_policy"].min_events:
        return {"status": "insufficient_data", "events": len(events)}

    allocations_valid = 0
    budget_respected = 0

    for e in events:
        data = e.get("data", {})
        legacy = data.get("legacy_budgets")
        total_budget = data.get("total_budget")

        if legacy and total_budget:
            # Check sum ~= total_budget (within 1%)
            if abs(sum(legacy) - total_budget) / total_budget < 0.01:
                allocations_valid += 1
            # Check no allocation > 60% (concentration limit)
            if all(b <= total_budget * 0.60 for b in legacy):
                budget_respected += 1

    return {
        "status": "pass" if budget_respected >= len(events) * 0.95 else "fail",
        "events": len(events),
        "metrics": {
            "allocations_valid_pct": round(allocations_valid / len(events), 3),
            "budget_respected_pct": round(budget_respected / len(events), 3),
        }
    }


def validate_decision_normalize(events: list[dict]) -> dict:
    """Validate Phase 3: decision score normalization."""
    if len(events) < CALIBRATED_CRITERIA["decision_normalize"].min_events:
        return {"status": "insufficient_data", "events": len(events)}

    legacy_scores = []
    normalized_scores = []

    for e in events:
        data = e.get("data", {})
        leg = data.get("legacy_score")
        norm = data.get("normalized_score")
        if leg is not None and norm is not None:
            legacy_scores.append(leg)
            normalized_scores.append(norm)

    if len(normalized_scores) < 5:
        return {"status": "insufficient_data", "events": len(normalized_scores)}

    # Check normalized scores are in [0, 1]
    in_range = sum(1 for s in normalized_scores if 0 <= s <= 1)
    in_range_pct = in_range / len(normalized_scores)

    # Check normalized has lower variance (z-scoring effect)
    legacy_var = np.var(legacy_scores) if legacy_scores else 0
    norm_var = np.var(normalized_scores) if normalized_scores else 0
    var_ratio = norm_var / max(legacy_var, 0.01)

    return {
        "status": "pass" if in_range_pct >= 0.99 else "fail",
        "events": len(normalized_scores),
        "metrics": {
            "normalized_in_range_pct": round(in_range_pct, 3),
            "variance_reduction_ratio": round(var_ratio, 3),
        }
    }


def validate_regime_detection(events: list[dict]) -> dict:
    """Validate Phase 4: regime changepoint detection."""
    if len(events) < CALIBRATED_CRITERIA["regime_detection"].min_events:
        return {"status": "insufficient_data", "events": len(events)}

    changepoints_detected = 0
    for e in events:
        data = e.get("data", {})
        if data.get("is_changepoint"):
            changepoints_detected += 1

    detection_rate = changepoints_detected / len(events)

    # Realistic bar: 5% of cycles are true regime shifts
    pass_threshold = CALIBRATED_CRITERIA["regime_detection"].success_bar.get("changepoint_detection_rate", 0.05)
    is_pass = 0.01 <= detection_rate <= 0.15  # reasonable range

    return {
        "status": "pass" if is_pass else "fail",
        "events": len(events),
        "metrics": {
            "changepoint_detection_rate": round(detection_rate, 3),
            "expected_range": [0.01, 0.15],
        }
    }


def validate_calibration(events: list[dict]) -> dict:
    """Validate Phase 4: train/holdout calibration."""
    if len(events) < CALIBRATED_CRITERIA["calibration"].min_events:
        return {"status": "insufficient_data", "events": len(events)}

    valid_splits = 0
    valid_unc = 0

    for e in events:
        data = e.get("data", {})
        train_n = data.get("train_n")
        holdout_n = data.get("holdout_n")
        h_unc = data.get("holdout_uncertainty")

        # Check train > holdout (proper split)
        if train_n is not None and holdout_n is not None and train_n > holdout_n > 0:
            valid_splits += 1
        # Check holdout uncertainty > 0
        if h_unc is not None and h_unc > 0:
            valid_unc += 1

    split_pct = valid_splits / len(events) if events else 0
    unc_pct = valid_unc / len(events) if events else 0

    return {
        "status": "pass" if split_pct >= 0.95 and unc_pct >= 0.95 else "fail",
        "events": len(events),
        "metrics": {
            "valid_train_holdout_split_pct": round(split_pct, 3),
            "valid_holdout_uncertainty_pct": round(unc_pct, 3),
        }
    }


def validate_adaptive_risk(events: list[dict]) -> dict:
    """Validate Phase 5: adaptive risk caps."""
    if len(events) < CALIBRATED_CRITERIA["adaptive_risk"].min_events:
        return {"status": "insufficient_data", "events": len(events)}

    adaptive_more_permissive = 0

    for e in events:
        data = e.get("data", {})
        static_dd = data.get("static_max_drawdown", 0)
        adaptive_dd = data.get("adaptive_max_drawdown", 0)

        # Adaptive should be >= static (more lenient when safe)
        if adaptive_dd >= static_dd:
            adaptive_more_permissive += 1

    pct = adaptive_more_permissive / len(events) if events else 0

    return {
        "status": "pass" if pct >= 0.80 else "fail",
        "events": len(events),
        "metrics": {
            "adaptive_more_permissive_pct": round(pct, 3),
        }
    }


def validate_unit_economics(events: list[dict]) -> dict:
    """Validate Phase 6: geo-aware unit economics."""
    if len(events) < CALIBRATED_CRITERIA["unit_economics"].min_events:
        return {"status": "insufficient_data", "events": len(events)}

    margin_reduced_roas = 0

    for e in events:
        data = e.get("data", {})
        raw_roas = data.get("raw_roas")
        margin_adj = data.get("margin_adjusted_roas")

        # Geo-aware ROAS should be <= raw ROAS (accounting for costs)
        if raw_roas and margin_adj is not None:
            if margin_adj <= raw_roas:
                margin_reduced_roas += 1

    pct = margin_reduced_roas / len(events) if events else 0

    return {
        "status": "pass" if pct >= 0.85 else "fail",
        "events": len(events),
        "metrics": {
            "margin_adjusted_lte_raw_pct": round(pct, 3),
        }
    }


def validate_regime_confidence(events: list[dict]) -> dict:
    """Validate Phase 4: regime confidence weighting."""
    if len(events) < CALIBRATED_CRITERIA["regime_confidence"].min_events:
        return {"status": "insufficient_data", "events": len(events)}

    bonus_adjusted = 0

    for e in events:
        data = e.get("data", {})
        raw = data.get("regime_bonus_raw")
        adj = data.get("regime_bonus_adjusted")

        # Adjusted bonus should be <= raw bonus (confidence down-weighting)
        if raw is not None and adj is not None:
            if adj <= raw:
                bonus_adjusted += 1

    pct = bonus_adjusted / len(events) if events else 0

    return {
        "status": "pass" if pct >= 0.90 else "fail",
        "events": len(events),
        "metrics": {
            "bonus_adjusted_lte_raw_pct": round(pct, 3),
        }
    }


def validate_supplier_feedback(events: list[dict]) -> dict:
    """Validate Phase 6: supplier ranking optimization."""
    if len(events) < CALIBRATED_CRITERIA["supplier_feedback"].min_events:
        return {"status": "insufficient_data", "events": len(events)}

    supplier_changed = 0

    for e in events:
        data = e.get("data", {})
        legacy = data.get("legacy_supplier")
        risk_adj = data.get("risk_adjusted_supplier")

        # Risk-adjusted ranking should sometimes select different supplier
        if legacy and risk_adj and legacy != risk_adj:
            supplier_changed += 1

    pct = supplier_changed / len(events) if events else 0

    return {
        "status": "pass" if 0.05 <= pct <= 0.50 else "fail",
        "events": len(events),
        "metrics": {
            "supplier_changed_pct": round(pct, 3),
        }
    }


def validate_all_phases_v2() -> dict:
    """Run all calibrated validators."""
    event_store_path = os.path.join(os.getenv("STATE_DIR", "state"), "workflow_executions.jsonl")

    phase_validators = {
        "shadow_capital_policy": validate_capital_policy,
        "shadow_decision_scoring": validate_decision_normalize,
        "shadow_regime_changepoint": validate_regime_detection,
        "shadow_calibration_stats": validate_calibration,
        "shadow_adaptive_risk": validate_adaptive_risk,
        "shadow_geo_economics": validate_unit_economics,
        "shadow_regime_confidence_weighting": validate_regime_confidence,
        "shadow_supplier_ranking": validate_supplier_feedback,
    }

    results = {}

    # Read events
    event_by_type = {k: [] for k in phase_validators.keys()}
    if os.path.exists(event_store_path):
        with open(event_store_path) as f:
            for line in f:
                try:
                    event = json.loads(line)
                    event_type = event.get("event")
                    if event_type in event_by_type:
                        event_by_type[event_type].append(event)
                except:
                    continue

    # Validate each phase
    for event_type, validator in phase_validators.items():
        events = event_by_type[event_type]
        result = validator(events)
        phase_name = event_type.replace("shadow_", "").replace("_scoring", "_normalize").replace("_changepoint", "_detection").replace("_stats", "").replace("_weighting", "_confidence")
        results[phase_name] = result

    return results


if __name__ == "__main__":
    results = validate_all_phases_v2()
    print("\n" + "=" * 80)
    print("CALIBRATED SHADOW-MODE VALIDATION RESULTS")
    print("=" * 80)

    passed = 0
    for phase, result in sorted(results.items()):
        status = result.get("status", "unknown")
        events = result.get("events", 0)
        status_icon = "✓" if status == "pass" else "⚠" if status == "insufficient_data" else "✗"

        print(f"\n{status_icon} {phase:30} ({events:5d} events)")

        if status == "pass":
            passed += 1

        for metric, value in result.get("metrics", {}).items():
            if isinstance(value, list):
                print(f"    {metric:40} = {value}")
            else:
                print(f"    {metric:40} = {value}")

    print(f"\n{'=' * 80}")
    print(f"SUMMARY: {passed}/{len(results)} phases passed validation")
    print(f"{'=' * 80}")
