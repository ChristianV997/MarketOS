"""Tests for services.customer_intelligence.sprint.build_customer_intelligence_sprint."""
import backend.core.persistence as pers
import pytest
from backend.workspaces.artifact_store import ArtifactStore
from services.customer_intelligence.sprint import CustomerIntelligenceSprint, build_customer_intelligence_sprint


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))


def test_returns_result_and_completed_envelope():
    result, envelope = build_customer_intelligence_sprint("clinic", vertical="clinic_wellness")
    assert isinstance(result, CustomerIntelligenceSprint)
    assert result.vertical_playbook is not None
    assert envelope.service_name == "customer_intelligence"
    assert envelope.status == "completed"


def test_no_vertical_means_no_playbook():
    result, _ = build_customer_intelligence_sprint("shop", vertical=None)
    assert result.vertical_playbook is None


def test_saved_to_artifact_store():
    result, envelope = build_customer_intelligence_sprint("clinic", vertical="clinic_wellness")
    store = ArtifactStore()
    saved = store.load(envelope.workspace_id, envelope.experiment_id, "result.json")
    assert saved == result.to_dict()
