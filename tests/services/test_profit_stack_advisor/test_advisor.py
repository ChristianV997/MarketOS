"""Tests for services.profit_stack_advisor.advisor.run_profit_stack_advisor."""
import backend.core.persistence as pers
import pytest
from backend.experiments.audit_log import transitions_for
from backend.experiments.registry import get_experiment_registry
from backend.workspaces.artifact_store import ArtifactStore
from backend.workspaces.client_workspace import ClientWorkspace
from services.profit_stack_advisor.advisor import run_profit_stack_advisor
from services.profit_stack_advisor.schemas import ProfitStackAdvisorResult


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))


class TestProfitStackAdvisor:
    def test_returns_result_and_completed_envelope(self):
        result, envelope = run_profit_stack_advisor(
            "Own Store", business_model="own_ecommerce", expected_monthly_revenue=5000.0, supplier_cost=10.0, retail_price=35.0,
        )
        assert isinstance(result, ProfitStackAdvisorResult)
        assert result.recommendation["commerce_provider_recommendation"]["provider_id"] == "woocommerce"
        assert envelope.service_name == "profit_stack_advisor"
        assert envelope.status == "completed"

    def test_cost_comparison_populated_for_reachable_low_cost_strategy(self):
        result, _ = run_profit_stack_advisor("Own Store", business_model="own_ecommerce", supplier_cost=10.0, retail_price=35.0)
        assert result.cost_comparison is not None
        assert len(result.cost_comparison["stacks"]) == 2

    def test_lead_gen_strategy_completes_without_ecommerce_cost_comparison(self):
        result, envelope = run_profit_stack_advisor("Agency", business_model="agency_white_label_fast", expected_monthly_revenue=20000.0)
        assert envelope.status == "completed"
        assert result.recommendation["status"] == "recommended"
        assert result.recommendation["crm_provider_recommendation"]["provider_id"] == "gohighlevel"
        assert result.cost_comparison is None

    def test_envelope_registered_and_retrievable(self):
        _, envelope = run_profit_stack_advisor("Own Store", business_model="own_ecommerce")
        fetched = get_experiment_registry().get(envelope.experiment_id)
        assert fetched is not None
        assert fetched.status == "completed"

    def test_audit_log_transitions_recorded(self):
        _, envelope = run_profit_stack_advisor("Own Store", business_model="own_ecommerce")
        events = {e["event"] for e in transitions_for(envelope)}
        assert {"experiment_created", "experiment_running", "experiment_completed"} <= events

    def test_result_saved_to_artifact_store(self):
        ws = ClientWorkspace(name="own-store")
        result, envelope = run_profit_stack_advisor("Own Store", business_model="own_ecommerce", workspace=ws)
        store = ArtifactStore()
        saved = store.load(ws.workspace_id, envelope.experiment_id, "result.json")
        assert saved == result.to_dict()


class TestProfitStackAdvisorNeverRaises:
    def test_never_raises_when_stack_planner_fails(self, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("boom")
        monkeypatch.setattr("backend.stack_planner.planner.recommend_stack", _boom)
        result, envelope = run_profit_stack_advisor("Own Store", business_model="own_ecommerce")
        assert isinstance(result, ProfitStackAdvisorResult)
        assert result.recommendation == {}
        assert envelope.status == "completed"
