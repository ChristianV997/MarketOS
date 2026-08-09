from backend.discovery.acquisition_plan import EvidenceAcquisitionPlan
from backend.discovery.connector_stubs import get_connector_stub
from backend.obsidian.sync import sync_acquisition_plan_note, sync_connector_stub_note


def test_acquisition_notes_optional(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    plan = EvidenceAcquisitionPlan("p", "w", "source", "generic_market_csv", "t", "o", 50)
    assert sync_acquisition_plan_note(plan)["status"] == "skipped"
    assert sync_connector_stub_note(get_connector_stub("generic_market_csv"))["status"] == "skipped"
