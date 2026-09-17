"""Focused tests for the bounded offline research-to-decision seam."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.research_to_decision import ResearchToDecisionError, build_research_to_decision


ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures" / "research_to_decision"
SCENARIOS = (
    "hydroponics_promising.json",
    "smart_pet_support_risk.json",
    "solar_4g_blocked.json",
    "commodity_electronics_rejected.json",
    "walking_pad_deferred.json",
    "b2b_insufficient_data.json",
)


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", SCENARIOS)
def test_scenario_builds_existing_client_safe_packet(name: str) -> None:
    report = build_research_to_decision(load_fixture(name), base_dir=FIXTURES)
    appendix = report["appendix"]
    assert report["report_version"] == "product-validation-report-v1"
    assert report["source_reports"]["research_to_decision"] == "supplied"
    assert report["read_only"] is True
    assert report["network_calls"] is False
    assert report["mutated"] is False
    assert appendix["validation"]["status"] == "hold_for_manual_review"
    assert appendix["validation"]["provider_calls"] is False
    assert len(appendix["replay_fingerprint"]) == 64
    assert appendix["candidate_audit"][0]["lifecycle_state"]
    assert "lane" in appendix["candidate_audit"][0]
    assert report["overall_recommendation"] != "advance_to_launch_draft"


def test_packet_is_deterministic_and_contains_ranked_evidence() -> None:
    manifest = load_fixture("hydroponics_promising.json")
    first = build_research_to_decision(manifest, base_dir=FIXTURES)
    second = build_research_to_decision(manifest, base_dir=FIXTURES)
    assert first == second
    assert first["candidate_rankings"]
    assert first["appendix"]["candidate_audit"][0]["action"]
    assert "economics" in first["appendix"]["candidate_audit"][0]


def test_missing_supplier_evidence_is_explicitly_hold_for_review() -> None:
    report = build_research_to_decision(load_fixture("b2b_insufficient_data.json"), base_dir=FIXTURES)
    validation = report["appendix"]["validation"]
    assert "supplier_evidence_missing" in validation["warnings"]
    assert "marketplace_evidence_missing" in validation["warnings"]
    assert "consumer_attention_evidence_missing" in validation["warnings"]


def test_reviewed_url_observation_is_summarized_without_raw_url(tmp_path: Path) -> None:
    observation = tmp_path / "review.json"
    observation.write_text(json.dumps({"candidate_id": "x", "url": "https://example.test/item?token=not-kept"}), encoding="utf-8")
    manifest = {
        "captured_at": "2026-09-16T09:00:00-06:00",
        "lane": {"origin": "Shenzhen", "destination": "Mexico", "currency": "MXN"},
        "candidates": [{"candidate_id": "x"}],
        "observation_inputs": [{"path": "review.json", "kind": "reviewed_url"}],
    }
    report = build_research_to_decision(manifest, base_dir=tmp_path)
    assert report["appendix"]["input_audit"][0]["kind"] == "reviewed_url"
    assert "example.test" not in json.dumps(report)


@pytest.mark.parametrize(
    ("manifest_patch", "expected"),
    [
        ({"captured_at": "2026-09-16T09:00:00"}, "timezone"),
        ({"lane": {"origin": "Shenzhen", "destination": "Mexico", "currency": "ZZZ"}}, "unsupported currency"),
        ({"lane": {"origin": "Shenzhen", "destination": "unsupported", "currency": "MXN"}}, "unsupported"),
    ],
)
def test_manifest_rejects_unsafe_lane_or_capture_time(manifest_patch: dict, expected: str) -> None:
    manifest = load_fixture("b2b_insufficient_data.json")
    manifest.update(manifest_patch)
    with pytest.raises(ResearchToDecisionError, match=expected):
        build_research_to_decision(manifest, base_dir=FIXTURES)


def test_secret_html_duplicate_and_traversal_inputs_fail_closed(tmp_path: Path) -> None:
    secret = tmp_path / "secret.json"
    secret.write_text(json.dumps({"candidate_id": "x", "api_key": "sk_test_nope"}), encoding="utf-8")
    manifest = {
        "captured_at": "2026-09-16T09:00:00-06:00",
        "lane": {"origin": "Shenzhen", "destination": "Mexico", "currency": "MXN"},
        "candidates": [{"candidate_id": "x"}],
        "supplier_inputs": [{"path": "secret.json"}],
    }
    with pytest.raises(ResearchToDecisionError, match="secret-like"):
        build_research_to_decision(manifest, base_dir=tmp_path)

    html = tmp_path / "page.json"
    html.write_text("<html>not an evidence packet</html>", encoding="utf-8")
    manifest["supplier_inputs"] = [{"path": "page.json"}]
    with pytest.raises(ResearchToDecisionError, match="HTML"):
        build_research_to_decision(manifest, base_dir=tmp_path)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(json.dumps([{"candidate_id": "x"}, {"candidate_id": "x"}]), encoding="utf-8")
    manifest["supplier_inputs"] = [{"path": "duplicate.json"}]
    with pytest.raises(ResearchToDecisionError, match="duplicate"):
        build_research_to_decision(manifest, base_dir=tmp_path)

    manifest["supplier_inputs"] = [{"path": "..\\outside.json"}]
    with pytest.raises(ResearchToDecisionError, match="relative"):
        build_research_to_decision(manifest, base_dir=tmp_path)


def test_currency_and_destination_mismatch_fail_closed(tmp_path: Path) -> None:
    evidence = tmp_path / "supplier.json"
    evidence.write_text(json.dumps({"candidate_id": "x", "supplier": "manual", "currency": "USD", "destination_region": "Canada"}), encoding="utf-8")
    manifest = {
        "captured_at": "2026-09-16T09:00:00-06:00",
        "lane": {"origin": "Shenzhen", "destination": "Mexico", "currency": "MXN"},
        "candidates": [{"candidate_id": "x"}],
        "supplier_inputs": [{"path": "supplier.json"}],
    }
    with pytest.raises(ResearchToDecisionError, match="currency mismatch"):
        build_research_to_decision(manifest, base_dir=tmp_path)


def test_conflicting_same_identity_across_inputs_fails_closed(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    base = {"candidate_id": "x", "supplier": "manual", "supplier_sku": "SKU-1", "currency": "MXN", "destination_region": "Mexico", "unit_cost": 10}
    first.write_text(json.dumps(base), encoding="utf-8")
    second.write_text(json.dumps({**base, "unit_cost": 12}), encoding="utf-8")
    manifest = {
        "captured_at": "2026-09-16T09:00:00-06:00",
        "lane": {"origin": "Shenzhen", "destination": "Mexico", "currency": "MXN"},
        "candidates": [{"candidate_id": "x"}],
        "supplier_inputs": [{"path": "first.json"}, {"path": "second.json"}],
    }
    with pytest.raises(ResearchToDecisionError, match="conflicting duplicate"):
        build_research_to_decision(manifest, base_dir=tmp_path)
