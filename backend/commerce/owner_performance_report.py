"""Read-only owner performance projection over explicit period inputs.

This is a reporting adapter, not a scorer.  It sums observed and modeled
money with the canonical economics kernel and never treats a missing cost,
refund, spend, or currency as zero.  Campaign lift and realized profit are
unavailable unless every required input is present and same-currency.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
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
_CALENDAR_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _calendar_date(value: str, code: str) -> date:
    """Accept only a calendar date. ``fromisoformat`` echoes its input, so arbitrary text never reaches it."""
    if not _CALENDAR_DATE.fullmatch(value):
        raise OwnerPerformanceReportError(code)
    try:
        return PERIOD_BOUND(value)
    except ValueError:
        raise OwnerPerformanceReportError(code) from None


MAX_REPORT_BYTES = 64 * 1024


class OwnerPerformanceReportError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _period(payload: Mapping[str, Any]) -> tuple[date, date]:
    start = payload.get("period_start")
    end = payload.get("period_end")
    if not isinstance(start, str) or not isinstance(end, str):
        raise OwnerPerformanceReportError("invalid_period")
    start_date = _calendar_date(start, "invalid_period")
    end_date = _calendar_date(end, "invalid_period")
    if end_date < start_date:
        raise OwnerPerformanceReportError("period_end_before_start")
    return start_date, end_date


_CLASS_TO_STATE = {
    "observed": "observed",
    "manual": "unknown",
    "fixture": "fixture",
    "modeled": "derived",
    "assumed": "assumed",
}


def _evidence_state(explicit: Any, evidence_class: str) -> str:
    expected = _CLASS_TO_STATE[evidence_class]
    if explicit is None or explicit == expected:
        return expected
    raise OwnerPerformanceReportError("invalid_evidence_state")


def _rollup_status(classes: set[str]) -> str:
    if len(classes) == 1:
        return next(iter(classes))
    if not classes:
        return "unavailable"
    return "mixed"


def _public_evidence_state(classes: set[str]) -> str:
    if len(classes) != 1:
        return "unknown"
    return _CLASS_TO_STATE[next(iter(classes))]


def _evidence(raw: Mapping[str, Any] | None, evidence_class: str) -> EvidenceRef | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise OwnerPerformanceReportError("invalid_evidence")
    try:
        ref = EvidenceRef.from_dict(raw)
    except EconomicsError as exc:
        raise OwnerPerformanceReportError("invalid_evidence") from exc
    if evidence_class != "observed" and ref.evidence_state in {"observed", "verified", "live_readonly"}:
        raise OwnerPerformanceReportError("invalid_evidence")
    return ref


def _money_view(
    money: Money | None,
    *,
    status: str,
    classes: set[str] | None = None,
    missing_reason: str | None = None,
    aggregated: bool = False,
) -> dict[str, Any]:
    evidence_classes = sorted(classes or ())
    if money is None:
        return {
            "status": status,
            "amount": None,
            "currency": None,
            "provenance": "unavailable",
            "evidence_state": "missing",
            "evidence_classes": evidence_classes,
            "missing_reason": missing_reason,
        }
    payload = money.to_dict()
    payload["status"] = status
    payload["evidence_classes"] = evidence_classes
    class_state = _public_evidence_state(set(evidence_classes))
    # A sum of observed lines is not itself one observation. Mixed and non-observed
    # classes keep their class state; contribution formulas still pass status "derived".
    published_state = "derived" if status == "derived" or (aggregated and class_state == "observed") else class_state
    payload["evidence_state"] = published_state
    ref = payload.get("evidence_ref")
    if status == "derived" or aggregated or not isinstance(ref, dict) or ref.get("evidence_state") != published_state:
        payload["evidence_ref"] = None
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
    occurred_on = _calendar_date(occurred_on, "invalid_line_date").isoformat()
    source = raw.get("source", evidence_class)
    provenance = raw.get("provenance", evidence_class)
    if not isinstance(source, str) or not isinstance(provenance, str):
        raise OwnerPerformanceReportError("invalid_line")
    campaign_id = raw.get("campaign_id")
    if campaign_id in (None, ""):
        campaign_id = None
    elif (
        not isinstance(campaign_id, str)
        or len(campaign_id) > 128
        or any(unicodedata.category(char) == "Cc" for char in campaign_id)
    ):
        raise OwnerPerformanceReportError("invalid_campaign")
    amount = raw.get("amount")
    currency = raw.get("currency")
    if amount is None or currency is None:
        raise OwnerPerformanceReportError("missing_line_money")
    try:
        money = Money(
            amount,
            currency,
            source=source,
            provenance=provenance,
            evidence_state=_evidence_state(raw.get("evidence_state"), evidence_class),
            evidence_ref=_evidence(raw.get("evidence_ref"), str(evidence_class)),
        )
    except EconomicsError as exc:
        raise OwnerPerformanceReportError("invalid_line_money") from exc
    return {
        "index": index,
        "metric": metric,
        "evidence_class": evidence_class,
        "occurred_on": occurred_on,
        "campaign_id": campaign_id,
        "money": money,
    }


def _sum_metric(lines: list[dict[str, Any]], metric: str, currency: str) -> tuple[Money | None, list[str], str, set[str]]:
    matched = [line for line in lines if line["metric"] == metric]
    if not matched:
        return None, [f"{metric}_absent"], "unavailable", set()
    total: Money | None = None
    classes: set[str] = set()
    for line in matched:
        money = line["money"]
        if money.currency != currency:
            raise OwnerPerformanceReportError("currency_mismatch")
        classes.add(line["evidence_class"])
        total = money if total is None else total + money
    if total is None:
        return None, [f"{metric}_absent"], "unavailable", set()
    if len(matched) > 1:
        # A kernel sum keeps the left line's evidence_ref. That ref does not cover the total.
        total = Money(
            total.amount,
            total.currency,
            source=total.source,
            provenance=total.provenance,
            evidence_state=total.evidence_state,
            evidence_ref=None,
        )
    return total, [], _rollup_status(classes), classes


def _aggregated(lines: list[dict[str, Any]], metric: str) -> bool:
    return sum(line["metric"] == metric for line in lines) > 1


def _recorded_zero(lines: list[dict[str, Any]], metric: str) -> bool:
    matched = [line for line in lines if line["metric"] == metric]
    return bool(matched) and all(line["money"].amount == 0 for line in matched)


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
        currency = Money.zero(currency).currency
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
        occurred_on = date.fromisoformat(line["occurred_on"])
        if occurred_on < period_start:
            excluded_before_period += 1
            continue
        if occurred_on > period_end:
            excluded_after_period += 1
            continue
        line["occurred_on"] = occurred_on.isoformat()
        parsed.append(line)
    parsed.sort(key=lambda item: (
        item["occurred_on"],
        item["metric"],
        item["campaign_id"] or "",
        item["evidence_class"],
        str(item["money"].amount),
        _canonical(item["money"].evidence_ref.to_dict()) if item["money"].evidence_ref else "",
    ))

    missing: list[str] = []
    revenue, miss, revenue_status, revenue_classes = _sum_metric(parsed, "revenue", currency)
    missing.extend(miss)
    refunds, miss, refunds_status, refund_classes = _sum_metric(parsed, "refunds", currency)
    missing.extend(miss)
    product_cost, miss, product_status, product_classes = _sum_metric(parsed, "product_cost", currency)
    missing.extend(miss)
    shipping, miss, shipping_status, shipping_classes = _sum_metric(parsed, "shipping_cost", currency)
    missing.extend(miss)
    fees, miss, fees_status, fee_classes = _sum_metric(parsed, "fees", currency)
    missing.extend(miss)
    ad_spend, miss, spend_status, spend_classes = _sum_metric(parsed, "ad_spend", currency)
    missing.extend(miss)
    contribution_classes = revenue_classes | refund_classes | product_classes | shipping_classes | fee_classes

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
        spend, _, status, spend_row_classes = _sum_metric(group, "ad_spend", currency)
        attributed_revenue, _, rev_status, revenue_row_classes = _sum_metric(group, "revenue", currency)
        campaign_rows.append(
            {
                "campaign_id": campaign_id,
                "ad_spend": _money_view(
                    spend,
                    status=status,
                    classes=spend_row_classes,
                    missing_reason=None if spend else "ad_spend_absent",
                    aggregated=_aggregated(group, "ad_spend"),
                ),
                "attributed_revenue": _money_view(
                    attributed_revenue,
                    status=rev_status,
                    classes=revenue_row_classes,
                    missing_reason=None if attributed_revenue else "revenue_absent",
                    aggregated=_aggregated(group, "revenue"),
                ),
                "lift": _money_view(None, status="unavailable", missing_reason="causal_lift_unsupported"),
                "causal_attribution": False,
                "ads_ran_proven": False,
            }
        )

    evidence_classes = sorted({line["evidence_class"] for line in parsed})
    profit_classes = contribution_classes | spend_classes
    quality = {
        "line_count": len(parsed),
        "excluded_before_period": excluded_before_period,
        "excluded_after_period": excluded_after_period,
        "evidence_classes": evidence_classes,
        "confidence": "high" if evidence_classes == ["observed"] and not missing else "partial" if parsed else "none",
        "claims": {
            "campaign_lift": False,
            "realized_profit": realized_profit is not None and profit_classes == {"observed"},
            "causal_attribution": False,
        },
    }
    body = {
        "schema": REPORT_VERSION,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "currency": currency,
        "revenue": _money_view(revenue, status=revenue_status, classes=revenue_classes, missing_reason=None if revenue else "revenue_absent", aggregated=_aggregated(parsed, "revenue")),
        "refunds": _money_view(refunds, status=refunds_status, classes=refund_classes, missing_reason=None if refunds else "refunds_absent", aggregated=_aggregated(parsed, "refunds")),
        "product_cost": _money_view(product_cost, status=product_status, classes=product_classes, missing_reason=None if product_cost else "product_cost_absent", aggregated=_aggregated(parsed, "product_cost")),
        "shipping_cost": _money_view(shipping, status=shipping_status, classes=shipping_classes, missing_reason=None if shipping else "shipping_cost_absent", aggregated=_aggregated(parsed, "shipping_cost")),
        "fees": _money_view(fees, status=fees_status, classes=fee_classes, missing_reason=None if fees else "fees_absent", aggregated=_aggregated(parsed, "fees")),
        "ad_spend": _money_view(ad_spend, status=spend_status, classes=spend_classes, missing_reason=None if ad_spend else "ad_spend_absent", aggregated=_aggregated(parsed, "ad_spend")),
        "contribution": _money_view(
            contribution,
            status=contribution_status,
            classes=contribution_classes,
            missing_reason=None if contribution else "incomplete_contribution_inputs",
        ),
        "realized_profit": _money_view(
            realized_profit,
            status=realized_profit_status,
            classes=profit_classes,
            missing_reason=None if realized_profit is not None else "incomplete_profit_inputs",
        ),
        "campaigns": campaign_rows,
        "missing_inputs": sorted(set(missing)),
        "explicit_zeros": sorted(
            name
            for name in ("revenue", "refunds", "product_cost", "shipping_cost", "fees", "ad_spend")
            if _recorded_zero(parsed, name)
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
