from backend.creative_intelligence.creative_models import CreativeAngle, CreativeIntelligenceReport

def test_creative_models_bound_and_markdown():
    angle=CreativeAngle("a","w","p","c","o","education","t","draft","buyer","motivation","objection",score=200,confidence=2)
    report=CreativeIntelligenceReport("r","w","p","c","o","title","m",top_angles=[{"title":"t"}],missing_evidence=["proof"])
    assert angle.score==100 and angle.confidence==1
    assert CreativeAngle.from_dict(angle.to_dict()).angle_id=="a"
    assert "No ad was launched" in report.to_markdown()
