from dataclasses import replace
from pathlib import Path
import pytest
from backend.ecommerce.shopify_readonly.events import shopify_batch_events
from backend.ecommerce.shopify_readonly.importer import import_shopify_readonly
from backend.events.supabase_event_validation import SupabaseEventValidationError, event_to_supabase_row, validate_events_for_supabase
from backend.mvp_commerce.events import commerce_mvp_events
from backend.mvp_commerce.runner import run_commerce_mvp_slice

ROOT = Path(__file__).resolve().parents[2]

def test_commerce_and_shopify_rows_validate():
    run = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=ROOT / "tests/fixtures/commerce_mvp/public_signals.json")
    batch, context = import_shopify_readonly(ROOT / "tests/fixtures/shopify_readonly/shopify_sample.json")
    events = commerce_mvp_events(run) + shopify_batch_events(batch, context)
    assert len(validate_events_for_supabase(events)) == len(events)
    assert event_to_supabase_row(events[0])["workspace_id"] == "commerce-mvp-dry-run"

def test_pii_and_authority_fail_closed():
    batch, context = import_shopify_readonly(ROOT / "tests/fixtures/shopify_readonly/shopify_sample.json")
    event = shopify_batch_events(batch, context)[1]
    with pytest.raises(SupabaseEventValidationError, match="PII"):
        event_to_supabase_row(replace(event, payload={"email": "plain@example.test"}))
    with pytest.raises(SupabaseEventValidationError, match="authority"):
        event_to_supabase_row(replace(event, metadata={}))
