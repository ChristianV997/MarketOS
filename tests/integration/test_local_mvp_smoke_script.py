import json
from pathlib import Path

from scripts.local_mvp_smoke import run_smoke

ROOT = Path(__file__).resolve().parents[2]


def test_local_smoke_generates_dashboard_readable_events():
    target = ROOT / "artifacts/test-local-deployment-smoke-events.jsonl"
    try:
        report = run_smoke(query="portable espresso maker", allow_public_network=False, include_shopify_fixture=True, write_jsonl=str(target.relative_to(ROOT)), skip_frontend_build=True)
        assert report["run"]["status"] == "fixture"
        assert report["run"]["event_count"] > 10
        assert report["timeline"]["event_count"] == report["run"]["event_count"]
        assert report["dashboard_route"] == "/operator/events"
        assert report["network_used"] is False
        assert report["mutated"] is False
    finally:
        target.unlink(missing_ok=True)


def test_local_smoke_public_network_is_not_default():
    report = run_smoke(query="portable espresso maker", allow_public_network=False, include_shopify_fixture=False, write_jsonl=None, skip_frontend_build=True)
    assert report["network_used"] is False
    assert report["run"]["status"] == "fixture"
