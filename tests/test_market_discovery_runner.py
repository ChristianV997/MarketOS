from pathlib import Path
from backend.discovery.market_discovery_runner import run_market_discovery
from backend.discovery.discovery_registry import get_discovery_registry


def test_market_discovery_fixture_is_category_first_and_read_only():
    path = Path(__file__).parent / "fixtures" / "market_evidence_seed.json"
    result = run_market_discovery(dataset_paths=[str(path)], run_validation_services=False)
    assert result["status"] == "completed"
    assert result["discovery"]["category_opportunities"]
    assert result["hypotheses"]["hypotheses"]
    assert result["discovery"]["metadata"]["real_market_claims"] is False


def test_empty_discovery_fails_closed():
    get_discovery_registry().clear_for_tests()
    result = run_market_discovery(dataset_paths=[], run_validation_services=False)
    assert result["status"] == "blocked"
    assert "no_local_or_persisted_evidence" in result["warnings"]


def test_validation_uses_governed_dry_run_service():
    get_discovery_registry().clear_for_tests()
    path = Path(__file__).parent / "fixtures" / "market_evidence_seed.json"
    result = run_market_discovery(dataset_paths=[str(path)], max_hypotheses=2, run_validation_services=True)
    assert result["status"] == "completed"
    assert result["validation_reports"]
    assert all(item.get("status") == "completed" for item in result["validation_reports"])
