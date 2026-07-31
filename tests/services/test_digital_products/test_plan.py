"""Tests for services.digital_products.plan.build_digital_product_plan."""
import backend.core.persistence as pers
import pytest
from backend.workspaces.artifact_store import ArtifactStore
from services.digital_products.plan import build_digital_product_plan
from services.digital_products.schemas import DigitalProductPlan


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))


def test_returns_plan_and_completed_envelope():
    plan, envelope = build_digital_product_plan(
        "My Playbook", target_customer="marketers", price=99.0, target_buyers=5, has_existing_audience=True,
    )
    assert isinstance(plan, DigitalProductPlan)
    assert plan.offer["offer_name"] == "My Playbook"
    assert plan.validation["verdict"] == "strong"
    assert plan.launch_checklist
    assert plan.margin
    assert plan.margin["retail_price"] == 99.0
    assert envelope.service_name == "digital_products"
    assert envelope.status == "completed"


def test_saved_to_artifact_store():
    plan, envelope = build_digital_product_plan("Thing", price=99.0)
    store = ArtifactStore()
    saved = store.load(envelope.workspace_id, envelope.experiment_id, "result.json")
    assert saved == plan.to_dict()


def test_decision_criteria_present():
    plan, _ = build_digital_product_plan("Thing", price=99.0)
    assert {"kill", "iterate", "scale"} <= plan.decision_criteria.keys()
