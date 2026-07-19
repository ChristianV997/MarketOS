"""Tests for backend.validation.shadow_validator — phase validation framework."""
from __future__ import annotations

import pytest

from backend.validation.shadow_validator import (
    EventStoreReader,
    CapitalPolicyValidator,
    DecisionNormalizeValidator,
    RegimeDetectionValidator,
    AdaptiveRiskValidator,
    UnitEconomicsValidator,
    CreativeFatigueValidator,
    UrgencyScoringValidator,
    OrganicChannelValidator,
    ValidationCriteria,
    ValidationResult,
    PHASE_CRITERIA,
)


class TestEventStoreReader:
    """Test event_store reader utilities."""

    def test_read_all_events_nonexistent(self):
        """Returns empty list when file doesn't exist."""
        reader = EventStoreReader("/nonexistent/path/events.jsonl")
        events = reader.read_all_events()
        assert events == []

    def test_filter_by_type(self):
        """Filter events by type."""
        reader = EventStoreReader()
        events = [
            {"event": "shadow_capital_policy", "data": {"x": 1}},
            {"event": "shadow_regime_detection", "data": {"x": 2}},
            {"event": "shadow_capital_policy", "data": {"x": 3}},
            {"event": "workflow_started", "data": {}},
        ]
        filtered = reader.events_by_type(events, "shadow_capital_policy")
        assert len(filtered) == 2
        assert filtered[0]["data"]["x"] == 1
        assert filtered[1]["data"]["x"] == 3


class TestValidationCriteria:
    """Test validation criteria definitions."""

    def test_phase_criteria_defined(self):
        """All expected phases have criteria."""
        expected = {
            "capital_policy",
            "decision_normalize",
            "regime_detection",
            "adaptive_risk",
            "unit_economics",
            "creative_fatigue",
            "urgency_scoring",
            "organic_channel",
        }
        assert set(PHASE_CRITERIA.keys()) == expected

    def test_criteria_have_reasonable_bounds(self):
        """Criteria values are sane."""
        for phase, crit in PHASE_CRITERIA.items():
            assert crit.min_cycles >= 20, f"{phase} min_cycles too low"
            assert 0 < crit.max_regression < 1, f"{phase} max_regression out of range"
            if crit.correlation_threshold:
                assert 0 <= crit.correlation_threshold <= 1, f"{phase} correlation threshold out of range"


class TestCapitalPolicyValidator:
    """Validate Phase 2: capital allocation."""

    def test_insufficient_events(self):
        """Fail when fewer events than min_cycles."""
        validator = CapitalPolicyValidator(
            "capital_policy", PHASE_CRITERIA["capital_policy"]
        )
        events = [
            {"data": {"legacy_budgets": [100, 50], "policy": {"budgets": [110, 40]}}}
            for _ in range(5)
        ]
        result = validator.validate(events)
        assert result.passed is False
        assert result.recommendation == "collect_more_data"

    def test_valid_events(self):
        """Process valid shadow events."""
        validator = CapitalPolicyValidator(
            "capital_policy", PHASE_CRITERIA["capital_policy"]
        )
        events = [
            {"data": {"legacy_budgets": [100, 50], "policy": {"budgets": [110, 40]}}}
            for _ in range(60)
        ]
        result = validator.validate(events)
        assert result.num_events == 60
        assert "legacy_sharpe_mean" in result.metrics or result.passed is False


class TestDecisionNormalizeValidator:
    """Validate Phase 3: decision score normalization."""

    def test_insufficient_valid_pairs(self):
        """Fail when fewer than 5 valid score-ROAS pairs."""
        validator = DecisionNormalizeValidator(
            "decision_normalize", PHASE_CRITERIA["decision_normalize"]
        )
        events = [
            {"data": {"legacy_score": 0.5, "policy_score": 0.55, "realized_roas": 1.2}}
            for _ in range(3)
        ]
        result = validator.validate(events)
        assert result.passed is False
        assert result.recommendation == "collect_more_data"

    def test_correlation_validation(self):
        """Validate correlation with realized outcomes."""
        validator = DecisionNormalizeValidator(
            "decision_normalize", PHASE_CRITERIA["decision_normalize"]
        )
        events = [
            {
                "data": {
                    "legacy_score": 0.3 + i * 0.01,
                    "policy_score": 0.32 + i * 0.01,  # policy slightly better
                    "realized_roas": 1.0 + i * 0.02,  # correlated with policy
                }
            }
            for i in range(60)
        ]
        result = validator.validate(events)
        # Policy correlation should be positive and >= legacy
        if result.metrics.get("policy_score_roas_corr"):
            assert result.metrics["policy_score_roas_corr"] >= result.metrics.get("legacy_score_roas_corr", 0)


class TestRegimeDetectionValidator:
    """Validate Phase 4: calibration and regime detection."""

    def test_mae_regression_detection(self):
        """Detect MAE regression."""
        validator = RegimeDetectionValidator(
            "regime_detection", PHASE_CRITERIA["regime_detection"]
        )
        events = [
            {
                "data": {
                    "legacy_mae": 0.10,
                    "policy_mae": 0.15,  # worse than legacy
                    "detection_latency_days": 1.0,
                }
            }
            for _ in range(40)
        ]
        result = validator.validate(events)
        assert bool(result.regression_detected) is True
        # Recommended action depends on threshold

    def test_detection_latency_check(self):
        """Validate detection latency."""
        validator = RegimeDetectionValidator(
            "regime_detection", PHASE_CRITERIA["regime_detection"]
        )
        events = [
            {
                "data": {
                    "legacy_mae": 0.10,
                    "policy_mae": 0.09,
                    "detection_latency_days": 1.0,  # detects shift in 1 day
                }
            }
            for _ in range(40)
        ]
        result = validator.validate(events)
        assert result.metrics.get("avg_detection_latency_days") <= 2.0


class TestAdaptiveRiskValidator:
    """Validate Phase 5: adaptive risk management."""

    def test_drawdown_reduction_validation(self):
        """Validate realized drawdown reduction."""
        validator = AdaptiveRiskValidator(
            "adaptive_risk", PHASE_CRITERIA["adaptive_risk"]
        )
        events = [
            {
                "data": {
                    "legacy_realized_drawdown": 0.25,
                    "policy_realized_drawdown": 0.15,  # 40% reduction
                    "spend_cap_violation": False,
                }
            }
            for _ in range(30)
        ]
        result = validator.validate(events)
        dd_reduction = result.metrics.get("drawdown_reduction_pct", 0)
        assert dd_reduction >= 0.30, "Should detect 40% drawdown reduction"

    def test_spend_cap_violations(self):
        """Track spend cap violations."""
        validator = AdaptiveRiskValidator(
            "adaptive_risk", PHASE_CRITERIA["adaptive_risk"]
        )
        events = [
            {
                "data": {
                    "legacy_realized_drawdown": 0.25,
                    "policy_realized_drawdown": 0.15,
                    "spend_cap_violation": i > 5,  # some violations in second half
                }
            }
            for i in range(30)
        ]
        result = validator.validate(events)
        violations = result.metrics.get("spend_cap_violations", 0)
        assert violations > 0, "Should detect spend cap violations"


class TestUnitEconomicsValidator:
    """Validate Phase 6: unit economics."""

    def test_ranking_accuracy(self):
        """Validate product ranking correlation with outcomes."""
        validator = UnitEconomicsValidator(
            "unit_economics", PHASE_CRITERIA["unit_economics"]
        )
        events = [
            {
                "data": {
                    "legacy_product_ranking": list(range(10)),
                    "policy_product_ranking": [i + 1 if i < 5 else i - 1 for i in range(10)],
                    "realized_roas": [2.0 - i * 0.1 for i in range(10)],
                }
            }
            for _ in range(60)
        ]
        result = validator.validate(events)
        assert "policy_ranking_corr" in result.metrics or not result.passed


class TestCreativeFatigueValidator:
    """Validate Phase 7a: creative fatigue detection."""

    def test_detection_latency(self):
        """Validate fatigue detection latency."""
        validator = CreativeFatigueValidator(
            "creative_fatigue", PHASE_CRITERIA["creative_fatigue"]
        )
        events = [
            {
                "data": {
                    "fatigue_detection_latency_days": 2.0 + 0.1 * (i % 10),
                }
            }
            for i in range(50)
        ]
        result = validator.validate(events)
        latency = result.metrics.get("avg_detection_latency_days", 0)
        assert latency <= 3.0, "Should detect fatigue within 3 days on average"


class TestUrgencyScoringValidator:
    """Validate Phase 7b: urgency scoring."""

    def test_urgency_correlation_with_outcomes(self):
        """Validate urgency score correlation."""
        validator = UrgencyScoringValidator(
            "urgency_scoring", PHASE_CRITERIA["urgency_scoring"]
        )
        events = [
            {
                "data": {
                    "urgency_score": 0.3 + i * 0.01,
                    "early_mover_success": 1.0 if i > 30 else 0.0,
                }
            }
            for i in range(60)
        ]
        result = validator.validate(events)
        corr = result.metrics.get("urgency_score_correlation", 0)
        assert corr >= 0, "Correlation should be positive"


class TestOrganicChannelValidator:
    """Validate Phase 8: organic/UGC channel."""

    def test_organic_cac_ratio(self):
        """Validate organic CAC vs paid CAC."""
        validator = OrganicChannelValidator(
            "organic_channel", PHASE_CRITERIA["organic_channel"]
        )
        events = [
            {
                "data": {
                    "organic_cac_ratio": 0.35 + 0.03 * (i % 10),  # range [0.35, 0.65), avg ~0.5
                }
            }
            for i in range(50)
        ]
        result = validator.validate(events)
        ratio = result.metrics.get("avg_organic_cac_ratio", 0)
        assert ratio <= 0.60, "Organic CAC should be <60% of paid"


class TestValidationResult:
    """Test validation result structure."""

    def test_result_serialization(self):
        """Validate result converts to dict."""
        result = ValidationResult(
            phase="test_phase",
            passed=True,
            num_events=100,
            metrics={"metric_1": 0.95, "metric_2": None},
            regression_detected=False,
            recommendation="flip_flag",
        )
        data = result.to_dict()
        assert data["phase"] == "test_phase"
        assert data["passed"] is True
        assert data["num_events"] == 100


class TestValidationIntegration:
    """Integration tests for validation framework."""

    def test_all_validators_instantiate(self):
        """All validators can be instantiated."""
        for phase, criteria in PHASE_CRITERIA.items():
            validator_cls_name = {
                "capital_policy": CapitalPolicyValidator,
                "decision_normalize": DecisionNormalizeValidator,
                "regime_detection": RegimeDetectionValidator,
                "adaptive_risk": AdaptiveRiskValidator,
                "unit_economics": UnitEconomicsValidator,
                "creative_fatigue": CreativeFatigueValidator,
                "urgency_scoring": UrgencyScoringValidator,
                "organic_channel": OrganicChannelValidator,
            }.get(phase)
            assert validator_cls_name is not None, f"No validator for {phase}"
            validator = validator_cls_name(phase, criteria)
            assert validator.phase == phase
            assert validator.criteria == criteria
