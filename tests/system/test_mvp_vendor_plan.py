import json
from pathlib import Path

from backend.providers.vendor_router import build_workspace_vendor_plan
from backend.runtime.mvp_mode import load_mvp_profile


ROOT = Path(__file__).resolve().parents[2]


def test_mvp_profile_and_vendor_plan_remain_advisory() -> None:
    profile = load_mvp_profile()
    plan = build_workspace_vendor_plan()
    assert "saas_capability_router_metadata" in profile["enabled_modules"]
    assert plan["routing_is_metadata_only"] is True
    assert plan["external_calls"] is False
    assert plan["live_mutations_enabled"] is False
    assert "live_ads" in profile["disabled_modules"]


def test_mvp_vendor_snapshot_examples_remain_stable() -> None:
    expected = json.loads((ROOT / "tests/fixtures/vendor_capabilities/vendor_plan_mvp.expected.json").read_text(encoding="utf-8"))
    plan = build_workspace_vendor_plan()
    routes = {row["capability_id"]: row["recommended_vendor_id"] for row in plan["recommendations"]}
    assert plan["routing_is_metadata_only"] is expected["routing_is_metadata_only"]
    assert plan["external_calls"] is expected["network_calls"]
    for capability_id, vendor_id in expected["selected_examples"].items():
        assert routes[capability_id] == vendor_id
