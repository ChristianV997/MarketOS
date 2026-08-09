from backend.discovery.evidence_gap import EvidenceGap, EvidenceGapAnalysis
from backend.discovery.import_recommendation import build_import_recommendation_plan


def test_recommendations_group_parser_types():
    analysis = EvidenceGapAnalysis("a", "w", "x", "y", [EvidenceGap("g1", "w", "category", "x", "x", "margin_proxy", "critical", 95, recommended_parser_types=["supplier_catalog_csv"]), EvidenceGap("g2", "w", "category", "x", "x", "supplier_proxy", "high", 80, recommended_parser_types=["supplier_catalog_csv"])])
    plan = build_import_recommendation_plan(analysis)
    assert len(plan.recommendations) == 1
    assert "supplier_cost" in plan.recommendations[0].required_fields
    assert "data/import_templates" in plan.to_markdown()
