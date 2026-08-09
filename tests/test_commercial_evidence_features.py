from backend.commercial_intelligence.evidence_features import EvidenceFeature, EvidenceFeatureSet, extract_evidence_features
from backend.discovery.discovery_registry import DiscoveryRegistry
from backend.discovery.evidence_source_contract import EvidenceRecord
from backend.discovery.opportunity_registry import OpportunityRegistry


def test_feature_extraction_preserves_provenance_and_handles_empty(monkeypatch, tmp_path):
    discovery=DiscoveryRegistry(tmp_path/"discovery.json"); opportunities=OpportunityRegistry(tmp_path/"opp.json")
    discovery.register_evidence([EvidenceRecord("e1","fixture","fixture","category","sleep improvement","trend_proxy",.7,1,.6,1,{"type":"synthetic_fixture","not_real_market_data":True})])
    monkeypatch.setattr("backend.discovery.discovery_registry.get_discovery_registry", lambda: discovery)
    monkeypatch.setattr("backend.discovery.opportunity_registry.get_opportunity_registry", lambda: opportunities)
    features=extract_evidence_features(category="sleep improvement")
    assert features.features[0].provenance["evidence_id"] == "e1"
    assert "synthetic_fixture_not_real_market_data" in features.features[0].limitations
    empty=extract_evidence_features(category="missing")
    assert empty.limitation_summary
    assert EvidenceFeatureSet.from_dict(features.to_dict()).features[0].feature_id == features.features[0].feature_id
