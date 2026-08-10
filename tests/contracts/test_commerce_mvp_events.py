from pathlib import Path
from backend.contracts.events import Event
from backend.mvp_commerce.events import commerce_mvp_events
from backend.mvp_commerce.runner import run_commerce_mvp_slice

ROOT = Path(__file__).resolve().parents[2]


def test_canonical_events_validate_and_cannot_grant_live_authority() -> None:
    run = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=ROOT / "tests/fixtures/commerce_mvp/public_signals.json")
    events = commerce_mvp_events(run)
    assert events[0].event_type == "commerce_mvp_run_started"
    assert events[-1].event_type == "commerce_mvp_run_completed"
    assert all(Event.from_dict(item.to_dict()).replay_hash() == item.replay_hash() for item in events)
    for event in events:
        assert event.metadata["manual_approval_required"] is True
        assert all(event.metadata[key] is True for key in ("no_launch_authority", "no_spend_authority", "no_publish_authority", "no_store_mutation_authority", "no_payment_authority", "no_fulfillment_authority"))
