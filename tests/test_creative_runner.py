from backend.creative_intelligence.creative_registry import CreativeIntelligenceRegistry
from backend.creative_intelligence import creative_registry
from backend.creative_intelligence.creative_runner import run_creative_intelligence_cycle

def test_creative_runner_builds_thin_evidence_artifacts(tmp_path,monkeypatch):
    reg=CreativeIntelligenceRegistry(tmp_path/"creative.json");monkeypatch.setattr(creative_registry,"_singleton",reg)
    output=run_creative_intelligence_cycle("creative-test","Organizer","Home")
    assert output["status"]=="completed"
    assert output["angles"] and output["hooks"] and output["test_matrix"]["safety_notes"]
    assert reg.latest_report("creative-test")
