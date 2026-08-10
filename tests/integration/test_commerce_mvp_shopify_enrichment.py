from pathlib import Path
from backend.ecommerce.shopify_readonly.importer import import_shopify_readonly
from backend.ecommerce.shopify_readonly.events import append_shopify_events
from backend.events.repository import JsonlEventRepository
from backend.mvp_commerce.runner import run_commerce_mvp_slice

ROOT = Path(__file__).resolve().parents[2]


def test_shopify_context_enriches_without_changing_selection():
    plain = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=ROOT / "tests/fixtures/commerce_mvp/public_signals.json")
    _, context = import_shopify_readonly(ROOT / "tests/fixtures/shopify_readonly/shopify_sample.json")
    enriched = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=ROOT / "tests/fixtures/commerce_mvp/public_signals.json", shopify_store_context=context)
    assert enriched.selected_candidate.candidate_id == plain.selected_candidate.candidate_id
    assert enriched.metadata["shopify_readonly_enrichment"]["store_context"]["pii_redacted"] is True


def test_explicit_repository_receives_shopify_and_commerce_events(tmp_path):
    batch, context = import_shopify_readonly(ROOT / "tests/fixtures/shopify_readonly/shopify_sample.json")
    repo = JsonlEventRepository(tmp_path / "events.jsonl")
    shopify_ids = append_shopify_events(batch, context, repo)
    run = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=ROOT / "tests/fixtures/commerce_mvp/public_signals.json", shopify_store_context=context, write_repository=repo)
    assert len(shopify_ids) == 16
    assert len(repo.tail(100)) == len(shopify_ids) + len(run.canonical_event_ids)
