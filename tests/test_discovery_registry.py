from backend.discovery.discovery_registry import DiscoveryRegistry
from backend.discovery.evidence_source_contract import EvidenceRecord


def test_registry_missing_and_corrupt_are_empty(tmp_path):
    registry = DiscoveryRegistry(tmp_path / "missing.json")
    assert registry.list_evidence() == []
    path = tmp_path / "corrupt.json"
    path.write_text("{broken", encoding="utf-8")
    assert DiscoveryRegistry(path).list_evidence() == []


def test_registry_filters_evidence(tmp_path):
    registry = DiscoveryRegistry(tmp_path / "state.json")
    record = EvidenceRecord("e", "local", "fixture", "category", "home", "trend_proxy", .5, 1, .5, 1, {"type": "test"})
    registry.register_evidence([record])
    assert registry.list_evidence(entity_type="category")[0].evidence_id == "e"
