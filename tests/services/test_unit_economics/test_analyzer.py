"""Tests for services.unit_economics.analyzer.run_unit_economics."""
import backend.core.persistence as pers
import pytest
from backend.experiments.audit_log import transitions_for
from backend.experiments.registry import get_experiment_registry
from backend.workspaces.artifact_store import ArtifactStore
from backend.workspaces.client_workspace import ClientWorkspace
from services.unit_economics.analyzer import run_unit_economics
from services.unit_economics.schemas import UnitEconomicsResult


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))


class TestUnitEconomicsAnalyzer:
    def test_returns_result_and_completed_envelope(self):
        result, envelope = run_unit_economics("Widget", supplier_cost=10.0, retail_price=40.0, shipping_cost=2.0)

        assert isinstance(result, UnitEconomicsResult)
        assert result.base_margin["retail_price"] == 40.0
        assert result.break_even_cac > 0
        assert result.verdict in ("profitable", "breakeven", "loss")
        assert envelope.service_name == "unit_economics"
        assert envelope.status == "completed"

    def test_geo_variant_only_populated_when_geo_passed(self):
        without_geo, _ = run_unit_economics("Widget", supplier_cost=10.0, retail_price=40.0)
        with_geo, _ = run_unit_economics("Widget", supplier_cost=10.0, retail_price=40.0, geo="MX")

        assert without_geo.geo_margin is None
        assert with_geo.geo_margin is not None

    def test_envelope_registered_and_retrievable(self):
        _, envelope = run_unit_economics("Widget", supplier_cost=10.0, retail_price=40.0)
        fetched = get_experiment_registry().get(envelope.experiment_id)
        assert fetched is not None
        assert fetched.status == "completed"

    def test_audit_log_transitions_recorded(self):
        _, envelope = run_unit_economics("Widget", supplier_cost=10.0, retail_price=40.0)
        events = {e["event"] for e in transitions_for(envelope)}
        assert {"experiment_created", "experiment_running", "experiment_completed"} <= events

    def test_result_saved_to_artifact_store(self):
        ws = ClientWorkspace(name="own-store")
        result, envelope = run_unit_economics("Widget", supplier_cost=10.0, retail_price=40.0, workspace=ws)
        store = ArtifactStore()
        saved = store.load(ws.workspace_id, envelope.experiment_id, "result.json")
        assert saved == result.to_dict()


class TestUnitEconomicsCrossWorkspaceIsolation:
    def test_two_workspaces_same_product_produce_distinct_experiments_and_paths(self):
        ws_a = ClientWorkspace(name="workspace-a")
        ws_b = ClientWorkspace(name="workspace-b")

        _, env_a = run_unit_economics("Widget", supplier_cost=10.0, retail_price=40.0, workspace=ws_a)
        _, env_b = run_unit_economics("Widget", supplier_cost=10.0, retail_price=40.0, workspace=ws_b)

        assert env_a.experiment_id != env_b.experiment_id

        store = ArtifactStore()
        assert store.path_for(ws_a.workspace_id, env_a.experiment_id, "result.json") != \
               store.path_for(ws_b.workspace_id, env_b.experiment_id, "result.json")


class TestUnitEconomicsNeverRaises:
    def test_never_raises_on_zero_retail_price(self):
        result, envelope = run_unit_economics("Free Sample", supplier_cost=5.0, retail_price=0.0)
        assert result.verdict == "loss"
        assert envelope.status == "completed"

    def test_never_raises_when_margin_calculator_fails(self, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("boom")
        monkeypatch.setattr("backend.validation.margin_calculator.calculate_margin", _boom)
        result, envelope = run_unit_economics("Widget", supplier_cost=10.0, retail_price=40.0)
        assert isinstance(result, UnitEconomicsResult)
        assert envelope.status == "completed"
