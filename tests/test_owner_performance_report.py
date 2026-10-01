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
    assert first["contribution"]["evidence_state"] == "derived"
    assert first["realized_profit"]["amount"] == "30.00"
    assert first["realized_profit"]["evidence_state"] == "derived"
    assert first["evidence_quality"]["claims"]["realized_profit"] is True
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
    assert report["campaigns"][1]["attributed_revenue"]["amount"] is None
    assert report["campaigns"][0]["causal_attribution"] is False
    assert report["campaigns"][0]["ads_ran_proven"] is False
    assert report["campaigns"][0]["lift"]["status"] == "unavailable"


def test_manual_and_mixed_inputs_are_not_labeled_observed():
    manual = build_owner_performance_report(
        _base(lines=[_line("ad_spend", "12.00", evidence_class="manual", campaign_id="camp-a")])
    ).to_dict()
    assert manual["ad_spend"]["status"] == "manual"
    assert manual["ad_spend"]["evidence_state"] != "observed"
    assert manual["ad_spend"]["evidence_classes"] == ["manual"]
    assert manual["campaigns"][0]["ads_ran_proven"] is False
    assert manual["campaigns"][0]["causal_attribution"] is False
    assert manual["safety"]["ads_launched"] is False
    mixed = build_owner_performance_report(
        _base(lines=[
            _line("revenue", "10.00", evidence_class="observed"),
            _line("revenue", "5.00", evidence_class="manual"),
        ])
    ).to_dict()
    assert mixed["revenue"]["status"] == "mixed"
    assert mixed["revenue"]["evidence_state"] != "observed"
    assert mixed["revenue"]["evidence_classes"] == ["manual", "observed"]
    assert mixed["revenue"]["amount"] == "15.00"


def test_assumed_cost_is_not_relabeled_modeled():
    report = build_owner_performance_report(
        _base(lines=[_line("product_cost", "4.00", evidence_class="assumed")])
    ).to_dict()
    assert report["product_cost"]["status"] == "assumed"
    assert report["product_cost"]["evidence_classes"] == ["assumed"]
    assert report["product_cost"]["evidence_state"] == "assumed"


def test_fixture_profit_is_calculated_without_a_realized_claim():
    report = build_owner_performance_report(
        _base(lines=[
            _line("revenue", "80.00", evidence_class="fixture"),
            _line("refunds", "0.00", evidence_class="fixture"),
            _line("product_cost", "20.00", evidence_class="fixture"),
            _line("shipping_cost", "0.00", evidence_class="fixture"),
            _line("fees", "0.00", evidence_class="fixture"),
            _line("ad_spend", "5.00", evidence_class="fixture", campaign_id="camp-a"),
        ])
    ).to_dict()
    assert report["realized_profit"]["status"] == "derived"
    assert report["realized_profit"]["amount"] == "55.00"
    assert report["realized_profit"]["evidence_state"] == "derived"
    assert report["evidence_quality"]["claims"]["realized_profit"] is False
    assert report["evidence_quality"]["claims"]["campaign_lift"] is False
    assert report["campaigns"][0]["lift"]["amount"] is None


def test_same_day_reorder_keeps_fingerprint_and_period_edges_include_bounds():
    lines = [
        _line("revenue", "10.00", evidence_class="fixture"),
        _line("revenue", "1.00", evidence_class="observed"),
    ]
    first = build_owner_performance_report(_base(lines=lines))
    second = build_owner_performance_report(_base(lines=list(reversed(lines))))
    assert first.fingerprint == second.fingerprint
    assert first.to_dict()["revenue"]["status"] == "mixed"
    assert first.to_dict()["revenue"]["amount"] == "11.00"
    bounded = build_owner_performance_report(
        _base(lines=[
            _line("revenue", "1.00", occurred_on="2026-09-01"),
            _line("revenue", "2.00", occurred_on="2026-09-30"),
            _line("revenue", "9.00", occurred_on="2026-08-31"),
        ])
    ).to_dict()
    assert bounded["revenue"]["amount"] == "3.00"
    assert bounded["period_start"] == "2026-09-01"
    assert bounded["period_end"] == "2026-09-30"
    assert bounded["evidence_quality"]["excluded_before_period"] == 1
    left = _line("revenue", "1.00")
    right = _line("revenue", "1.00")
    left["evidence_ref"] = {"evidence_id": "ev-b", "evidence_state": "observed"}
    right["evidence_ref"] = {"evidence_id": "ev-a", "evidence_state": "observed"}
    forward = build_owner_performance_report(_base(lines=[left, right]))
    backward = build_owner_performance_report(_base(lines=[right, left]))
    assert forward.fingerprint == backward.fingerprint


def test_currency_case_is_canonical_and_not_converted():
    report = build_owner_performance_report(
        _base(currency="usd", lines=[_line("revenue", "10.00", currency="USD")])
    ).to_dict()
    assert report["currency"] == "USD"
    assert report["revenue"]["currency"] == "USD"
    assert report["revenue"]["amount"] == "10.00"
    payload = _base(lines=[_line("revenue", "10.00", currency="mxn")])
    with pytest.raises(OwnerPerformanceReportError) as exc:
        build_owner_performance_report(payload)
    assert exc.value.code == "currency_mismatch"
    assert report["revenue"]["amount"] != "0"
