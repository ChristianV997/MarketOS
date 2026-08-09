"""Tests for services.ecommerce_operator.contribution_profit."""
import backend.core.persistence as pers
import pytest
from backend.workspaces.artifact_store import ArtifactStore
from services.ecommerce_operator.contribution_profit import reconcile_contribution_profit
from services.ecommerce_operator.experiment import create_commerce_experiment


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))


class TestReconcileContributionProfit:
    def test_computes_contribution_profit_from_reconciled_not_raw_revenue(self):
        env = create_commerce_experiment("Widget")
        # Platforms self-report 800 total but Shopify ground truth is only 600
        # (over-claiming via overlapping attribution windows) -> reconciled
        # revenue must be scaled down to 600, and contribution_profit must
        # be computed off that 600, not the inflated 800.
        result = reconcile_contribution_profit(
            env, campaign_revenue={"camp1": 500.0, "camp2": 300.0}, ground_truth_revenue=600.0,
            actual_spend=200.0, actual_orders=25, refunds=20.0, supplier_costs=150.0, payment_fees=30.0,
        )

        assert result.actual_revenue_raw == 800.0
        assert result.actual_revenue_reconciled == 600.0
        assert result.contribution_profit == 600.0 - 200.0 - 150.0 - 30.0 - 20.0
        assert round(result.contribution_margin, 4) == round(result.contribution_profit / 600.0, 4)
        assert result.reconciliation["applied"] is True

    def test_no_ground_truth_skips_reconciliation_but_still_computes_profit(self):
        env = create_commerce_experiment("Widget")
        result = reconcile_contribution_profit(
            env, campaign_revenue={"camp1": 500.0}, ground_truth_revenue=None,
            actual_spend=100.0,
        )
        assert result.actual_revenue_reconciled == 500.0
        assert result.reconciliation["applied"] is False

    def test_saved_to_artifact_store_and_envelope_outputs(self):
        env = create_commerce_experiment("Widget")
        result = reconcile_contribution_profit(env, campaign_revenue={"camp1": 100.0}, ground_truth_revenue=100.0)

        store = ArtifactStore()
        saved = store.load(env.workspace_id, env.experiment_id, "contribution_profit.json")
        assert saved == result.to_dict()
        assert env.outputs["contribution_profit_result"] == result.to_dict()
        assert env.actual_spend == 0.0

    def test_never_raises_when_reconcile_revenue_fails(self, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("boom")
        monkeypatch.setattr("backend.metrics.attribution.reconcile_revenue", _boom)
        env = create_commerce_experiment("Widget")

        result = reconcile_contribution_profit(env, campaign_revenue={"camp1": 100.0}, ground_truth_revenue=100.0)
        assert result.actual_revenue_reconciled == 100.0  # degrades to raw total

    def test_zero_revenue_gives_zero_margin_not_division_error(self):
        env = create_commerce_experiment("Widget")
        result = reconcile_contribution_profit(env, campaign_revenue={}, ground_truth_revenue=None)
        assert result.contribution_margin == 0.0
