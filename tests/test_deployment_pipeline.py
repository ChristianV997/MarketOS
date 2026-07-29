"""Comprehensive tests for Phase 7-8 deployment pipeline.

Tests cover:
1. Staging validation (old vs new logic comparison)
2. Shadow-mode tracking and journaling
3. Organic channel expansion (affiliate networks)
4. End-to-end deployment workflow

(Feature flag management tests were removed when
backend/deployment/feature_flags.py was retired as Tier 2 — it was a
second, independent flag-bookkeeping system whose 6 PHASE7_*/PHASE8_*_LIVE
flags were never actually consulted by any real code path; each flag it
tracked already has its own ad-hoc os.getenv(...) gate directly in the
module that uses it — see core/creative/selection.py, core/portfolio.py,
simulation/engine.py, orchestrator/main.py — which is the one real
deployment mechanism this codebase actually uses.)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from backend.deployment.shadow_mode import ShadowModeController, shadow_record_decision, shadow_record_outcome
from backend.integrations.affiliate_networks import AffiliateNetwork, OrganicChannelExpander
from backend.staging.validator import StagingValidator, ValidationReport


class TestStagingValidator:
    """Test staging validation framework."""

    def test_validator_initialization(self):
        """Test StagingValidator initialization."""
        validator = StagingValidator()
        assert validator.metrics is not None

    @pytest.mark.asyncio
    async def test_validate_decision_quality(self):
        """Test full staging validation workflow."""
        validator = StagingValidator()
        report = await validator.validate_decision_quality(num_samples=50)

        assert isinstance(report, ValidationReport)
        assert report.scenarios_tested == 50
        assert report.scenarios_agreement >= 0
        assert report.rank_accuracy_baseline >= 0.0
        assert report.rank_accuracy_phase78 >= 0.0

    @pytest.mark.asyncio
    async def test_synthetic_scenario_generation(self):
        """Test synthetic scenario generation for MVP."""
        validator = StagingValidator()
        scenarios = validator._generate_synthetic_scenarios(num_samples=10)

        assert len(scenarios) == 10
        for scenario in scenarios:
            assert "score" in scenario
            assert "velocity" in scenario
            assert "saturation" in scenario
            assert "realized_roas" in scenario
            assert 0 <= scenario["score"] <= 1
            assert 0 <= scenario["velocity"] <= 1

    @pytest.mark.asyncio
    async def test_validation_report_recommendation(self):
        """Test validation report generates correct recommendation."""
        validator = StagingValidator()
        report = await validator.validate_decision_quality(num_samples=30)

        # Report should have a recommendation
        assert report.recommendation in ["APPROVE", "NEEDS_ITERATION", "REJECT"]

    def test_validation_report_summary(self):
        """Test validation report generates readable summary."""
        report = ValidationReport(
            validation_period=(datetime.now(timezone.utc), datetime.now(timezone.utc)),
            scenarios_tested=100,
            rank_accuracy_baseline=0.75,
            rank_accuracy_phase78=0.82,
            recommendation="APPROVE",
        )

        summary = report.summary()
        assert "Staging Validation Report" in summary
        assert "APPROVE" in summary
        assert "100" in summary  # scenarios tested


class TestShadowMode:
    """Test shadow-mode decision tracking and validation."""

    def test_shadow_controller_initialization(self):
        """Test ShadowModeController initialization."""
        controller = ShadowModeController()
        assert controller.shadow_decisions is not None
        assert "accuracy_threshold" in controller.validation_gates

    def test_record_shadow_decision(self):
        """Test recording a shadow decision."""
        controller = ShadowModeController()

        shadow = controller.record_shadow_decision(
            decision_type="creative_score",
            baseline_decision="launch",
            baseline_score=0.75,
            baseline_confidence=0.6,
            new_decision="launch",
            new_score=0.78,
            new_confidence=0.7,
            product_id="product_123",
        )

        assert shadow.decision_type == "creative_score"
        assert shadow.baseline_score == 0.75
        assert shadow.new_score == 0.78
        assert shadow.product_id == "product_123"

    def test_record_outcome(self):
        """Test recording outcome for shadow decision."""
        controller = ShadowModeController()

        shadow = controller.record_shadow_decision(
            decision_type="creative_score",
            baseline_decision="launch",
            baseline_score=0.75,
            baseline_confidence=0.6,
            new_decision="launch",
            new_score=0.78,
            new_confidence=0.7,
        )

        # Find shadow ID
        shadow_id = list(controller.shadow_decisions.keys())[0]

        # Record outcome
        controller.record_outcome(shadow_id, realized_roas=0.80)

        # Verify outcome recorded
        updated_shadow = controller.shadow_decisions[shadow_id]
        assert updated_shadow.outcome_realized is not None
        assert updated_shadow.outcome_realized["roas"] == 0.80

    def test_validation_gate_insufficient_samples(self):
        """Test validation gate with insufficient samples."""
        controller = ShadowModeController()

        # Add only 5 decisions (gate requires 50)
        for i in range(5):
            controller.record_shadow_decision(
                decision_type="urgency_rank",
                baseline_decision=f"rank_{i}",
                baseline_score=0.5,
                baseline_confidence=0.6,
                new_decision=f"rank_{i}",
                new_score=0.55,
                new_confidence=0.7,
            )

        passes, reason = controller.check_validation_gate("urgency_rank")
        assert passes is False
        assert "Insufficient samples" in reason

    def test_shadow_convenience_functions(self):
        """Test convenience wrapper functions."""
        shadow_id = shadow_record_decision(
            decision_type="urgency_rank",
            baseline_decision="launch",
            baseline_score=0.7,
            baseline_confidence=0.6,
            new_decision="launch",
            new_score=0.75,
            new_confidence=0.7,
            product_id="product_test",
        )

        assert isinstance(shadow_id, str)
        assert len(shadow_id) == 16  # MD5 first 16 chars

        # Record outcome
        shadow_record_outcome(shadow_id, realized_roas=0.78)


class TestAffiliateNetworks:
    """Test affiliate network integration for organic channel expansion."""

    @pytest.mark.asyncio
    async def test_affiliate_network_connector_initialization(self):
        """Test AffiliateNetworkConnector initialization."""
        from backend.integrations.affiliate_networks import AffiliateNetworkConnector

        connector = AffiliateNetworkConnector(AffiliateNetwork.IMPACT, dry_run=True)
        assert connector.network == AffiliateNetwork.IMPACT
        assert connector.dry_run is True

    @pytest.mark.asyncio
    async def test_fetch_performance_dry_run(self):
        """Test fetching performance data in dry-run mode."""
        from backend.integrations.affiliate_networks import AffiliateNetworkConnector

        connector = AffiliateNetworkConnector(AffiliateNetwork.REFERSION, dry_run=True)
        performance = await connector.fetch_performance("product_1", days=30)

        assert len(performance) > 0
        for perf in performance:
            assert perf.product_id == "product_1"
            assert perf.clicks > 0
            assert perf.conversions > 0
            assert perf.roas > 0

    @pytest.mark.asyncio
    async def test_organic_channel_expander_initialization(self):
        """Test OrganicChannelExpander initialization."""
        expander = OrganicChannelExpander(dry_run=True)
        assert len(expander.connectors) == len(AffiliateNetwork)

    @pytest.mark.asyncio
    async def test_evaluate_product_for_affiliate_scaling(self):
        """Test product evaluation for affiliate scaling."""
        expander = OrganicChannelExpander(dry_run=True)

        result = await expander.evaluate_product_for_affiliate_scaling(
            product_id="product_1",
            current_organic_cac=20.0,
            paid_cac=50.0,
        )

        assert result["product_id"] == "product_1"
        assert result["recommendation"] in ["HOLD", "SCALE"]
        assert "qualified_networks" in result

    @pytest.mark.asyncio
    async def test_recruit_on_qualified_networks(self):
        """Test recruitment submission on qualified networks."""
        expander = OrganicChannelExpander(dry_run=True)

        qualified_networks = [
            {
                "network": "impact",
                "affiliate_count": 3,
                "avg_roas": 3.0,
                "avg_affiliate_cac": 15.0,
            }
        ]

        result = await expander.recruit_on_qualified_networks(
            product_id="product_1",
            qualified_networks=qualified_networks,
        )

        assert result["product_id"] == "product_1"
        assert "networks_recruited" in result

    @pytest.mark.asyncio
    async def test_end_to_end_organic_scaling(self):
        """Test end-to-end organic channel scaling."""
        from backend.integrations.affiliate_networks import evaluate_and_scale_organic_channel

        result = await evaluate_and_scale_organic_channel(
            product_ids=["product_1", "product_2"],
            current_organic_cac=20.0,
            paid_cac=50.0,
        )

        assert "evaluated" in result
        assert "recruited" in result
        assert len(result["evaluated"]) == 2


class TestEndToEndDeploymentWorkflow:
    """Integration tests for complete deployment pipeline."""

    @pytest.mark.asyncio
    async def test_staging_to_production_workflow(self):
        """Test full staging validation → shadow-mode → production workflow."""
        # Step 1: Staging validation
        validator = StagingValidator()
        validation_report = await validator.validate_decision_quality(num_samples=50)
        assert validation_report.recommendation in ["APPROVE", "NEEDS_ITERATION"]

        # Step 2: Shadow-mode tracking
        controller = ShadowModeController()
        controller.record_shadow_decision(
            decision_type="urgency_rank",
            baseline_decision="launch",
            baseline_score=0.7,
            baseline_confidence=0.6,
            new_decision="launch",
            new_score=0.75,
            new_confidence=0.7,
            product_id="product_staging_test",
        )

        # Record outcome
        first_shadow_id = list(controller.shadow_decisions.keys())[0]
        controller.record_outcome(first_shadow_id, realized_roas=0.76)

    @pytest.mark.asyncio
    async def test_organic_channel_production_integration(self):
        """Test organic channel integrated into production workflow."""
        # Evaluate products for organic scaling
        expander = OrganicChannelExpander(dry_run=True)
        eval_result = await expander.evaluate_product_for_affiliate_scaling(
            product_id="product_prod_test",
            current_organic_cac=20.0,
            paid_cac=50.0,
        )

        # If qualified, recruit
        if eval_result["recommendation"] == "SCALE":
            recruit_result = await expander.recruit_on_qualified_networks(
                product_id="product_prod_test",
                qualified_networks=eval_result["qualified_networks"],
            )

            assert recruit_result["product_id"] == "product_prod_test"
            assert "networks_recruited" in recruit_result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
