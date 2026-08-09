from backend.discovery.calibration_registry import CalibrationRegistry
from backend.discovery.evidence_gap import EvidenceGap, EvidenceGapAnalysis
from backend.discovery.import_recommendation import build_import_recommendation_plan
from backend.discovery.source_calibration import SourceCalibrationProfile


def test_calibration_adjusts_but_does_not_remove_severe_gap(monkeypatch, tmp_path):
    import backend.discovery.import_recommendation as module
    registry = CalibrationRegistry(tmp_path / "calibration.json")
    profile = SourceCalibrationProfile("p", "w", "supplier_catalog", "local_file", "supplier_catalog_csv", usefulness_score=80, recommended_priority_adjustment=-25, strengths=["gap_reduction"])
    registry.register_profile(profile)
    monkeypatch.setattr(module, "get_calibration_registry", lambda: registry)
    gap = EvidenceGap("g", "w", "category", "x", "x", "margin_proxy", "critical", 80, recommended_parser_types=["supplier_catalog_csv"])
    recommendation = build_import_recommendation_plan(EvidenceGapAnalysis("a", "w", "t", "o", [gap])).recommendations[0]
    assert recommendation.priority_score >= 70 and recommendation.metadata["calibration_profile_id"] == "p"


def test_no_profile_preserves_base_metadata():
    gap = EvidenceGap("g", "w", "category", "x", "x", "trend_proxy", "high", 80, recommended_parser_types=["google_trends_csv"])
    recommendation = build_import_recommendation_plan(EvidenceGapAnalysis("a", "w", "t", "o", [gap])).recommendations[0]
    assert recommendation.metadata["priority_adjustment"] == 0
