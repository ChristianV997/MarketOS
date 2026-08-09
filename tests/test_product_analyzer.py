from backend.commercial_intelligence import product_analyzer
from backend.commercial_intelligence.evidence_features import EvidenceFeatureSet
from backend.commercial_intelligence.intelligence_registry import CommercialIntelligenceRegistry
from backend.commercial_intelligence.market_models import MarketAttractivenessReport


def test_product_analyzer_generates_positioning_and_tests(monkeypatch, tmp_path):
    monkeypatch.setattr(product_analyzer, "extract_evidence_features", lambda *args, **kwargs: EvidenceFeatureSet("fs","default","Features"))
    monkeypatch.setattr(product_analyzer, "analyze_market_category", lambda *args, **kwargs: MarketAttractivenessReport("m","default","cat","Market"))
    registry=CommercialIntelligenceRegistry(tmp_path/"ci.json"); monkeypatch.setattr(product_analyzer, "get_commercial_intelligence_registry", lambda: registry)
    report=product_analyzer.analyze_product_viability(product_name="Recovery tool",category_name="wellness")
    assert report.positioning.metadata["hypothesis_only"] and report.recommended_validation_tests and report.missing_evidence
    assert registry.get_product_report(report.report_id)
