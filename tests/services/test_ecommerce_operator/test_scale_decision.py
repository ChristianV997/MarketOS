"""Tests for services.ecommerce_operator.scale_decision.make_kill_scale_decision.

Covers every decision value in schemas.DECISIONS and confirms the decision
uses contribution profit, not ROAS alone.
"""
import backend.core.persistence as pers
import pytest
from services.ecommerce_operator.contribution_profit import reconcile_contribution_profit
from services.ecommerce_operator.experiment import create_commerce_experiment
from services.ecommerce_operator.launch_guard import evaluate_launch_readiness
from services.ecommerce_operator.scale_decision import make_kill_scale_decision
from services.ecommerce_operator.schemas import ContributionProfitResult


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))


def _envelope_with_kill_criteria(**kill_criteria):
    return create_commerce_experiment("Widget", kill_criteria=kill_criteria)


class TestBlockedDecision:
    def test_blocked_experiment_yields_blocked_decision(self):
        env = create_commerce_experiment("Widget")  # no prerequisites -> will be blocked
        evaluate_launch_readiness(env)
        contribution = ContributionProfitResult(product_name="Widget")

        decision = make_kill_scale_decision(env, contribution, roas=2.0)

        assert decision.decision == "blocked"


class TestKillDecision:
    def test_negative_contribution_profit_kills_regardless_of_roas(self):
        env = _envelope_with_kill_criteria(min_roas=1.0)
        contribution = ContributionProfitResult(
            product_name="Widget", actual_spend=100.0, contribution_profit=-50.0, contribution_margin=-0.1,
        )
        # High ROAS alone must not save it — this is the "not just ROAS" requirement.
        decision = make_kill_scale_decision(env, contribution, roas=5.0)
        assert decision.decision == "kill"

    def test_auto_kill_raw_signal_kills(self):
        env = _envelope_with_kill_criteria(min_roas=0.5)
        contribution = ContributionProfitResult(
            product_name="Widget", actual_spend=50.0, contribution_profit=10.0, contribution_margin=0.05,
        )
        # spend > 10 and roas < 0.8 triggers agents.auto_kill.should_kill
        decision = make_kill_scale_decision(env, contribution, roas=0.5)
        assert decision.decision == "kill"


class TestIterateOfferDecision:
    def test_low_contribution_margin_iterates_offer_not_creative(self):
        env = _envelope_with_kill_criteria(min_roas=0.5, min_contribution_margin=0.2)
        contribution = ContributionProfitResult(
            product_name="Widget", actual_spend=5.0, contribution_profit=5.0, contribution_margin=0.05,
        )
        decision = make_kill_scale_decision(env, contribution, roas=2.0)
        assert decision.decision == "iterate_offer"


class TestIterateCreativeDecision:
    def test_low_roas_with_good_margin_iterates_creative(self):
        env = _envelope_with_kill_criteria(min_roas=2.0, min_contribution_margin=0.05)
        contribution = ContributionProfitResult(
            product_name="Widget", actual_spend=5.0, contribution_profit=20.0, contribution_margin=0.4,
        )
        decision = make_kill_scale_decision(env, contribution, roas=1.0)
        assert decision.decision == "iterate_creative"


class TestContinueTestDecision:
    def test_insufficient_orders_continues_test(self):
        env = _envelope_with_kill_criteria(min_roas=0.5, min_contribution_margin=0.05)
        contribution = ContributionProfitResult(
            product_name="Widget", actual_spend=5.0, contribution_profit=20.0,
            contribution_margin=0.4, actual_orders=3,
        )
        decision = make_kill_scale_decision(env, contribution, roas=3.0)
        assert decision.decision == "continue_test"


class TestScaleApprovedDecision:
    def test_strong_metrics_and_evidence_scale_approved(self):
        env = _envelope_with_kill_criteria(min_roas=0.5, min_contribution_margin=0.05)
        contribution = ContributionProfitResult(
            product_name="Widget", actual_spend=5.0, contribution_profit=100.0,
            contribution_margin=0.4, actual_orders=25,
        )
        decision = make_kill_scale_decision(env, contribution, roas=3.0)
        assert decision.decision == "scale_approved"


class TestScaleCautiouslyDecision:
    def test_risk_gate_cap_yields_scale_cautiously(self, monkeypatch):
        monkeypatch.setattr(
            "backend.risk.gate.check_spend",
            lambda amount: {"allowed": True, "adjusted_amount": amount / 2, "reason": "daily_cap_reached", "triggered_cap": "daily"},
        )
        env = _envelope_with_kill_criteria(min_roas=0.5, min_contribution_margin=0.05)
        contribution = ContributionProfitResult(
            product_name="Widget", actual_spend=5.0, contribution_profit=100.0,
            contribution_margin=0.4, actual_orders=25,
        )
        decision = make_kill_scale_decision(env, contribution, roas=3.0, proposed_scale_amount=100.0)
        assert decision.decision == "scale_cautiously"


class TestDecisionReasonAndOutputsAndNeverRaises:
    def test_decision_reason_is_nonempty_string(self):
        env = _envelope_with_kill_criteria(min_roas=0.5)
        contribution = ContributionProfitResult(product_name="Widget", contribution_profit=10.0)
        decision = make_kill_scale_decision(env, contribution, roas=1.0)
        assert isinstance(decision.decision_reason, str) and decision.decision_reason

    def test_decision_recorded_on_envelope_outputs(self):
        env = _envelope_with_kill_criteria(min_roas=0.5)
        contribution = ContributionProfitResult(product_name="Widget", contribution_profit=10.0, actual_orders=25)
        decision = make_kill_scale_decision(env, contribution, roas=3.0)
        assert env.outputs["scale_decision"] == decision.to_dict()

    def test_never_raises_when_auto_kill_check_fails(self, monkeypatch):
        monkeypatch.setattr("agents.auto_kill.should_kill", lambda event: (_ for _ in ()).throw(RuntimeError("boom")))
        env = _envelope_with_kill_criteria(min_roas=0.5)
        contribution = ContributionProfitResult(product_name="Widget", contribution_profit=10.0, actual_orders=25)
        decision = make_kill_scale_decision(env, contribution, roas=3.0)
        assert decision.decision in (
            "kill", "iterate_offer", "iterate_creative", "continue_test", "scale_cautiously", "scale_approved",
        )
