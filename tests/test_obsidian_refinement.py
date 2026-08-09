from backend.discovery.evidence_gap import EvidenceGapAnalysis
from backend.discovery.import_recommendation import ImportRecommendationPlan
from backend.obsidian.sync import sync_refinement_cycle_note


def test_refinement_note_optional(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    result = sync_refinement_cycle_note(EvidenceGapAnalysis("a", "w", "t", "o"), ImportRecommendationPlan("p", "w", "t"), [])
    assert result["status"] == "skipped"
