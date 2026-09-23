"""Unit coverage for the operator browser acceptance runner (fixture path)."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.ai.run_operator_browser_acceptance import (
    AcceptanceConfig,
    _assert_no_mutations,
    _fixture_payload,
    resolve_browser,
    run_fixture_journey,
)


def test_fixture_payloads_cover_evidence_classes():
    services = _fixture_payload("services")
    classes = {row["evidence"] for row in services["engagements"]}
    assert classes == {"fixture", "manual", "simulated", "unknown"}
    assert any(row["lifecycle"] == "data_inadequate" for row in services["engagements"])

    cockpit = _fixture_payload("first-phase")
    assert {row["evidence"] for row in cockpit["candidates"]} == {
        "fixture",
        "manual",
        "simulated",
        "unknown",
    }


def test_mutation_guard_rejects_post_and_external_hosts():
    failures = _assert_no_mutations(
        [
            {"method": "GET", "url": "http://127.0.0.1:9/__mock_api/services"},
            {"method": "POST", "url": "http://127.0.0.1:9/api/commerce-mvp/public-run"},
            {"method": "GET", "url": "https://supplier.example/orders"},
        ]
    )
    assert any(item.startswith("mutating_method:POST") for item in failures)
    assert any(item.startswith("external_provider_url:") for item in failures)


def test_resolve_browser_none_is_stable():
    assert resolve_browser("none") == "none"


def test_run_fixture_journey_without_browser_is_honest(tmp_path: Path):
    report = run_fixture_journey(
        AcceptanceConfig(
            browser="none",
            artifact_dir=tmp_path,
            include_viewports=False,
        )
    )
    assert report["schema"] == "MarketOS.OperatorBrowserAcceptance.v1"
    assert report["browser_proof"] is False
    assert str(report["status"]).startswith("passed")
    assert report["routes"] == [
        "/operator/services",
        "/operator/first-phase",
        "/operator/events",
        "/operator/consulting-research",
        "/operator/marketing-strategy",
    ]
    spa = [case for case in report["cases"] if str(case["id"]).startswith("fixture-server-spa-")]
    assert len(spa) == 5
    assert all(case["http_status"] == 404 and case["passed"] for case in spa)
    saved = json.loads((tmp_path / "operator-browser-acceptance-report.json").read_text(encoding="utf-8"))
    assert saved["schema"] == report["schema"]
