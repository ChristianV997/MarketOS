from backend.discovery.refinement_registry import get_refinement_registry
from backend.discovery.refinement_runner import run_refinement_cycle


def test_refinement_includes_calibration_context():
    get_refinement_registry().clear_for_tests()
    result = run_refinement_cycle(create_templates=False, max_recommendations=2)
    assert "calibration_profiles_used" in result and "adjusted_import_recommendations" in result
    assert result["calibration"]["status"] in {"partial", "completed"}
