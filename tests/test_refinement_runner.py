from pathlib import Path
from backend.discovery.refinement_registry import get_refinement_registry
from backend.discovery.refinement_runner import run_import_refine_compare, run_refinement_cycle


def test_refinement_cycle_creates_plan():
    get_refinement_registry().clear_for_tests()
    result = run_refinement_cycle(create_templates=False)
    assert result["status"] == "completed" and result["import_plan"]["recommendations"]


def test_import_refine_compare_without_baseline():
    path = str(Path(__file__).parent / "fixtures" / "evidence_imports" / "supplier_catalog_sample.csv")
    result = run_import_refine_compare(import_paths=[path], parser_type_by_path={path: "supplier_catalog_csv"})
    assert result["status"] == "completed" and result["gap_analysis"]
    assert result.get("comparison", {}).get("baseline_discovery_id", "") == ""
