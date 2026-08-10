from pathlib import Path
from backend.ecommerce.shopify_readonly.events import shopify_batch_events
from backend.ecommerce.shopify_readonly.importer import import_shopify_readonly
from backend.events.supabase_event_validation import validate_events_for_supabase
from backend.mvp_commerce.events import commerce_mvp_events
from backend.mvp_commerce.runner import run_commerce_mvp_slice

ROOT = Path(__file__).resolve().parents[2]
def test_mixed_advisory_event_batch_is_staging_compatible():
    batch, context = import_shopify_readonly(ROOT / "tests/fixtures/shopify_readonly/shopify_sample.json")
    run = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=ROOT / "tests/fixtures/commerce_mvp/public_signals.json")
    validations = validate_events_for_supabase(shopify_batch_events(batch, context) + commerce_mvp_events(run))
    assert validations and all(item["valid"] for item in validations)
