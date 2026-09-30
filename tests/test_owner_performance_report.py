"""Fixture-backed tests for the owner performance reporting projection."""
from __future__ import annotations

import pytest

from backend.commerce.owner_performance_report import (
    REPORT_VERSION,
    OwnerPerformanceReportError,
    build_owner_performance_report,
)


def _line(metric, amount, occurred_on="2026-09-10", evidence_class="observed", currency="USD", campaign_id=None):
    payload = {
        "metric": metric,
        "amount": amount,
        "currency": currency,
        "occurred_on": occurred_on,
        "evidence_class": evidence_class,
    }
    if campaign_id is not None:
        payload["campaign_id"] = campaign_id
    return payload


def _base(**extra):
    payload = {
        "currency": "USD",
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
        "lines": [
            _line("revenue", "100.00"),
            _line("refunds", "10.00"),
            _line("product_cost", "40.00"),
            _line("shipping_cost", "5.00"),
            _line("fees", "3.00"),
            _line("ad_spend", "12.00", campaign_id="camp-a"),
        ],
    }
    payload.update(extra)
    return payload


def test_complete_observed_period_is_reproducible_and_derived():
    first = build_owner_performance_report(_base()).to_dict()
    second = build_owner_performance_report(_base()).to_dict()
    assert first == second
    assert first["schema"] == REPORT_VERSION
    assert first["revenue"]["amount"] == "100.00"
    assert first["refunds"]["amount"] == "10.00"
    assert first["contribution"]["status"] == "derived"
    assert first["contribution"]["amount"] == "42.00"
    assert first["realized_profit"]["amount"] == "30.00"
    assert first["evidence_quality"]["claims"]["campaign_lift"] is False
    assert first["evidence_quality"]["claims"]["causal_attribution"] is False
    assert first["campaigns"][0]["lift"]["status"] == "unavailable"
    assert first["safety"]["ads_launched"] is False


def test_missing_refunds_are_not_zero_and_block_contribution():
    payload = _base()
    payload["lines"] = [line for line in payload["lines"] if line["metric"] != "refunds"]
    report = build_owner_performance_report(payload).to_dict()
    assert report["refunds"]["amount"] is None
    assert report["refunds"]["status"] == "unavailable"
    assert report["contribution"]["status"] == "unavailable"
    assert "refunds_absent" in report["missing_inputs"]
    assert "refunds" not in report["explicit_zeros"]
    assert report["evidence_quality"]["claims"]["realized_profit"] is False


def test_explicit_zero_refund_is_distinct_from_missing():
    payload = _base()
    payload["lines"] = [line for line in payload["lines"] if line["metric"] != "refunds"]
    payload["lines"].append(_line("refunds", "0"))
    report = build_owner_performance_report(payload).to_dict()
    assert report["refunds"]["amount"] == "0"
    assert "refunds" in report["explicit_zeros"]
    assert report["contribution"]["status"] == "derived"
    assert report["contribution"]["amount"] == "52.00"


def test_currency_mismatch_is_rejected():
    payload = _base()
    payload["lines"].append(_line("revenue", "10", currency="MXN"))
    with pytest.raises(OwnerPerformanceReportError) as exc:
        build_owner_performance_report(payload)
    assert exc.value.code == "currency_mismatch"


def test_period_boundaries_exclude_outside_lines():
    payload = _base()
    payload["lines"].append(_line("revenue", "999", occurred_on="2026-08-31"))
    payload["lines"].append(_line("revenue", "888", occurred_on="2026-10-01"))
    report = build_owner_performance_report(payload).to_dict()
    assert report["revenue"]["amount"] == "100.00"
    assert report["evidence_quality"]["excluded_before_period"] == 1
    assert report["evidence_quality"]["excluded_after_period"] == 1


def test_inverted_period_is_rejected():
    with pytest.raises(OwnerPerformanceReportError) as exc:
        build_owner_performance_report(_base(period_start="2026-09-30", period_end="2026-09-01"))
    assert exc.value.code == "period_end_before_start"


def test_partial_modeled_and_fixture_lines_are_labeled_not_observed_profit():
    payload = _base(
        lines=[
            _line("revenue", "80", evidence_class="fixture"),
            _line("refunds", "0", evidence_class="modeled"),
            _line("product_cost", "20", evidence_class="assumed"),
            _line("shipping_cost", "2", evidence_class="manual"),
            _line("fees", "1", evidence_class="observed"),
        ]
    )
    report = build_owner_performance_report(payload).to_dict()
    assert report["revenue"]["status"] == "fixture"
    assert report["ad_spend"]["status"] == "unavailable"
    assert report["contribution"]["status"] == "derived"
    assert report["realized_profit"]["status"] == "unavailable"
    assert report["evidence_quality"]["confidence"] == "partial"
    classes = report["evidence_quality"]["evidence_classes"]
    assert classes == sorted(classes)


def test_campaign_rows_are_ordered_and_do_not_claim_lift():
    payload = _base(
        lines=[
            _line("ad_spend", "5", campaign_id="camp-b"),
            _line("ad_spend", "7", campaign_id="camp-a"),
            _line("revenue", "20", campaign_id="camp-a"),
        ]
    )
    report = build_owner_performance_report(payload).to_dict()
    assert [row["campaign_id"] for row in report["campaigns"]] == ["camp-a", "camp-b"]
    assert report["campaigns"][1]["attributed_revenue"]["status"] == "unavailable"
    assert report["campaigns"][0]["causal_attribution"] is False
