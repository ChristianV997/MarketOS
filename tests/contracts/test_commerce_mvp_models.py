from pathlib import Path
from backend.mvp_commerce.runner import run_commerce_mvp_slice

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/commerce_mvp/public_signals.json"


def test_models_are_json_safe_and_assumption_labeled() -> None:
    run = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=FIXTURE)
    data = run.to_dict()
    assert data["selected_candidate"]["product_name"] == "Portable Espresso Maker"
    assert data["unit_economics_summary"]["source"] == "dry_run_assumption"
    assert "profitability" in data["selected_candidate"]["cannot_claim"][0]
    assert data["metadata"]["provider_calls"] is False


def test_thin_evidence_is_explicitly_warned() -> None:
    run = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=ROOT / "tests/fixtures/commerce_mvp/public_signals_thin_evidence.json")
    assert any("thin_evidence" in item for item in run.warnings)
    assert run.selected_candidate.confidence_level == "thin"
