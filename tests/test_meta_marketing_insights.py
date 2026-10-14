from __future__ import annotations

import json

import pytest

from backend.adapters.research.meta_marketing_insights import operational_read, read_supplied_fixture
from evaluation.commerce.meta_marketing_insights import SCHEMA, normalize_supplied_insights

CANARY = "insights-canary@example.com"


def _row(**extra):
    document = {
        "date_start": "2026-04-01",
        "date_stop": "2026-04-07",
        "impressions": "100",
        "clicks": "4",
        "spend": "12.50",
        "account_currency": "USD",
        "account_id": "1234567890",
        "actions": [{"action_type": "link_click", "value": "4"}],
    }
    document.update(extra)
    return {"data": [document]}


def test_supplied_fixture_keeps_aggregate_metrics_and_drops_identity():
    document = normalize_supplied_insights(_row())
    assert document["schema"] == SCHEMA
    assert document["status"] == "supplied_fixture"
    assert document["live_observation"] is False
    assert document["provider_call"] is False
    assert document["credentials_read"] is False
    row = document["evidence"]["normalized_fields"]["rows"][0]
    assert row["impressions"] == 100
    assert row["clicks"] == 4
    assert row["spend"] == 12.5
    assert row["account_currency"] == "USD"
    assert row["account_id_stored"] is False
    assert row["ctr_recomputed"] is False
    assert row["platform_reported_actions"][0]["independently_verified_sales"] is False
    rendered = json.dumps(document)
    assert "1234567890" not in rendered
    assert document["evidence"]["evidence_category"] == "ProviderRunEvidence"
    assert document["evidence"]["can_feed_reports"] is False
    for key, value in document["authority"].items():
        assert value is False, key


def test_ctr_is_copied_not_recomputed():
    document = normalize_supplied_insights(_row(ctr="0.5"))
    row = document["evidence"]["normalized_fields"]["rows"][0]
    assert row["ctr"] == 0.5
    assert row["ctr_recomputed"] is False


def test_demographic_breakdown_is_not_stored():
    document = normalize_supplied_insights(_row(gender="female", age="25-34"))
    rendered = json.dumps(document)
    assert "female" not in rendered
    assert "25-34" not in rendered
    assert document["evidence"]["normalized_fields"]["demographic_breakdown_discarded"] is True


def test_wide_window_and_secret_input_do_not_leak():
    wide = normalize_supplied_insights(_row(date_start="2024-01-01", date_stop="2026-04-07"))
    assert wide["status"] == "unavailable"
    assert wide["evidence"]["normalized_fields"]["rows"] == []
    with pytest.raises(ValueError, match="unsafe insights input"):
        normalize_supplied_insights({"data": [{"note": CANARY}]})
    with pytest.raises(ValueError, match="unsafe insights input"):
        normalize_supplied_insights({"access_token": "abcdefghijklmnop", "data": []})


def test_operational_read_never_calls_transport_or_uses_a_fixture():
    calls = {"count": 0}

    def transport():
        calls["count"] += 1
        return _row()

    blocked = operational_read(approval_granted=False, transport=transport)
    assert blocked["status"] == "approval_unavailable"
    assert blocked["rows"] == []
    assert blocked["fixture_fallback"] is False
    assert blocked["credential_values_read"] is False
    assert calls["count"] == 0

    missing = operational_read(approval_granted=True, loaded_keys=("TIKTOK_ACCESS_TOKEN",), transport=transport)
    assert missing["status"] == "credential_unavailable"
    assert missing["approved_allowlist_has_meta_key"] is False
    assert calls["count"] == 0
    assert "TIKTOK_ACCESS_TOKEN" not in json.dumps(missing)

    fixture = read_supplied_fixture(_row())
    assert fixture["evidence_mode"] == "supplied_fixture"
    assert fixture["fixture_used_as_operational_fallback"] is False
