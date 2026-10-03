"""Unit and contract coverage for the Owner Research acceptance runner."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.ai.run_owner_research_acceptance import (
    OwnerAcceptanceConfig,
    _assert_no_mutations,
    _fixture_portfolio_payload,
    resolve_browser,
    run_owner_research_acceptance,
)


def test_fixture_portfolio_payloads_cover_scenarios():
    p_ok = _fixture_portfolio_payload("ok-fixture-2-of-3", "ws-owner-alpha")
    assert p_ok["schema_version"] == "owner-research-portfolio-v1"
    assert p_ok["workspace_id"] == "ws-owner-alpha"
    assert p_ok["evidence_mode"] == "fixture_only"
    assert p_ok["read_only"] is True
    assert p_ok["mutated"] is False
    assert len(p_ok["items"]) == 2

    p_manual = _fixture_portfolio_payload("ready-3-of-3-manual", "ws-owner-alpha")
    assert p_manual["evidence_mode"] == "manual"
    assert len(p_manual["items"]) == 3
    assert p_manual["draft_research"]["eligible"] is True

    p_empty = _fixture_portfolio_payload("empty-0-of-3", "ws-owner-alpha")
    assert len(p_empty["items"]) == 0

    p_dup = _fixture_portfolio_payload("duplicates-and-archived", "ws-owner-alpha")
    active_ids = {it["candidate_id"] for it in p_dup["items"] if it.get("status") == "active"}
    assert active_ids == {"c-hydroponics", "c-smart-feeder", "c-solar-camera"}
    assert any(it.get("status") in {"archived", "removed", "inactive"} for it in p_dup["items"])


def test_mutation_guard_rejects_mutations_and_external_providers():
    failures = _assert_no_mutations(
        [
            {"method": "GET", "url": "http://127.0.0.1:9/__mock_api/portfolio"},
            {"method": "POST", "url": "http://127.0.0.1:9/api/owner-research/draft"},
            {"method": "GET", "url": "https://api.openai.com/v1/chat/completions"},
            {"method": "GET", "url": "https://api.shopify.com/admin/products.json"},
        ]
    )
    assert any(item.startswith("mutating_method:POST") for item in failures)
    assert any("openai.com" in item for item in failures)
    assert any("shopify.com" in item for item in failures)


def test_resolve_browser_none_is_stable():
    assert resolve_browser("none") == "none"


def test_run_owner_research_acceptance_journey_passes(tmp_path: Path):
    report = run_owner_research_acceptance(
        OwnerAcceptanceConfig(
            browser="none",
            artifact_dir=tmp_path,
            include_viewports=False,
        )
    )

    assert report["schema"] == "MarketOS.OwnerResearchAcceptance.v1"
    assert report["status"] == "passed"
    assert report["browser_proof"] is False
    assert report["live_validated"] is False
    assert report["evidence_class"] == "contract_fixture_tested"

    # Verify zero-mutation guarantees
    assert report["zero_mutation_guarantees"] == {
        "provider_calls": 0,
        "publishes": 0,
        "ad_spends": 0,
        "orders": 0,
        "payments": 0,
        "customer_messages": 0,
        "mutating_http_verbs": 0,
    }

    # Verify unmet dependencies documented truthfully
    deps = {d["dependency"]: d for d in report["unmet_dependencies"]}
    assert "GET /api/phase1/evidence-cockpit" in deps
    assert "GET /api/owner-research/portfolio" in deps
    assert deps["GET /api/owner-research/portfolio"]["schema_version"] == "owner-research-portfolio-v1"

    # Verify checks
    checks = report["checks"]
    assert checks["auth_owner_scoping"] is True
    assert checks["deduplication_and_archived"] is True
    assert checks["blocked_draft_below_three_conflict"] is True
    assert checks["allowed_advisory_draft_at_or_above_3"] is True
    assert checks["distinct_active_counts"] == {
        "empty-0-of-3": 0,
        "ok-fixture-2-of-3": 2,
        "ready-3-of-3-manual": 3,
        "ready-5-of-3": 5,
    }
    assert checks["outage_honesty"] == {
        "unavailable-404": True,
        "unavailable-501": True,
        "error-500": True,
    }
    assert checks["harness_contracts"] is True

    # Verify saved report
    saved = json.loads((tmp_path / "owner-research-acceptance-report.json").read_text(encoding="utf-8"))
    assert saved["schema"] == report["schema"]
    assert saved["status"] == "passed"


def test_harness_file_contracts_and_a11y_markers():
    harness_path = Path("frontend/tests/fixtures/owner-research-journey/harness.html")
    assert harness_path.is_file()
    content = harness_path.read_text(encoding="utf-8")

    assert 'id="skip-link"' in content
    assert 'href="#main-content"' in content
    assert 'role="listbox"' in content
    assert 'role="option"' in content
    assert 'role="status"' in content
    assert 'aria-live="polite"' in content
    assert 'role="group"' in content
    assert 'aria-labelledby="draft-actions-title"' in content
    assert 'data-action="target_markets"' in content
    assert 'data-action="personas"' in content
    assert 'data-action="brand_ad_strategy"' in content
    assert 'data-action="social_channels"' in content
    assert 'data-action="storefront_landing"' in content
    assert "POST" not in content or 'method: "POST"' not in content
