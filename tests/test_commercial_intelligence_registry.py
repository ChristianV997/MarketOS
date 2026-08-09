from backend.commercial_intelligence.intelligence_registry import CommercialIntelligenceRegistry
from backend.commercial_intelligence.market_models import MarketAttractivenessReport


def test_intelligence_registry_persists_and_filters(tmp_path):
    r=CommercialIntelligenceRegistry(tmp_path/"ci.json"); report=MarketAttractivenessReport("m","ws","cat","Market"); r.register_market_report(report)
    loaded=CommercialIntelligenceRegistry(tmp_path/"ci.json")
    assert loaded.latest_market_report("ws","cat").report_id == "m"
