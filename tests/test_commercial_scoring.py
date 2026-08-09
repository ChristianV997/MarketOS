from backend.commercial_intelligence.evidence_features import EvidenceFeature
from backend.commercial_intelligence.scoring import bounded_score, score_evidence_coverage, score_market_attractiveness, score_product_viability


def f(signal, value, confidence=.8, source="csv"):
    return EvidenceFeature(signal, "default", signal, "test", source, "category", "cat", signal, value, value, confidence, provenance={"type":"test"})


def test_scoring_is_bounded_and_confidence_sensitive():
    assert bounded_score(999) == 100 and bounded_score(-2) == 0
    strong=[f("demand",80),f("trend",70),f("competition",20),f("price",60),f("supplier",60)]
    score=score_market_attractiveness(strong); product=score_product_viability(strong)
    assert 0 <= score["score"] <= 100 and 0 <= score["confidence"] <= 1
    assert "creative" in score["missing"]
    synthetic=f("demand",80,1,"fixture"); synthetic.limitations=["synthetic_fixture_not_real_market_data"]
    assert score_market_attractiveness([synthetic])["confidence"] < score_market_attractiveness([f("demand",80)])["confidence"]
    assert 0 <= product["score"] <= 100
