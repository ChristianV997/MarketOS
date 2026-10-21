"""Fixture/fake-transport tests for the official Google Trends interest adapter."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.commerce.google_trends_interest_adapter import (
    COLLECTION_STATUSES,
    MAX_LOOKBACK_DAYS,
    OBSERVATION_STATUSES,
    PROVIDER_ID,
    READINESS_STATES,
    REQUEST_KINDS,
    TIME_RESOLUTIONS,
    FakeTrendsTransport,
    GoogleTrendsInterestAdapterError,
    build_google_trends_interest_report,
    normalize_interest_observation,
    parse_google_trends_interest_fixture,
    validate_date_window,
    validate_geography,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "google_trends_interest_adapter"
CLI = ROOT / "scripts" / "run_google_trends_interest_adapter.py"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_source_evaluation_marks_alpha_not_commercially_ga():
    report = build_google_trends_interest_report()
    access = report.access_assessment
    assert access.provider_id == PROVIDER_ID
    assert access.official_api_exists is True
    assert access.commercially_generally_available is False
    assert access.alpha_application_required is True
    assert access.pytrends_allowed is False
    assert access.browser_scraping_allowed is False
    assert access.undocumented_endpoints_allowed is False
    assert access.quotas_published is False
    assert access.costs_published is False
    assert "alpha" in access.suitability_summary.lower()
    assert "developers.google.com/search/apis/trends" in access.primary_documentation[0]
    assert any("cant-access-docs" in url for url in access.primary_documentation)
    assert report.request_plan.live_request_created is False
    assert report.safety_summary.network_calls is False
    assert "unknown_until_alpha_reference_docs" in report.request_plan.endpoint_placeholder
    assert "googleapis.com" not in report.request_plan.endpoint_placeholder
    assert "published_quota" in report.unavailable_fields
    assert "public_method_schema" in report.unavailable_fields
    assert "website_0_100_rescale" in report.unavailable_fields


def test_relative_interest_is_not_volume_sales_or_launch_evidence():
    report = build_google_trends_interest_report(payload=load("trends_interest_valid.json"))
    assert report.evidence_boundary["relative_search_interest_evidence"] is True
    assert report.evidence_boundary["absolute_volume_authority"] is False
    assert report.evidence_boundary["sales_or_demand_proof"] is False
    assert report.evidence_boundary["website_0_100_rescale"] is False
    assert report.evidence_boundary["supplier_proof"] is False
    assert report.evidence_boundary["launch_authority"] is False
    for item in report.observations:
        blob = " ".join(item.limitations).lower()
        assert "relative" in blob or "consistently scaled" in blob
        assert "absolute" in blob
        assert "website" in blob and "0" in blob and "100" in blob
        assert item.metric_kind == "relative_search_interest"
        assert item.observation_period_start
        assert item.observation_period_end


def test_default_report_is_deterministic_and_offline():
    first = build_google_trends_interest_report().to_dict()
    second = build_google_trends_interest_report().to_dict()
    assert first == second
    assert first["safety_summary"]["credentials_loaded"] is False
    assert first["safety_summary"]["raw_payload_stored"] is False
    assert first["safety_summary"]["scraping_performed"] is False
    assert first["result_status"] in COLLECTION_STATUSES


@pytest.mark.parametrize("kind", REQUEST_KINDS)
def test_request_kind_vocabulary(kind: str):
    assert build_google_trends_interest_report(request_kind=kind).request_plan.request_kind == kind


@pytest.mark.parametrize("resolution", TIME_RESOLUTIONS)
def test_time_resolution_vocabulary(resolution: str):
    assert resolution in TIME_RESOLUTIONS


@pytest.mark.parametrize("status", OBSERVATION_STATUSES)
def test_observation_status_vocabulary(status: str):
    assert status in OBSERVATION_STATUSES


@pytest.mark.parametrize("state", READINESS_STATES)
def test_readiness_state_vocabulary(state: str):
    assert state in READINESS_STATES


def test_valid_fixture_normalizes_relative_interest_not_volume():
    payload = load("trends_interest_valid.json")
    parsed = parse_google_trends_interest_fixture(payload)
    assert parsed.parse_status == "parsed"
    assert parsed.observations
    for item in parsed.observations:
        assert item.relative_interest is not None
        assert item.absolute_search_volume is None
        assert item.purchase_intent is None
        assert item.metric_kind == "relative_search_interest"
        assert "absolute" not in item.limitations[0].lower() or "not" in item.limitations[0].lower()
        assert item.geography
        assert item.language
        assert item.observation_period_start
        assert item.observation_period_end
        assert item.method == "official_trends_api_fixture"
        assert item.provenance in {"fixture", "observed", "unavailable", "incomplete", "stale", "blocked"}
        assert item.status in OBSERVATION_STATUSES


def test_missing_observation_is_not_coerced_to_zero():
    payload = load("trends_interest_partial.json")
    parsed = parse_google_trends_interest_fixture(payload)
    missing = [item for item in parsed.observations if item.status == "unavailable"]
    assert missing
    for item in missing:
        assert item.relative_interest is None
        assert item.relative_interest != 0


def test_malformed_fixture_is_rejected():
    with pytest.raises(GoogleTrendsInterestAdapterError, match="malformed|fixture_mode|schema"):
        parse_google_trends_interest_fixture(load("trends_interest_malformed.json"))


def test_secret_like_fixture_rejected():
    with pytest.raises(GoogleTrendsInterestAdapterError, match="secret|raw"):
        parse_google_trends_interest_fixture(load("trends_interest_secret_rejected.json"))


def test_raw_payload_fixture_rejected():
    with pytest.raises(GoogleTrendsInterestAdapterError, match="secret|raw"):
        parse_google_trends_interest_fixture(load("trends_interest_raw_payload_rejected.json"))


def test_geography_validation_iso_codes():
    assert validate_geography("US") == "US"
    assert validate_geography("US-CA") == "US-CA"
    assert validate_geography("worldwide") == "WORLD"
    with pytest.raises(GoogleTrendsInterestAdapterError):
        validate_geography("California!!!")
    with pytest.raises(GoogleTrendsInterestAdapterError):
        validate_geography("")


def test_date_window_bounds_and_freshness():
    # Rolling ~1800 day window; data ends ~2 days ago per primary docs.
    ok = validate_date_window("2024-01-01", "2024-06-30", reference_date="2024-07-02")
    assert ok["valid"] is True
    assert ok["span_days"] <= MAX_LOOKBACK_DAYS

    too_long = validate_date_window("2018-01-01", "2024-06-30", reference_date="2024-07-02")
    assert too_long["valid"] is False
    assert "lookback" in too_long["reason"]

    too_recent = validate_date_window("2024-06-01", "2024-07-02", reference_date="2024-07-02")
    assert too_recent["valid"] is False
    assert "lag" in too_recent["reason"] or "2" in too_recent["reason"]


def test_stale_observations_marked_stale_not_collected():
    payload = load("trends_interest_stale.json")
    parsed = parse_google_trends_interest_fixture(payload, reference_date="2026-10-12")
    assert any(item.status == "stale" for item in parsed.observations)
    assert all(item.status != "collected" or item.freshness_state != "stale" for item in parsed.observations)


def test_empty_fixture_is_incomplete_not_zero_filled():
    parsed = parse_google_trends_interest_fixture(load("trends_interest_empty.json"))
    assert parsed.parse_status in {"empty", "incomplete"}
    assert parsed.observations == ()
    assert "empty" in " ".join(parsed.warnings)


def test_fake_transport_rate_limit_and_quota():
    transport = FakeTrendsTransport()
    rate = transport.execute({"scenario": "rate_limited", "terms": ["desk fan"]})
    assert rate.status == "rate_limited"
    assert rate.observations == ()
    assert rate.network_attempted is False

    quota = transport.execute({"scenario": "quota_exhausted", "terms": ["desk fan"]})
    assert quota.status == "quota_exhausted"
    assert quota.observations == ()


def test_fake_transport_unsupported_access_and_disabled_policy():
    transport = FakeTrendsTransport()
    denied = transport.execute({"scenario": "unsupported_access", "terms": ["desk fan"]})
    assert denied.status == "unsupported_access"

    policy = transport.execute({"scenario": "disabled_by_policy", "terms": ["desk fan"]})
    assert policy.status == "disabled_by_policy"


def test_live_mode_remains_fail_closed():
    report = build_google_trends_interest_report(live_read_only=True)
    assert report.approval_readiness.readiness_state == "blocked"
    assert report.request_plan.status == "blocked_live_mode"
    assert report.safety_summary.network_calls is False
    assert any("live" in item.lower() for item in report.blocked_live_activation)


def test_attention_evidence_not_marketplace_or_launch_authority():
    report = build_google_trends_interest_report(payload=load("trends_interest_valid.json"))
    assert report.evidence_boundary["marketplace_price_authority"] is False
    assert report.evidence_boundary["supplier_proof"] is False
    assert report.evidence_boundary["launch_authority"] is False
    assert report.evidence_boundary["purchase_intent_authority"] is False
    assert report.evidence_boundary["sales_or_demand_proof"] is False
    assert report.evidence_category == "OrganicSearchInterestEvidence"
    for item in report.observations:
        assert "price" not in item.to_dict() or item.to_dict().get("price") in (None, "")
        assert item.absolute_search_volume is None
        assert item.purchase_intent is None


def test_normalize_observation_rejects_absolute_volume_claim():
    with pytest.raises(GoogleTrendsInterestAdapterError, match="absolute|volume|purchase"):
        normalize_interest_observation(
            {
                "term": "desk fan",
                "relative_interest": 42,
                "absolute_search_volume": 12000,
                "geography": "US",
                "language": "en",
                "observation_period_start": "2024-01-01",
                "observation_period_end": "2024-01-07",
                "status": "collected",
            }
        )


def test_cli_json_is_offline_safe():
    result = run_cli("--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["provider_id"] == PROVIDER_ID
    assert payload["safety_summary"]["network_calls"] is False
    assert payload["access_assessment"]["commercially_generally_available"] is False


def test_cli_rejects_secret_fixture_path():
    result = run_cli("--fixture", str(FIXTURES / "trends_interest_secret_rejected.json"), "--json")
    assert result.returncode != 0
    assert "secret" in (result.stderr + result.stdout).lower() or "not accepted" in (result.stderr + result.stdout).lower()
