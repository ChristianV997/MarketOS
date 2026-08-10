import json
from pathlib import Path
from backend.mvp_commerce.runner import run_commerce_mvp_slice
ROOT = Path(__file__).resolve().parents[2]

def test_full_fixture_slice_is_demoable_and_export_only() -> None:
    run = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=ROOT / "tests/fixtures/commerce_mvp/public_signals.json")
    assert len(run.signal_batch) == 4 and len(run.canonical_event_ids) >= 10
    assert "Do not publish" in " ".join(run.landing_page_packet.manual_publish_checklist)
    assert "external store" in " ".join(run.approval_packet.required_reviews)
    assert "Advisory and dry-run only" in run.to_markdown()


def test_expected_fixture_summary_remains_true() -> None:
    expected = json.loads((ROOT / "tests/fixtures/commerce_mvp/commerce_mvp_run.expected.json").read_text(encoding="utf-8"))
    run = run_commerce_mvp_slice(query=expected["query"], signal_fixture_path=ROOT / "tests/fixtures/commerce_mvp/public_signals.json")
    assert run.status == expected["status"] and run.selected_candidate.product_name == expected["selected_product_hypothesis"]
    assert run.unit_economics_summary.source == expected["economics_source"] and run.metadata["provider_calls"] is expected["provider_calls"]
