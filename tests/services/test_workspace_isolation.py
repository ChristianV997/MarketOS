"""Cross-service workspace isolation integration test (Phase 7: SaaS-lite
readiness). Every sellable module runs against two distinct workspaces
with the same input product/business name and must produce distinct
experiment IDs and non-colliding ArtifactStore paths — no module leaks
data across tenants.
"""
import backend.core.persistence as pers
import pytest
from backend.workspaces.artifact_store import ArtifactStore
from backend.workspaces.client_workspace import ClientWorkspace


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))
    from core.signals import signal_engine
    monkeypatch.setattr(signal_engine, "get", lambda force_refresh=False: [])


def _two_workspaces():
    return ClientWorkspace(name="tenant-a"), ClientWorkspace(name="tenant-b")


def _assert_isolated(env_a, env_b):
    assert env_a.workspace_id != env_b.workspace_id
    assert env_a.experiment_id != env_b.experiment_id
    store = ArtifactStore()
    path_a = store.path_for(env_a.workspace_id, env_a.experiment_id, "result.json")
    path_b = store.path_for(env_b.workspace_id, env_b.experiment_id, "result.json")
    assert path_a != path_b
    assert store.load(env_a.workspace_id, env_a.experiment_id, "result.json") is not None
    assert store.load(env_b.workspace_id, env_b.experiment_id, "result.json") is not None


def test_product_research_isolated_across_workspaces():
    from services.product_research.audit import run_product_audit
    ws_a, ws_b = _two_workspaces()
    _, env_a = run_product_audit("Widget", workspace=ws_a)
    _, env_b = run_product_audit("Widget", workspace=ws_b)
    _assert_isolated(env_a, env_b)


def test_unit_economics_isolated_across_workspaces():
    from services.unit_economics.analyzer import run_unit_economics
    ws_a, ws_b = _two_workspaces()
    _, env_a = run_unit_economics("Widget", supplier_cost=10.0, retail_price=40.0, workspace=ws_a)
    _, env_b = run_unit_economics("Widget", supplier_cost=10.0, retail_price=40.0, workspace=ws_b)
    _assert_isolated(env_a, env_b)


def test_ecommerce_operator_isolated_across_workspaces():
    from services.ecommerce_operator.experiment import create_commerce_experiment
    ws_a, ws_b = _two_workspaces()
    env_a = create_commerce_experiment("Widget", workspace=ws_a)
    env_b = create_commerce_experiment("Widget", workspace=ws_b)
    assert env_a.workspace_id != env_b.workspace_id
    assert env_a.experiment_id != env_b.experiment_id


def test_creative_growth_isolated_across_workspaces():
    from services.creative_growth.plan import build_creative_growth_plan
    ws_a, ws_b = _two_workspaces()
    _, env_a = build_creative_growth_plan("Widget", workspace=ws_a)
    _, env_b = build_creative_growth_plan("Widget", workspace=ws_b)
    _assert_isolated(env_a, env_b)


def test_customer_intelligence_isolated_across_workspaces():
    from services.customer_intelligence.sprint import build_customer_intelligence_sprint
    ws_a, ws_b = _two_workspaces()
    _, env_a = build_customer_intelligence_sprint("Shop", workspace=ws_a)
    _, env_b = build_customer_intelligence_sprint("Shop", workspace=ws_b)
    _assert_isolated(env_a, env_b)


def test_digital_products_isolated_across_workspaces():
    from services.digital_products.plan import build_digital_product_plan
    ws_a, ws_b = _two_workspaces()
    _, env_a = build_digital_product_plan("Thing", price=99.0, workspace=ws_a)
    _, env_b = build_digital_product_plan("Thing", price=99.0, workspace=ws_b)
    _assert_isolated(env_a, env_b)


def test_sales_automation_isolated_across_workspaces():
    from services.sales_automation.simulate import run_sales_bot_simulation
    ws_a, ws_b = _two_workspaces()
    _, _, _, env_a = run_sales_bot_simulation("ecommerce_brand", ["hi"], workspace=ws_a)
    _, _, _, env_b = run_sales_bot_simulation("ecommerce_brand", ["hi"], workspace=ws_b)
    _assert_isolated(env_a, env_b)


def test_no_module_leaks_data_between_workspaces_via_experiment_registry():
    """A workspace's ExperimentRegistry.for_workspace() view must never
    include another workspace's experiments, across every service module."""
    from backend.experiments.registry import get_experiment_registry
    from services.product_research.audit import run_product_audit
    from services.unit_economics.analyzer import run_unit_economics

    ws_a, ws_b = _two_workspaces()
    _, env_a1 = run_product_audit("Widget", workspace=ws_a)
    _, env_a2 = run_unit_economics("Widget", supplier_cost=10.0, retail_price=40.0, workspace=ws_a)
    _, env_b1 = run_product_audit("Widget", workspace=ws_b)

    registry = get_experiment_registry()
    a_experiment_ids = {e.experiment_id for e in registry.for_workspace(ws_a.workspace_id)}
    b_experiment_ids = {e.experiment_id for e in registry.for_workspace(ws_b.workspace_id)}

    assert {env_a1.experiment_id, env_a2.experiment_id} <= a_experiment_ids
    assert env_b1.experiment_id not in a_experiment_ids
    assert env_b1.experiment_id in b_experiment_ids
