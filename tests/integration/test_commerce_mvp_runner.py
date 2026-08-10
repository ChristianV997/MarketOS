from pathlib import Path
from backend.events.repository import InMemoryEventRepository
from backend.mvp_commerce.events import commerce_mvp_events
from backend.mvp_commerce.runner import run_commerce_mvp_slice

ROOT = Path(__file__).resolve().parents[2]


def test_runner_composes_full_packet_and_router_recommendations() -> None:
    repository = InMemoryEventRepository()
    run = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=ROOT / "tests/fixtures/commerce_mvp/public_signals.json", write_repository=repository)
    assert run.status == "completed"
    assert run.creative_packet and run.landing_page_packet and run.store_draft_packet and run.approval_packet
    assert run.landing_page_packet.target_builder == "gempages"
    assert run.store_draft_packet.target_platform == "shopify"
    assert "shopify_product_creation" in run.store_draft_packet.forbidden_actions
    routes = {item["capability_id"]: item["recommended_vendor_id"] for item in run.vendor_recommendations}
    assert routes["video_ad_generation"] == "creatify"
    assert len(repository.tail()) == len(commerce_mvp_events(run))


def test_runner_does_not_write_without_explicit_repository() -> None:
    run = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=ROOT / "tests/fixtures/commerce_mvp/public_signals.json")
    assert run.metadata["network_used"] is False
    assert run.metadata["provider_calls"] is False
