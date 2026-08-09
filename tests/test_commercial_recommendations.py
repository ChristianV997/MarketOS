from backend.commercial_intelligence.recommendations import build_market_research_questions, build_product_validation_tests, build_recommended_imports_from_intelligence
from backend.commercial_intelligence.market_models import MarketAttractivenessReport
from backend.commercial_intelligence.product_models import ProductViabilityReport


def test_recommendations_are_manual_and_evidence_targeted():
    market=MarketAttractivenessReport("m","default","cat","Market",missing_evidence=["supplier"])
    product=ProductViabilityReport("p","default","tool","cat","Product",missing_evidence=["margin"])
    assert "supplier" in build_market_research_questions(market)[0]
    assert build_product_validation_tests(product)[0]["safety"].startswith("No live")
    assert build_recommended_imports_from_intelligence(product)[0]["signal_type"] == "margin"
