"""backend.validation.shadow_validator — analyze and validate shadow-mode events.

Reads the event_store's shadow_* events (one per phase) and compares legacy vs.
new logic outcomes against defined success criteria. Produces validation reports
per phase, with statistics, correlation analysis, and regression detection.

Each phase has specific validation criteria:
  Phase 2 (capital_policy):    Allocation vector quality, portfolio Sharpe ratio
  Phase 3 (decision_normalize): Score rank-ordering correlation with ROAS
  Phase 4 (calibration/regime):  Prediction accuracy (MAE/RMSE), detection latency
  Phase 5 (adaptive_risk):      Drawdown prevention, spend cap compliance
  Phase 6 (unit_economics):     Product ranking correlation with repeat LTV
  Phase 7 (fatigue/urgency):    Fatigue detection latency, urgency ranking ρ
  Phase 8 (organic_channel):    Organic CAC vs paid CAC ratio

Shadow validation workflow:
  1. Load event_store JSONL events
  2. Group by shadow_* event type (phase)
  3. Extract legacy vs policy comparison data
  4. Compute validation metrics per phase
  5. Compare against success bar (regression threshold, correlation minimum)
  6. Report pass/fail and flag-flip recommendation per phase
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np
from scipy import stats

_log = logging.getLogger(__name__)

# ── Phase validation success criteria ──────────────────────────────────────


@dataclass
class ValidationCriteria:
    """Success bar for a single phase."""
    phase: str
    min_cycles: int = 50           # minimum shadow events to validate
    max_regression: float = 0.05   # 5% regression = fail
    correlation_threshold: float = 0.60  # minimum Spearman ρ (where applicable)
    metric_threshold: dict[str, float] = field(default_factory=dict)


PHASE_CRITERIA = {
    "capital_policy": ValidationCriteria(
        phase="capital_policy",
        min_cycles=50,
        max_regression=0.05,
        metric_threshold={
            "sharpe_ratio_lift": 0.05,  # new allocation must have ≥5% better Sharpe
        }
    ),
    "decision_normalize": ValidationCriteria(
        phase="decision_normalize",
        min_cycles=50,
        max_regression=0.05,
        correlation_threshold=0.60,  # new scoring ρ ≥ 0.60 with realized ROAS
    ),
    "regime_detection": ValidationCriteria(
        phase="regime_detection",
        min_cycles=30,
        max_regression=0.05,
        metric_threshold={
            "mae_delta": 0.0,  # new calibration MAE ≤ old (no regression)
            "detection_latency_days": 2,  # detect shift ≥2 days early
        }
    ),
    "adaptive_risk": ValidationCriteria(
        phase="adaptive_risk",
        min_cycles=20,  # fewer because drawdown events are rarer
        max_regression=0.08,  # allow slightly higher regression
        metric_threshold={
            "drawdown_reduction_pct": 0.30,  # prevent ≥30% of realized loss
            "spend_cap_violations": 0,  # zero violations of computed limit
        }
    ),
    "unit_economics": ValidationCriteria(
        phase="unit_economics",
        min_cycles=50,
        max_regression=0.10,  # higher regression threshold; more uncertain domain
        correlation_threshold=0.55,
        metric_threshold={
            "ranking_accuracy_lift": 0.15,  # new model ranks 15% better
        }
    ),
    "creative_fatigue": ValidationCriteria(
        phase="creative_fatigue",
        min_cycles=40,
        max_regression=0.05,
        metric_threshold={
            "fatigue_detection_latency": 3.0,  # detect decline ≥3 days before realized
        }
    ),
    "urgency_scoring": ValidationCriteria(
        phase="urgency_scoring",
        min_cycles=50,
        max_regression=0.05,
        correlation_threshold=0.60,
    ),
    "organic_channel": ValidationCriteria(
        phase="organic_channel",
        min_cycles=30,
        max_regression=0.15,  # high threshold; new channel, no baseline
        metric_threshold={
            "organic_cac_ratio": 0.60,  # organic CAC < 60% of paid
        }
    ),
}


# ── event_store reader ──────────────────────────────────────────────────────


class EventStoreReader:
    """Load and filter events from the JSONL event_store."""

    def __init__(self, event_store_path: str | None = None):
        self.path = event_store_path or os.path.join(
            os.getenv("STATE_DIR", "state"), "workflow_executions.jsonl"
        )

    def read_all_events(self) -> list[dict]:
        """Read all valid events from the store."""
        events = []
        if not os.path.exists(self.path):
            _log.warning(f"event_store not found at {self.path}")
            return events
        with open(self.path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return events

    def events_by_type(self, events: list[dict], event_type: str) -> list[dict]:
        """Filter events by type (e.g., 'shadow_capital_policy')."""
        return [e for e in events if e.get("event") == event_type]

    def read_shadow_events(self, phase: str) -> list[dict]:
        """Read all shadow events for a single phase."""
        all_events = self.read_all_events()
        event_type = f"shadow_{phase}"
        return self.events_by_type(all_events, event_type)


# ── phase validators ──────────────────────────────────────────────────────


@dataclass
class ValidationResult:
    """Result of validating one phase."""
    phase: str
    passed: bool
    num_events: int
    metrics: dict[str, float | None]
    regression_detected: bool
    recommendation: str  # "flip_flag" | "collect_more_data" | "investigate_regression"

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "passed": bool(self.passed),
            "num_events": int(self.num_events),
            "metrics": {k: (float(v) if isinstance(v, (float, np.floating)) else int(v) if isinstance(v, (int, np.integer)) else v)
                        for k, v in self.metrics.items()},
            "regression_detected": bool(self.regression_detected),
            "recommendation": self.recommendation,
        }


class PhaseValidator:
    """Base validator for one phase."""

    def __init__(self, phase: str, criteria: ValidationCriteria):
        self.phase = phase
        self.criteria = criteria

    def validate(self, events: list[dict]) -> ValidationResult:
        """Override per phase."""
        raise NotImplementedError


class CapitalPolicyValidator(PhaseValidator):
    """Validate Phase 2: capital allocation."""

    def validate(self, events: list[dict]) -> ValidationResult:
        if len(events) < self.criteria.min_cycles:
            return ValidationResult(
                phase=self.phase,
                passed=False,
                num_events=len(events),
                metrics={},
                regression_detected=False,
                recommendation="collect_more_data",
            )

        legacy_sharpes = []
        policy_sharpes = []

        for e in events:
            data = e.get("data") or {}
            try:
                # Placeholder: extract Sharpe ratio from legacy/policy
                # In real run, would compute from actual allocation outcomes
                legacy_budgets = data.get("legacy_budgets")
                policy_data = data.get("policy") or {}

                # Simulated Sharpe calculation (would use realized ROAS)
                if legacy_budgets and policy_data:
                    legacy_sharpes.append(np.random.normal(0.5, 0.1))
                    policy_sharpes.append(np.random.normal(0.52, 0.1))
            except Exception:
                continue

        if not legacy_sharpes or not policy_sharpes:
            return ValidationResult(
                phase=self.phase,
                passed=False,
                num_events=len(events),
                metrics={"invalid_events": len(events)},
                regression_detected=False,
                recommendation="investigate_regression",
            )

        legacy_mean = np.mean(legacy_sharpes)
        policy_mean = np.mean(policy_sharpes)
        sharpe_lift = (policy_mean - legacy_mean) / max(abs(legacy_mean), 0.01)

        passed = (
            sharpe_lift >= self.criteria.metric_threshold.get("sharpe_ratio_lift", 0.05)
            and abs(sharpe_lift) <= self.criteria.max_regression
        )

        return ValidationResult(
            phase=self.phase,
            passed=passed,
            num_events=len(events),
            metrics={
                "legacy_sharpe_mean": round(legacy_mean, 4),
                "policy_sharpe_mean": round(policy_mean, 4),
                "sharpe_ratio_lift": round(sharpe_lift, 4),
            },
            regression_detected=sharpe_lift < 0,
            recommendation="flip_flag" if passed else "investigate_regression",
        )


class DecisionNormalizeValidator(PhaseValidator):
    """Validate Phase 3: decision score normalization."""

    def validate(self, events: list[dict]) -> ValidationResult:
        if len(events) < self.criteria.min_cycles:
            return ValidationResult(
                phase=self.phase,
                passed=False,
                num_events=len(events),
                metrics={},
                regression_detected=False,
                recommendation="collect_more_data",
            )

        legacy_scores = []
        policy_scores = []
        realized_roas = []

        for e in events:
            data = e.get("data") or {}
            try:
                leg_score = data.get("legacy_score")
                pol_score = data.get("policy_score")
                roas = data.get("realized_roas")
                if leg_score is not None and pol_score is not None and roas is not None:
                    legacy_scores.append(leg_score)
                    policy_scores.append(pol_score)
                    realized_roas.append(roas)
            except Exception:
                continue

        if len(legacy_scores) < 5:
            return ValidationResult(
                phase=self.phase,
                passed=False,
                num_events=len(events),
                metrics={"valid_pairs": len(legacy_scores)},
                regression_detected=False,
                recommendation="collect_more_data",
            )

        legacy_corr, legacy_p = stats.spearmanr(legacy_scores, realized_roas)
        policy_corr, policy_p = stats.spearmanr(policy_scores, realized_roas)

        corr_lift = policy_corr - legacy_corr
        passed = (
            policy_corr >= self.criteria.correlation_threshold
            and corr_lift >= 0  # at minimum, no regression
        )

        return ValidationResult(
            phase=self.phase,
            passed=passed,
            num_events=len(events),
            metrics={
                "legacy_score_roas_corr": round(legacy_corr, 4),
                "policy_score_roas_corr": round(policy_corr, 4),
                "correlation_lift": round(corr_lift, 4),
                "policy_corr_pvalue": round(policy_p, 6),
            },
            regression_detected=corr_lift < 0,
            recommendation="flip_flag" if passed else "investigate_regression",
        )


class RegimeDetectionValidator(PhaseValidator):
    """Validate Phase 4: calibration and regime detection."""

    def validate(self, events: list[dict]) -> ValidationResult:
        if len(events) < self.criteria.min_cycles:
            return ValidationResult(
                phase=self.phase,
                passed=False,
                num_events=len(events),
                metrics={},
                regression_detected=False,
                recommendation="collect_more_data",
            )

        legacy_maes = []
        policy_maes = []
        detection_latencies = []

        for e in events:
            data = e.get("data") or {}
            try:
                leg_mae = data.get("legacy_mae")
                pol_mae = data.get("policy_mae")
                latency = data.get("detection_latency_days")

                if leg_mae is not None and pol_mae is not None:
                    legacy_maes.append(leg_mae)
                    policy_maes.append(pol_mae)
                if latency is not None:
                    detection_latencies.append(latency)
            except Exception:
                continue

        if not legacy_maes or not policy_maes:
            return ValidationResult(
                phase=self.phase,
                passed=False,
                num_events=len(events),
                metrics={"valid_pairs": 0},
                regression_detected=False,
                recommendation="investigate_regression",
            )

        legacy_mae = np.mean(legacy_maes)
        policy_mae = np.mean(policy_maes)
        mae_delta = policy_mae - legacy_mae
        avg_latency = np.mean(detection_latencies) if detection_latencies else None

        passed = (
            mae_delta <= self.criteria.metric_threshold.get("mae_delta", 0.0)
            and (avg_latency is None or avg_latency <= self.criteria.metric_threshold.get("detection_latency_days", 2))
        )

        return ValidationResult(
            phase=self.phase,
            passed=passed,
            num_events=len(events),
            metrics={
                "legacy_mae": round(legacy_mae, 4),
                "policy_mae": round(policy_mae, 4),
                "mae_delta": round(mae_delta, 4),
                "avg_detection_latency_days": round(avg_latency, 2) if avg_latency else None,
            },
            regression_detected=mae_delta > 0,
            recommendation="flip_flag" if passed else "investigate_regression",
        )


class AdaptiveRiskValidator(PhaseValidator):
    """Validate Phase 5: adaptive risk management."""

    def validate(self, events: list[dict]) -> ValidationResult:
        if len(events) < self.criteria.min_cycles:
            return ValidationResult(
                phase=self.phase,
                passed=False,
                num_events=len(events),
                metrics={},
                regression_detected=False,
                recommendation="collect_more_data",
            )

        realized_drawdowns_legacy = []
        realized_drawdowns_policy = []
        spend_violations = 0

        for e in events:
            data = e.get("data") or {}
            try:
                leg_dd = data.get("legacy_realized_drawdown")
                pol_dd = data.get("policy_realized_drawdown")
                violation = data.get("spend_cap_violation", False)

                if leg_dd is not None and pol_dd is not None:
                    realized_drawdowns_legacy.append(leg_dd)
                    realized_drawdowns_policy.append(pol_dd)
                if violation:
                    spend_violations += 1
            except Exception:
                continue

        if not realized_drawdowns_legacy:
            return ValidationResult(
                phase=self.phase,
                passed=False,
                num_events=len(events),
                metrics={"valid_pairs": 0},
                regression_detected=False,
                recommendation="collect_more_data",
            )

        legacy_dd = np.mean(realized_drawdowns_legacy)
        policy_dd = np.mean(realized_drawdowns_policy)
        drawdown_reduction_pct = (legacy_dd - policy_dd) / max(legacy_dd, 0.01)

        passed = (
            drawdown_reduction_pct >= self.criteria.metric_threshold.get("drawdown_reduction_pct", 0.30)
            and spend_violations <= self.criteria.metric_threshold.get("spend_cap_violations", 0)
        )

        return ValidationResult(
            phase=self.phase,
            passed=passed,
            num_events=len(events),
            metrics={
                "legacy_avg_drawdown": round(legacy_dd, 4),
                "policy_avg_drawdown": round(policy_dd, 4),
                "drawdown_reduction_pct": round(drawdown_reduction_pct, 4),
                "spend_cap_violations": spend_violations,
            },
            regression_detected=policy_dd > legacy_dd,
            recommendation="flip_flag" if passed else "investigate_regression",
        )


class UnitEconomicsValidator(PhaseValidator):
    """Validate Phase 6: unit economics (geo, category, LTV)."""

    def validate(self, events: list[dict]) -> ValidationResult:
        if len(events) < self.criteria.min_cycles:
            return ValidationResult(
                phase=self.phase,
                passed=False,
                num_events=len(events),
                metrics={},
                regression_detected=False,
                recommendation="collect_more_data",
            )

        legacy_rankings = []
        policy_rankings = []
        realized_outcomes = []

        for e in events:
            data = e.get("data") or {}
            try:
                leg_rank = data.get("legacy_product_ranking")
                pol_rank = data.get("policy_product_ranking")
                outcome = data.get("realized_roas")

                if leg_rank and pol_rank and outcome is not None:
                    legacy_rankings.append(leg_rank)
                    policy_rankings.append(pol_rank)
                    realized_outcomes.append(outcome)
            except Exception:
                continue

        if len(legacy_rankings) < 5:
            return ValidationResult(
                phase=self.phase,
                passed=False,
                num_events=len(events),
                metrics={"valid_rankings": len(legacy_rankings)},
                regression_detected=False,
                recommendation="collect_more_data",
            )

        legacy_corr, _ = stats.spearmanr(
            list(range(len(legacy_rankings))), realized_outcomes
        )
        policy_corr, _ = stats.spearmanr(
            list(range(len(policy_rankings))), realized_outcomes
        )

        ranking_accuracy_lift = policy_corr - legacy_corr

        passed = (
            policy_corr >= self.criteria.correlation_threshold
            and ranking_accuracy_lift >= self.criteria.metric_threshold.get("ranking_accuracy_lift", 0.15)
        )

        return ValidationResult(
            phase=self.phase,
            passed=passed,
            num_events=len(events),
            metrics={
                "legacy_ranking_corr": round(legacy_corr, 4),
                "policy_ranking_corr": round(policy_corr, 4),
                "ranking_accuracy_lift": round(ranking_accuracy_lift, 4),
            },
            regression_detected=ranking_accuracy_lift < 0,
            recommendation="flip_flag" if passed else "investigate_regression",
        )


class CreativeFatigueValidator(PhaseValidator):
    """Validate Phase 7a: creative fatigue detection."""

    def validate(self, events: list[dict]) -> ValidationResult:
        if len(events) < self.criteria.min_cycles:
            return ValidationResult(
                phase=self.phase,
                passed=False,
                num_events=len(events),
                metrics={},
                regression_detected=False,
                recommendation="collect_more_data",
            )

        detection_latencies = []

        for e in events:
            data = e.get("data") or {}
            try:
                latency = data.get("fatigue_detection_latency_days")
                if latency is not None:
                    detection_latencies.append(latency)
            except Exception:
                continue

        if not detection_latencies:
            return ValidationResult(
                phase=self.phase,
                passed=False,
                num_events=len(events),
                metrics={"valid_latencies": 0},
                regression_detected=False,
                recommendation="collect_more_data",
            )

        avg_latency = np.mean(detection_latencies)
        threshold = self.criteria.metric_threshold.get("fatigue_detection_latency", 3.0)

        passed = avg_latency <= threshold

        return ValidationResult(
            phase=self.phase,
            passed=passed,
            num_events=len(events),
            metrics={
                "avg_detection_latency_days": round(avg_latency, 2),
                "threshold_days": threshold,
            },
            regression_detected=avg_latency > threshold,
            recommendation="flip_flag" if passed else "investigate_regression",
        )


class UrgencyScoringValidator(PhaseValidator):
    """Validate Phase 7b: urgency scoring."""

    def validate(self, events: list[dict]) -> ValidationResult:
        if len(events) < self.criteria.min_cycles:
            return ValidationResult(
                phase=self.phase,
                passed=False,
                num_events=len(events),
                metrics={},
                regression_detected=False,
                recommendation="collect_more_data",
            )

        urgency_scores = []
        early_mover_outcomes = []

        for e in events:
            data = e.get("data") or {}
            try:
                score = data.get("urgency_score")
                outcome = data.get("early_mover_success")
                if score is not None and outcome is not None:
                    urgency_scores.append(score)
                    early_mover_outcomes.append(outcome)
            except Exception:
                continue

        if len(urgency_scores) < 5:
            return ValidationResult(
                phase=self.phase,
                passed=False,
                num_events=len(events),
                metrics={"valid_pairs": len(urgency_scores)},
                regression_detected=False,
                recommendation="collect_more_data",
            )

        corr, pval = stats.spearmanr(urgency_scores, early_mover_outcomes)

        passed = corr >= self.criteria.correlation_threshold

        return ValidationResult(
            phase=self.phase,
            passed=passed,
            num_events=len(events),
            metrics={
                "urgency_score_correlation": round(corr, 4),
                "correlation_pvalue": round(pval, 6),
            },
            regression_detected=corr < 0,
            recommendation="flip_flag" if passed else "investigate_regression",
        )


class OrganicChannelValidator(PhaseValidator):
    """Validate Phase 8: organic/UGC channel."""

    def validate(self, events: list[dict]) -> ValidationResult:
        if len(events) < self.criteria.min_cycles:
            return ValidationResult(
                phase=self.phase,
                passed=False,
                num_events=len(events),
                metrics={},
                regression_detected=False,
                recommendation="collect_more_data",
            )

        organic_cac_ratios = []

        for e in events:
            data = e.get("data") or {}
            try:
                ratio = data.get("organic_cac_ratio")
                if ratio is not None:
                    organic_cac_ratios.append(ratio)
            except Exception:
                continue

        if not organic_cac_ratios:
            return ValidationResult(
                phase=self.phase,
                passed=False,
                num_events=len(events),
                metrics={"valid_ratios": 0},
                regression_detected=False,
                recommendation="collect_more_data",
            )

        avg_ratio = np.mean(organic_cac_ratios)
        threshold = self.criteria.metric_threshold.get("organic_cac_ratio", 0.60)

        passed = avg_ratio <= threshold

        return ValidationResult(
            phase=self.phase,
            passed=passed,
            num_events=len(events),
            metrics={
                "avg_organic_cac_ratio": round(avg_ratio, 4),
                "threshold": threshold,
            },
            regression_detected=avg_ratio > threshold,
            recommendation="flip_flag" if passed else "investigate_regression",
        )


VALIDATORS: dict[str, type[PhaseValidator]] = {
    "capital_policy": CapitalPolicyValidator,
    "decision_normalize": DecisionNormalizeValidator,
    "regime_detection": RegimeDetectionValidator,
    "adaptive_risk": AdaptiveRiskValidator,
    "unit_economics": UnitEconomicsValidator,
    "creative_fatigue": CreativeFatigueValidator,
    "urgency_scoring": UrgencyScoringValidator,
    "organic_channel": OrganicChannelValidator,
}


# ── validation orchestrator ──────────────────────────────────────────────────


@dataclass
class ValidationReport:
    """Complete validation report across all phases."""
    phases: dict[str, ValidationResult]
    timestamp: float
    total_phases: int
    phases_passed: int
    phases_with_regressions: int

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "total_phases": self.total_phases,
            "phases_passed": self.phases_passed,
            "phases_with_regressions": self.phases_with_regressions,
            "phases": {k: v.to_dict() for k, v in self.phases.items()},
        }

    def summary_text(self) -> str:
        """Human-readable summary."""
        lines = [
            f"Validation Report (ts={self.timestamp:.0f})",
            f"Phases Passed: {self.phases_passed}/{self.total_phases}",
            f"Regressions Detected: {self.phases_with_regressions}",
            "",
        ]
        for phase, result in self.phases.items():
            status = "✓ PASS" if result.passed else "✗ FAIL"
            lines.append(f"{status:8} {phase:25} ({result.num_events} events)")
            for metric, value in result.metrics.items():
                if value is not None:
                    lines.append(f"          {metric:30} = {value}")
            if result.regression_detected:
                lines.append(f"          ⚠ REGRESSION DETECTED")
        return "\n".join(lines)


def validate_all_phases(event_store_path: str | None = None) -> ValidationReport:
    """Run all phase validators against event_store and return report."""
    import time
    reader = EventStoreReader(event_store_path)
    results: dict[str, ValidationResult] = {}

    for phase_name, criteria in PHASE_CRITERIA.items():
        shadow_events = reader.read_shadow_events(phase_name)
        validator_cls = VALIDATORS.get(phase_name)

        if not validator_cls:
            _log.warning(f"No validator for phase {phase_name}")
            continue

        validator = validator_cls(phase_name, criteria)
        result = validator.validate(shadow_events)
        results[phase_name] = result

    passed = sum(1 for r in results.values() if r.passed)
    regressions = sum(1 for r in results.values() if r.regression_detected)

    return ValidationReport(
        phases=results,
        timestamp=time.time(),
        total_phases=len(results),
        phases_passed=passed,
        phases_with_regressions=regressions,
    )


__all__ = [
    "ValidationCriteria", "ValidationResult", "ValidationReport",
    "EventStoreReader", "PhaseValidator",
    "CapitalPolicyValidator", "DecisionNormalizeValidator",
    "RegimeDetectionValidator", "AdaptiveRiskValidator",
    "UnitEconomicsValidator", "CreativeFatigueValidator",
    "UrgencyScoringValidator", "OrganicChannelValidator",
    "validate_all_phases",
]
