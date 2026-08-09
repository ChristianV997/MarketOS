from backend.discovery.evidence_source_contract import EvidenceRecord, EvidenceSourceCapability, EvidenceSourceRegistry


def test_source_safety_and_provenance():
    registry = EvidenceSourceRegistry(":memory:")
    registry.register_source(EvidenceSourceCapability("safe", "fixture", True, False, False, False, True, "static"))
    registry.register_source(EvidenceSourceCapability("live", "external_live", True, True, True, False, False, "live_unavailable"))
    assert registry.validate_source_safe("safe")["allowed"] is True
    assert registry.validate_source_safe("live")["allowed"] is False
    record = EvidenceRecord("e", "safe", "fixture", "category", "x", "trend_proxy", .5, 1, .5, 1, {"type": "test"})
    assert record.to_dict()["provenance"]["type"] == "test"
