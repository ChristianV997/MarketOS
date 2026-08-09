from backend.discovery.acquisition_plan import EvidenceAcquisitionPlan
from backend.discovery.acquisition_registry import AcquisitionRegistry
from backend.discovery.connector_stubs import get_connector_stub


def test_registry_round_trip_and_filters(tmp_path):
    registry = AcquisitionRegistry(tmp_path / "acq.json")
    plan = EvidenceAcquisitionPlan("p", "w", "source", "generic_market_csv", "t", "o", 50)
    stub = get_connector_stub("generic_market_csv")
    registry.register_plan(plan); registry.register_stub(stub)
    assert registry.list_plans(workspace_id="w")[0].plan_id == "p"
    assert registry.get_stub(stub.connector_name).status == "disabled"


def test_corrupt_registry_is_empty(tmp_path):
    path = tmp_path / "bad.json"; path.write_text("{bad", encoding="utf-8")
    registry = AcquisitionRegistry(path)
    assert registry.list_plans() == [] and registry.list_stubs() == []
