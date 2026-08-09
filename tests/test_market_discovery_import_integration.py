from pathlib import Path
from backend.discovery.discovery_registry import get_discovery_registry
from backend.discovery.market_discovery_runner import run_market_discovery


def test_import_only_and_import_and_run():
    get_discovery_registry().clear_for_tests()
    path = str(Path(__file__).parent / "fixtures" / "evidence_imports" / "google_trends_sample.csv")
    parsers = {path: "google_trends_csv"}
    assert run_market_discovery(import_paths=[path], parser_type_by_path=parsers, import_only=True)["status"] == "completed"
    result = run_market_discovery(import_paths=[path], parser_type_by_path=parsers, run_validation_services=False)
    assert result["status"] == "completed" and result["discovery"]["evidence_count"] > 0


def test_bad_file_does_not_crash_good_import():
    path = str(Path(__file__).parent / "fixtures" / "evidence_imports" / "supplier_catalog_sample.csv")
    result = run_market_discovery(import_paths=["tests/fixtures/nope.csv", path], parser_type_by_path={path: "supplier_catalog_csv"}, run_validation_services=False)
    assert result["status"] == "completed" and result["warnings"]
