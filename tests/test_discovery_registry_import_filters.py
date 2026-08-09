from backend.discovery.discovery_registry import DiscoveryRegistry
from backend.discovery.evidence_source_contract import EvidenceRecord


def test_imported_evidence_filters(tmp_path):
    registry = DiscoveryRegistry(tmp_path / "discovery.json")
    record = EvidenceRecord("e", "source", "local_file", "category", "Home Fitness", "trend_proxy", .5, 1, .5, 1, {"workspace_id": "w"})
    registry.register_evidence([record])
    assert registry.list_evidence(source_type="local_file", entity_name="home fitness", workspace_id="w")
