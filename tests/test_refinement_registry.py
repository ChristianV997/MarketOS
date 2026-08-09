from backend.discovery.evidence_gap import EvidenceGapAnalysis
from backend.discovery.import_recommendation import ImportRecommendationPlan
from backend.discovery.import_templates import ImportTemplate
from backend.discovery.refinement_registry import RefinementRegistry


def test_refinement_registry_round_trip(tmp_path):
    registry = RefinementRegistry(tmp_path / "refinement.json")
    analysis = EvidenceGapAnalysis("a", "w", "t", "o")
    plan = ImportRecommendationPlan("p", "w", "t")
    template = ImportTemplate("t", "generic_market_csv", "t", "d", [], [], [], "data/import_templates/generic_market_csv.csv")
    registry.register_gap_analysis(analysis); registry.register_import_plan(plan); registry.register_template(template)
    assert registry.get_gap_analysis("a").analysis_id == "a" and registry.get_import_plan("p").plan_id == "p" and registry.get_template("t").template_id == "t"


def test_corrupt_registry_is_empty(tmp_path):
    path = tmp_path / "bad.json"; path.write_text("{bad", encoding="utf-8")
    registry = RefinementRegistry(path)
    assert registry.list_gap_analyses() == []
