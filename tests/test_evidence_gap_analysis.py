from backend.discovery.discovery_registry import DiscoveryRegistry
from backend.discovery.evidence_gap import analyze_evidence_gaps
from backend.discovery.evidence_source_contract import EvidenceRecord


def test_no_evidence_produces_actionable_gaps(monkeypatch, tmp_path):
    import backend.discovery.evidence_gap as module
    registry = DiscoveryRegistry(tmp_path / "discovery.json")
    monkeypatch.setattr(module, "get_discovery_registry", lambda: registry)
    result = analyze_evidence_gaps(top_n=10)
    assert result.gaps and result.gaps[0].recommended_parser_types
    assert all(0 <= gap.priority_score <= 100 for gap in result.gaps)


def test_missing_margin_recommends_supplier(monkeypatch, tmp_path):
    import backend.discovery.evidence_gap as module
    registry = DiscoveryRegistry(tmp_path / "discovery.json")
    registry.register_evidence([EvidenceRecord("e", "fixture", "fixture", "category", "home fitness", "trend_proxy", .5, 1, .2, 1, {"not_real_market_data": True})])
    monkeypatch.setattr(module, "get_discovery_registry", lambda: registry)
    result = analyze_evidence_gaps(top_n=100)
    gap = next(item for item in result.gaps if item.missing_signal_type == "margin_proxy")
    assert "supplier_catalog_csv" in gap.recommended_parser_types
    assert result.evidence_coverage["synthetic_only"] is True
