from __future__ import annotations

import json

import pytest

from backend.adapters.research.meta_marketing_insights import blocked_get_plan, operational_read, read_supplied_fixture
from evaluation.commerce.meta_marketing_insights import (
    SCHEMA,
    account_performance_view,
    build_blocked_get_plan,
    normalize_supplied_insights,
)

CANARY = "insights-canary@example.com"
ACCOUNT_DIGITS = "9988776655"
CURSOR = "CURSORCANARYVALUE"


def _row(**extra):
    document = {
        "date_start": "2026-04-01",
        "date_stop": "2026-04-07",
        "impressions": "100",
        "clicks": "4",
        "spend": "12.50",
        "account_currency": "USD",
        "account_id": ACCOUNT_DIGITS,
        "actions": [{"action_type": "link_click", "value": "4"}],
    }
    document.update(extra)
    return document


def _payload(*rows, **extra):
    document = {"data": list(rows), "account_scope": "fixture-account-a"}
    document.update(extra)
    return document


def test_supplied_fixture_keeps_decimal_metrics_and_drops_identity():
    document = normalize_supplied_insights(_payload(_row()), expected_account_scope="fixture-account-a")
    assert document["schema"] == SCHEMA
    assert document["status"] == "supplied_fixture"
    assert document["live_observation"] is False
    assert document["provider_call"] is False
    row = document["evidence"]["normalized_fields"]["rows"][0]
    assert row["impressions"] == "100"
    assert row["clicks"] == "4"
    assert row["spend"] == "12.50"
    assert row["account_currency"] == "USD"
    assert row["timezone_basis"] == "ad_account_timezone"
    assert row["timezone_name"] is None
    assert row["account_id_stored"] is False
    assert row["platform_reported_actions"][0]["independently_verified_sales"] is False
    assert document["evidence"]["evidence_category"] == "ProviderRunEvidence"
    assert document["evidence"]["can_feed_reports"] is False
    assert document["evidence"]["normalized_fields"]["combined_spend"] is None
    rendered = json.dumps(document)
    assert ACCOUNT_DIGITS not in rendered
    for value in document["authority"].values():
        assert value is False


def test_partial_metrics_currency_and_dates_fail_closed():
    partial = normalize_supplied_insights(_payload(_row(clicks=None, spend=None, ctr="0.5")))
    row = partial["evidence"]["normalized_fields"]["rows"][0]
    assert row["impressions"] == "100"
    assert row["clicks"] is None
    assert row["field_status"]["clicks"] == "unavailable"
    assert row["ctr"] == "0.5"
    assert row["ctr_recomputed"] is False

    comma = normalize_supplied_insights(_payload(_row(spend="12,50")))
    assert comma["evidence"]["normalized_fields"]["rows"][0]["spend"] is None

    lowered = normalize_supplied_insights(_payload(_row(account_currency="usd")))
    assert lowered["evidence"]["normalized_fields"]["rows"][0]["account_currency"] is None

    invalid = normalize_supplied_insights(_payload(_row(date_start="2026-04-31")))
    assert invalid["status"] == "unavailable"
    assert invalid["evidence"]["normalized_fields"]["rows"] == []

    mixed = normalize_supplied_insights(_payload(_row(), _row(account_currency="MXN")))
    assert mixed["evidence"]["normalized_fields"]["single_currency"] is False
    assert mixed["evidence"]["normalized_fields"]["combined_spend"] is None


def test_scope_paging_rate_limit_and_time_range():
    wrong = normalize_supplied_insights(
        _payload(_row(), account_scope="fixture-account-b", paging={"cursors": {"after": CURSOR}}),
        expected_account_scope="fixture-account-a",
    )
    rendered = json.dumps(wrong)
    assert wrong["status"] == "account_scope_mismatch"
    assert wrong["evidence"]["normalized_fields"]["rows"] == []
    assert ACCOUNT_DIGITS not in rendered
    assert CURSOR not in rendered

    with pytest.raises(ValueError, match="unsafe insights input"):
        normalize_supplied_insights(_payload(_row()), expected_account_scope=ACCOUNT_DIGITS)

    mismatch = normalize_supplied_insights(
        _payload(_row()),
        requested_since="2026-03-01",
        requested_until="2026-03-07",
    )
    assert mismatch["status"] == "time_range_mismatch"
    assert mismatch["evidence"]["normalized_fields"]["rows"] == []

    stable = normalize_supplied_insights(_payload(_row()), as_of="2026-05-20")
    assert (
        stable["evidence"]["normalized_fields"]["rows"][0]["reporting_stability"]
        == "officially_unchanged_after_28_days"
    )

    limited = normalize_supplied_insights(
        {
            "error": {"code": 4, "error_subcode": 1504022, "message": f"act_{ACCOUNT_DIGITS} slow down"},
            "paging": {"next": CURSOR},
        }
    )
    assert limited["status"] == "rate_limited"
    assert ACCOUNT_DIGITS not in json.dumps(limited)
    assert CURSOR not in json.dumps(limited)

    denied = normalize_supplied_insights({"error": {"code": 100, "error_subcode": 3191001, "message": "permission"}})
    assert denied["status"] == "permission_denied"
    assert denied["evidence"]["normalized_fields"]["rows"] == []


def test_market_wide_claim_is_rejected_and_account_review_is_not_demand():
    document = normalize_supplied_insights(_payload(_row()))
    rejected = account_performance_view(document, claimed_use="market_demand")
    assert rejected["status"] == "claim_rejected"
    assert rejected["market_wide"] is False
    assert rejected["rows_released"] is False
    assert "12.50" not in json.dumps(rejected)

    review = account_performance_view(document, claimed_use="account_performance_review")
    assert review["status"] == "account_performance_only"
    assert review["market_wide"] is False
    assert review["ad_library_evidence"] is False
    assert review["opportunity_attention"] is False
    assert review["ad_launch_authorized"] is False
    assert review["combined_spend"] is None
    assert review["rows"][0]["spend"] == "12.50"


def test_demographic_and_secret_input_do_not_leak():
    document = normalize_supplied_insights(_payload(_row(gender="female", age="25-34")))
    rendered = json.dumps(document)
    assert "female" not in rendered
    assert "25-34" not in rendered
    assert document["evidence"]["normalized_fields"]["demographic_breakdown_discarded"] is True
    with pytest.raises(ValueError, match="unsafe insights input"):
        normalize_supplied_insights({"data": [{"note": CANARY}]})
    with pytest.raises(ValueError, match="unsafe insights input"):
        normalize_supplied_insights({"access_token": "abcdefghijklmnop", "data": []})


def test_operational_read_cannot_bypass_the_ledger_or_call_transport():
    calls = {"count": 0}

    def transport():
        calls["count"] += 1
        return _payload(_row())

    with pytest.raises(TypeError):
        operational_read(approval_granted=True, transport=transport)

    blocked = operational_read(loaded_keys=("META_ACCESS_TOKEN",), transport=transport)
    assert blocked["status"] == "blocked_by_approval_ledger"
    assert blocked["approval"]["blocked_in_current_mode"] is True
    assert blocked["approval"]["can_execute"] is False
    assert blocked["approval"]["ad_launch_can_execute"] is False
    assert blocked["approved_allowlist_has_meta_key"] is False
    assert blocked["credential_values_read"] is False
    assert blocked["rows"] == []
    assert blocked["fixture_fallback"] is False
    assert blocked["transport_called"] is False
    assert calls["count"] == 0
    rendered = json.dumps(blocked)
    assert "META_ACCESS_TOKEN" not in rendered
    assert ACCOUNT_DIGITS not in rendered

    fixture = read_supplied_fixture(_payload(_row()))
    assert fixture["evidence_mode"] == "supplied_fixture"
    assert fixture["fixture_used_as_operational_fallback"] is False


def test_provider_errors_empty_rows_and_future_dates_do_not_invent_metrics():
    limited = normalize_supplied_insights({"error": {"code": 100, "error_subcode": 1487534, "message": ACCOUNT_DIGITS}})
    assert limited["status"] == "data_per_call_limit"
    assert limited["evidence"]["normalized_fields"]["rows"] == []
    assert ACCOUNT_DIGITS not in json.dumps(limited)

    timed_out = normalize_supplied_insights({"error": {"code": 100, "error_subcode": 1504018}})
    assert timed_out["status"] == "timeout"
    assert timed_out["evidence"]["normalized_fields"]["rows"] == []

    empty = normalize_supplied_insights({"data": []})
    assert empty["status"] == "unavailable"
    assert empty["evidence"]["normalized_fields"]["rows"] == []
    assert empty["evidence"]["normalized_fields"]["combined_spend"] is None

    future = normalize_supplied_insights(_payload(_row()), as_of="2026-03-15")
    assert future["status"] == "unavailable"
    assert future["evidence"]["normalized_fields"]["rejected_row_counts"]["not_yet_reported"] == 1
    assert future["evidence"]["normalized_fields"]["rows"] == []


def test_rejected_uses_and_error_documents_release_no_metrics():
    document = normalize_supplied_insights(_payload(_row()))
    for claimed in ("competitor_intelligence", "product_opportunity_attention", "verified_sales", "ad_launch"):
        rejected = account_performance_view(document, claimed_use=claimed)
        assert rejected["status"] == "claim_rejected"
        assert rejected["rows_released"] is False
        assert rejected["rows"] == []
        assert rejected["market_wide"] is False
        assert "12.50" not in json.dumps(rejected)

    denied = normalize_supplied_insights({"error": {"code": 100, "error_subcode": 3191001}})
    held = account_performance_view(denied, claimed_use="account_performance_review")
    assert held["status"] == "evidence_not_releasable"
    assert held["rows_released"] is False
    assert held["opportunity_attention"] is False
    assert held["ad_library_evidence"] is False


def test_get_plan_is_blocked_and_contains_no_account_id():
    plan = build_blocked_get_plan(account_scope="fixture-account-a", since="2026-04-01", until="2026-04-07")
    assert plan["method"] == "GET"
    assert plan["post_allowed"] is False
    assert plan["account_id_included"] is False
    assert plan["status"] == "blocked_by_approval_ledger"
    assert plan["approval"]["blocked_in_current_mode"] is True
    assert plan["attribution_window_requested"] is False
    assert ACCOUNT_DIGITS not in json.dumps(plan)
    assert "access_token" not in json.dumps(plan)

    adapter_plan = blocked_get_plan(account_scope="fixture-account-a", since="2026-04-01", until="2026-04-07")
    assert adapter_plan["provider_call"] is False
    with pytest.raises(ValueError, match="unsafe insights input"):
        build_blocked_get_plan(account_scope=ACCOUNT_DIGITS, since="2026-04-01", until="2026-04-07")
