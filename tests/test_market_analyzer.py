from backend.commercial_intelligence import market_analyzer
from backend.commercial_intelligence.evidence_features import EvidenceFeatureSet
from backend.commercial_intelligence.intelligence_registry import CommercialIntelligenceRegistry


def test_market_analyzer_persists_thin_report(monkeypatch, tmp_path):
    monkeypatch.setattr(market_analyzer, "extract_evidence_features", lambda *args, **kwargs: EvidenceFeatureSet("fs","default","Features"))
    registry=CommercialIntelligenceRegistry(tmp_path/"ci.json"); monkeypatch.setattr(market_analyzer, "get_commercial_intelligence_registry", lambda: registry)
    report=market_analyzer.analyze_market_category(category_name="home fitness")
    assert report.confidence_score == 0 and registry.get_market_report(report.report_id)
    assert report.recommended_research_questions
