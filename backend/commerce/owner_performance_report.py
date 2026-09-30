"""Read-only owner performance projection over explicit period inputs.

This is a reporting adapter, not a scorer.  It sums observed and modeled
money with the canonical economics kernel and never treats a missing cost,
refund, spend, or currency as zero.  Campaign lift and realized profit are
unavailable unless every required input is present and same-currency.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

from backend.economics.kernel import (
    CurrencyMismatchError,
    EconomicsError,
    EvidenceRef,
    Money,
)

REPORT_VERSION = "owner-performance-report-v1"
ECONOMICS_AUTHORITY = "backend.economics.kernel"
ALLOWED_CLASSES = frozenset({"observed", "manual", "fixture", "modeled", "assumed"})
ALLOWED_METRICS = frozenset(
    {"revenue", "refunds", "product_cost", "shipping_cost", "fees", "ad_spend"}
)
PERIOD_BOUND = date.fromisoformat

MAX_REPORT_BYTES = 64 * 1024


class OwnerPerformanceReportError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _period(payload: Mapping[str, Any]) -> tuple[str, str]:
    start = payload.get("period_start")
    end = payload.get("period_end")
    if not isinstance(start, str) or not isinstance(end, str):
        raise OwnerPerformanceReportError("invalid_period")
    try:
        start_date = PERIOD_BOUND(start)
        end_date = PERIOD_BOUND(end)
    except ValueError as exc:
        raise OwnerPerformanceReportError("invalid_period") from exc
    if end_date < start_date:
        raise OwnerPerformanceReportError("period_end_before_start")
    return start, end


_CLASS_TO_STATE = {
    "observed": "observed",
    "manual": "observed",
    "fixture": "fixture",
    "modeled": "derived",
    "assumed": "assumed",
}


def _evidence_state(explicit: Any, evidence_class: str) -> str:
    if explicit is None:
        return _CLASS_TO_STATE[evidence_class]
    if not isinstance(explicit, str):
        raise OwnerPerformanceReportError("invalid_evidence_state")
    return explicit


def _evidence(raw: Mapping[str, Any] | None) -> EvidenceRef | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise OwnerPerformanceReportError("invalid_evidence")
    try:
        return EvidenceRef.from_dict(raw)
    except EconomicsError as exc:
        raise OwnerPerformanceReportError("invalid_evidence") from exc


def _money_view(money: Money | None, *, status: str, missing_reason: str | None = None) -> dict[str, Any]:
    if money is None:
        return {
            "status": status,
            "amount": None,
            "currency": None,
            "provenance": "unavailable",
            "evidence_state": "missing",
            "missing_reason": missing_reason,
        }
    payload = money.to_dict()
    payload["status"] = status
    payload["missing_reason"] = None
    return payload


def _parse_line(raw: Mapping[str, Any], index: int) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise OwnerPerformanceReportError("invalid_line")
    metric = raw.get("metric")
    evidence_class = raw.get("evidence_class")
    occurred_on = raw.get("occurred_on")
    if metric not in ALLOWED_METRICS:
        raise OwnerPerformanceReportError("invalid_metric")
    if evidence_class not in ALLOWED_CLASSES:
        raise OwnerPerformanceReportError("invalid_evidence_class")
    if not isinstance(occurred_on, str):
        raise OwnerPerformanceReportError("invalid_line_date")
    try:
        PERIOD_BOUND(occurred_on)
    except ValueError as exc:
        raise OwnerPerformanceReportError("invalid_line_date") from exc
    amount = raw.get("amount")
    currency = raw.get("currency")
    if amount is None or currency is None:
        raise OwnerPerformanceReportError("missing_line_money")
    try:
        money = Money(
            amount,
            currency,
            source=str(raw.get("source", evidence_class)),
            provenance=str(raw.get("provenance", evidence_class)),
            evidence_state=_evidence_state(raw.get("evidence_state"), evidence_class),
            evidence_ref=_evidence(raw.get("evidence_ref")),
        )
    except EconomicsError as exc:
        raise OwnerPerformanceReportError("invalid_line_money") from exc
    return {
        "index": index,
        "metric": metric,
        "evidence_class": evidence_class,
        "occurred_on": occurred_on,
        "campaign_id": raw.get("campaign_id"),
        "money": money,
    }


def _sum_metric(lines: list[dict[str, Any]], metric: str, currency: str) -> tuple[Money | None, list[str], str]:
    matched = [line for line in lines if line["metric"] == metric]
    if not matched:
        return None, [f"{metric}_absent"], "unavailable"
    total: Money | None = None
    classes: set[str] = set()
    for line in matched:
        money = line["money"]
        if money.currency != currency:
            raise OwnerPerformanceReportError("currency_mismatch")
        classes.add(line["evidence_class"])
        total = money if total is None else total + money
    if total is None:
        return None, [f"{metric}_absent"], "unavailable"
    if classes <= {"observed", "manual"}:
        status = "observed"
    elif classes <= {"fixture"}:
        status = "fixture"
    elif classes <= {"modeled", "assumed"}:
        status = "modeled"
    else:
        status = "mixed"
    return total, [], status


def _contribution(
    revenue: Money | None,
    refunds: Money | None,
    costs: list[tuple[str, Money | None]],
    missing: list[str],
) -> tuple[Money | None, str]:
    required_missing = [name for name, value in (("revenue", revenue), ("refunds", refunds), *costs) if value is None]
    if required_missing:
        missing.extend(
            f"{name}_required_for_contribution"
            for name in required_missing
            if f"{name}_required_for_contribution" not in missing
        )
        return None, "unavailable"
    assert revenue is not None and refunds is not None
    try:
        result = revenue - refunds
        for _, cost in costs:
            assert cost is not None
            result = result - cost
    except CurrencyMismatchError as exc:
        raise OwnerPerformanceReportError("currency_mismatch") from exc
    return result, "derived"


def build_owner_performance_report(payload: Mapping[str, Any]) -> "OwnerPerformanceReport":
    if not isinstance(payload, Mapping):
        raise OwnerPerformanceReportError("payload_must_be_object")
    currency = payload.get("currency")
    if not isinstance(currency, str):
        raise OwnerPerformanceReportError("invalid_currency")
    try:
        Money.zero(currency)
    except EconomicsError as exc:
        raise OwnerPerformanceReportError("invalid_currency") from exc
    period_start, period_end = _period(payload)
    raw_lines = payload.get("lines", ())
    if not isinstance(raw_lines, (list, tuple)):
        raise OwnerPerformanceReportError("invalid_lines")
    parsed: list[dict[str, Any]] = []
    excluded_after_period = 0
    excluded_before_period = 0
    for index, raw in enumerate(raw_lines):
        line = _parse_line(raw, index)
        if line["occurred_on"] < period_start:
            excluded_before_period += 1
            continue
        if line["occurred_on"] > period_end:
            excluded_after_period += 1
            continue
        parsed.append(line)
    parsed.sort(key=lambda item: (item["occurred_on"], item["metric"], item["index"]))

    missing: list[str] = []
    revenue, miss, revenue_status = _sum_metric(parsed, "revenue", currency)
    missing.extend(miss)
    refunds, miss, refunds_status = _sum_metric(parsed, "refunds", currency)
    missing.extend(miss)
    product_cost, miss, product_status = _sum_metric(parsed, "product_cost", currency)
    missing.extend(miss)
    shipping, miss, shipping_status = _sum_metric(parsed, "shipping_cost", currency)
    missing.extend(miss)
    fees, miss, fees_status = _sum_metric(parsed, "fees", currency)
    missing.extend(miss)
    ad_spend, miss, spend_status = _sum_metric(parsed, "ad_spend", currency)
    missing.extend(miss)

    contribution, contribution_status = _contribution(
        revenue,
        refunds,
        [
            ("product_cost", product_cost),
            ("shipping_cost", shipping),
            ("fees", fees),
        ],
        missing,
    )
    realized_profit_status = "unavailable"
    realized_profit = None
    if contribution is not None and ad_spend is not None:
        realized_profit = contribution - ad_spend
        realized_profit_status = "derived"
    elif ad_spend is None:
        missing.append("ad_spend_required_for_realized_profit")

    campaign_rows: list[dict[str, Any]] = []
    campaign_ids = sorted({line["campaign_id"] for line in parsed if line["campaign_id"]})
    for campaign_id in campaign_ids:
        group = [line for line in parsed if line["campaign_id"] == campaign_id]
        spend, _, status = _sum_metric(group, "ad_spend", currency)
        attributed_revenue, _, rev_status = _sum_metric(group, "revenue", currency)
        campaign_rows.append(
            {
                "campaign_id": campaign_id,
                "ad_spend": _money_view(spend, status=status, missing_reason=None if spend else "ad_spend_absent"),
                "attributed_revenue": _money_view(
                    attributed_revenue,
                    status=rev_status,
                    missing_reason=None if attributed_revenue else "attribution_absent",
                ),
                "lift": _money_view(None, status="unavailable", missing_reason="causal_lift_unsupported"),
                "causal_attribution": False,
            }
        )

    evidence_classes = sorted({line["evidence_class"] for line in parsed})
    quality = {
        "line_count": len(parsed),
        "excluded_before_period": excluded_before_period,
        "excluded_after_period": excluded_after_period,
        "evidence_classes": evidence_classes,
        "confidence": "high" if evidence_classes == ["observed"] and not missing else "partial" if parsed else "none",
        "claims": {
            "campaign_lift": False,
            "realized_profit": realized_profit_status != "unavailable",
            "causal_attribution": False,
        },
    }
    body = {
        "schema": REPORT_VERSION,
        "period_start": period_start,
        "period_end": period_end,
        "currency": currency,
        "revenue": _money_view(revenue, status=revenue_status, missing_reason=None if revenue else "revenue_absent"),
        "refunds": _money_view(refunds, status=refunds_status, missing_reason=None if refunds else "refunds_absent"),
        "product_cost": _money_view(product_cost, status=product_status, missing_reason=None if product_cost else "product_cost_absent"),
        "shipping_cost": _money_view(shipping, status=shipping_status, missing_reason=None if shipping else "shipping_cost_absent"),
        "fees": _money_view(fees, status=fees_status, missing_reason=None if fees else "fees_absent"),
        "ad_spend": _money_view(ad_spend, status=spend_status, missing_reason=None if ad_spend else "ad_spend_absent"),
        "contribution": _money_view(
            contribution,
            status=contribution_status,
            missing_reason=None if contribution else "incomplete_contribution_inputs",
        ),
        "realized_profit": _money_view(
            realized_profit,
            status=realized_profit_status,
            missing_reason=None if realized_profit is not None else "incomplete_profit_inputs",
        ),
        "campaigns": campaign_rows,
        "missing_inputs": sorted(set(missing)),
        "explicit_zeros": sorted(
            name
            for name, value in (
                ("revenue", revenue),
                ("refunds", refunds),
                ("product_cost", product_cost),
                ("shipping_cost", shipping),
                ("fees", fees),
                ("ad_spend", ad_spend),
            )
            if value is not None and value.amount == 0
        ),
        "evidence_quality": quality,
        "authorities": {
            "economics": ECONOMICS_AUTHORITY,
            "reporting": "backend.commerce.owner_performance_report.build_owner_performance_report",
        },
        "safety": {
            "read_only": True,
            "network_calls": False,
            "provider_calls": False,
            "ads_launched": False,
            "payments_created": False,
            "publishing": False,
            "launch_authorized": False,
        },
    }
    encoded = _canonical(body)
    if len(encoded.encode("utf-8")) > MAX_REPORT_BYTES:
        raise OwnerPerformanceReportError("output_size_exceeded")
    return OwnerPerformanceReport(body=body, fingerprint=_fingerprint(body))


@dataclass(frozen=True)
class OwnerPerformanceReport:
    body: Mapping[str, Any]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.body)
        payload["fingerprint"] = self.fingerprint
        return payload


__all__ = [
    "ECONOMICS_AUTHORITY",
    "OwnerPerformanceReport",
    "OwnerPerformanceReportError",
    "REPORT_VERSION",
    "build_owner_performance_report",
]
