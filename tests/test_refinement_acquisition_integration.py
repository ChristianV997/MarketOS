from backend.discovery.acquisition_registry import get_acquisition_registry
from backend.discovery.refinement_registry import get_refinement_registry
from backend.discovery.refinement_runner import run_refinement_cycle


def test_refinement_returns_persisted_acquisition_plans():
    get_refinement_registry().clear_for_tests(); get_acquisition_registry().clear_for_tests()
    result = run_refinement_cycle(create_templates=False, max_recommendations=2)
    assert result["acquisition_plans"]
    assert get_acquisition_registry().get_plan(result["acquisition_plans"][0]["plan_id"]) is not None
    assert result["acquisition_plans"][0]["template_paths"]
