"""Canonical events -> owner performance report payload (read-only adapter).

Turns events that already exist in MarketOS into the ``lines`` payload that
``backend.commerce.owner_performance_report.build_owner_performance_report``
accepts. It is a translator, not a scorer and not a second report:

* It never supplies a missing value.  No event for a metric means that metric
  stays absent, so the report marks it ``unavailable``.  It never emits a zero
  line it did not read, and never infers a currency, class, date or amount.
* Currency, period, evidence class and source references are carried through
  unchanged.  Every line's ``evidence_ref`` points back to its canonical event
  (event id, aggregate, replay hash).
* It never produces the ``observed`` class from these sources: the Shopify
  events are manual/fixture imports, not live platform reads.
* It claims no campaign lift, no causal attribution and no platform validation.
  ``AttributionClaimObserved`` and ad-platform claimed revenue are deliberately
  not mapped.

Supported events (everything else is counted, with a reason, in ``coverage``):

``shopify_order_observed`` (``backend.ecommerce.shopify_readonly.events``)
    -> ``revenue`` from ``subtotal_price`` (excludes tax and shipping; discounts
    already applied).  Class ``fixture`` or ``manual`` from the import mode.
``RefundIssued`` / ``SupplierCostObserved`` / ``AdSpendObserved`` (``backend.ledger.events``)
    -> ``refunds`` / ``product_cost`` / ``ad_spend``, ONLY when the event itself
    records a ``currency`` and an ``evidence_class``.  The ledger writers do not
    record either today, so on current data these are counted as unsupported
    rather than guessed.  A recorded amount of exactly 0 is also refused: the
    writers default ``amount`` to ``0.0``, so an explicit zero cannot be told
    apart from "not provided".

References are privacy-safe: an event's ``source`` (which may be a local path or a
URL with credentials or a query string), ids and labels are copied into
``evidence_ref`` only when they match a conservative pattern; anything else is
withheld or replaced by a short digest, never echoed.  A malformed event can
therefore be excluded or sanitised but can never make the report builder reject
the whole report.

Idempotency: events are de-duplicated by ``event_id``; Shopify orders are
further de-duplicated by ``(workspace, order_id)`` across re-imports, newest
observation wins, and a differing older observation is counted as a conflict.
Output is independent of input order and of duplicate presence.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence

from backend.contracts.events import Event
from backend.economics.kernel import EconomicsError, Money

ADAPTER_VERSION = "owner-performance-event-adapter-v1"
REPORT_AUTHORITY = "backend.commerce.owner_performance_report.build_owner_performance_report"
MAX_EVENTS = 50_000

SHOPIFY_ORDER_EVENT = "shopify_order_observed"
SHOPIFY_IMPORT_MODE_CLASS = {"fixture": "fixture", "manual": "manual"}
# Order statuses that count as a (gross) sale. Refund AMOUNTS are not in the event,
# so refunded statuses stay revenue-eligible but flag that refunds are unavailable.
SHOPIFY_REVENUE_STATUSES = frozenset({"paid", "partially_refunded", "refunded"})
SHOPIFY_REFUND_STATUSES = frozenset({"partially_refunded", "refunded"})

LEDGER_METRIC = {
    "RefundIssued": "refunds",
    "SupplierCostObserved": "product_cost",
    "AdSpendObserved": "ad_spend",
}
LEDGER_EVIDENCE_CLASSES = frozenset({"observed", "manual", "fixture", "modeled", "assumed"})

# Event types that exist and look money-related but are intentionally NOT mapped.
NOT_MAPPED_REASONS = {
    "OrderCreated": "ledger revenue has no currency/evidence class and would double count Shopify orders",
    "PaymentCaptured": "cash collected is not revenue; no currency/evidence class recorded",
    "OrderCanceled": "no amount; cancellations are handled via Shopify order status",
    "ChargebackOpened": "no currency/evidence class recorded; not a refund",
    "FulfillmentCompleted": "no amount",
    "AttributionClaimObserved": "platform-claimed revenue; attribution is never inferred",
    "commerce_mvp_unit_economics_estimated": "modeled, advisory dry-run estimate; not period evidence",
    "metrics.ingested": "runtime metrics blob; no currency, period or evidence class",
}

# Reference hygiene.  The report builder rejects control characters in any evidence
# field (one bad event would fail the whole report) and its output reaches the API and UI.
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@=+-]{0,127}$")
_SAFE_SOURCE_REF = re.compile(r"^[a-z][a-z0-9+.-]{0,15}://[A-Za-z0-9._-]{1,64}$")
_SAFE_TIMESTAMP = re.compile(r"^[0-9T:.+Z -]{1,40}$")
_AMOUNT_LIMIT = Decimal("1e15")
_AMOUNT_MAX_PLACES = 8

_SHOPIFY_SIGNATURE_KEYS = ("order_id", "currency", "subtotal_price", "created_at", "financial_status", "cancelled_at")


class OwnerPerformanceEventAdapterError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PerformanceEventAdaptation:
    """``payload`` feeds the report builder; ``coverage`` says exactly what was and was not used."""

    payload: Mapping[str, Any]
    coverage: Mapping[str, Any]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {"payload": dict(self.payload), "coverage": dict(self.coverage), "fingerprint": self.fingerprint}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _validate_inputs(workspace_id: Any, period_start: Any, period_end: Any, currency: Any) -> tuple[str, date, date, str]:
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise OwnerPerformanceEventAdapterError("invalid_workspace")
    if not isinstance(period_start, str) or not isinstance(period_end, str):
        raise OwnerPerformanceEventAdapterError("invalid_period")
    try:
        start, end = date.fromisoformat(period_start), date.fromisoformat(period_end)
    except ValueError as exc:
        raise OwnerPerformanceEventAdapterError("invalid_period") from exc
    if end < start:
        raise OwnerPerformanceEventAdapterError("period_end_before_start")
    if not isinstance(currency, str):
        raise OwnerPerformanceEventAdapterError("invalid_currency")
    try:
        normalized = Money.zero(currency).currency
    except EconomicsError as exc:
        raise OwnerPerformanceEventAdapterError("invalid_currency") from exc
    return workspace_id, start, end, normalized


def _decimal(value: Any) -> Decimal | None:
    """Exact decimal for a real, finite, non-negative number; None otherwise (never a default)."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except Exception:  # noqa: BLE001 - any unparsable value is simply "not a usable amount"
        return None
    if not result.is_finite() or result < 0:
        return None
    return result


def _currency(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return Money.zero(value).currency
    except EconomicsError:
        return None


def _plausible(amount: Decimal) -> bool:
    """A money amount the report and UI can show: below 1e15 with at most 8 decimal places."""
    exponent = amount.as_tuple().exponent
    return amount < _AMOUNT_LIMIT and isinstance(exponent, int) and exponent >= -_AMOUNT_MAX_PLACES


def _plain(amount: Decimal) -> str:
    """Fixed-point text ("1000", never "1E+3") so the report and UI never see scientific notation."""
    return format(amount, "f")


def _digest(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8", "backslashreplace")).hexdigest()[:16]


def _safe_ref(value: Any) -> str:
    """The value itself when it is a plain identifier, else a stable short digest (never the raw text)."""
    return value if isinstance(value, str) and _SAFE_REF.fullmatch(value) else f"ref:{_digest(value)}"


def _safe_source(value: Any) -> str:
    """A bare ``scheme://label`` reference (for example ``manual://export-1``); paths, queries, userinfo and ports are withheld."""
    return value if isinstance(value, str) and _SAFE_SOURCE_REF.fullmatch(value) else ""


def _safe_label(value: Any) -> str:
    return value if isinstance(value, str) and _SAFE_REF.fullmatch(value) else "unrecognized_source"


def _date_as_written(value: Any) -> date | None:
    """Calendar date exactly as written in an ISO timestamp (no timezone shifting)."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip()).date()
    except ValueError:
        return None


def _epoch_datetime(value: float) -> datetime | None:
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _epoch_date(value: float) -> date | None:
    moment = _epoch_datetime(value)
    return moment.date() if moment is not None else None


def _event_workspace(event: Event) -> str | None:
    """Workspace the event belongs to; None when it cannot be established (never assumed)."""
    declared = event.workspace_id
    in_payload = event.payload.get("workspace_id")
    in_payload = in_payload if isinstance(in_payload, str) and in_payload.strip() else None
    if declared and in_payload and declared != in_payload:
        return ""  # contradictory: treated as unattributable below
    return declared or in_payload


def _evidence_ref(event: Event, *, state: str, extra_warnings: Sequence[str] = ()) -> dict[str, Any]:
    source = event.metadata.get("source")
    warnings = list(extra_warnings)
    if source and not _safe_source(source):
        warnings.append("source_reference_withheld")
    moment = _epoch_datetime(event.occurred_at)
    if moment is None:
        warnings.append("event_time_unavailable")
    return {
        "evidence_id": _safe_ref(event.event_id),
        "source_type": "canonical_event",
        "source_url": _safe_source(source),
        "document_ref": f"{_safe_label(event.aggregate_type)}:{_safe_ref(event.aggregate_id)}",
        "origin": _safe_label(event.source),
        "captured_at": moment.isoformat() if moment is not None else "",
        "extraction_method": ADAPTER_VERSION,
        "evidence_state": state,
        "snapshot_hash": event.replay_hash(),
        "warnings": warnings,
    }


_CLASS_STATE = {"manual": "unknown", "fixture": "fixture", "modeled": "derived", "assumed": "assumed", "observed": "observed"}


def _shopify_observation_key(event: Event) -> tuple[str, str] | None:
    order_id = event.payload.get("order_id")
    if not isinstance(order_id, str) or not order_id.strip():
        return None
    return ("shopify_order", order_id)


def _signature(event: Event) -> str:
    return _canonical({key: event.payload.get(key) for key in _SHOPIFY_SIGNATURE_KEYS})


def adapt_events_to_performance_report_payload(
    events: Sequence[Event],
    *,
    workspace_id: str,
    period_start: str,
    period_end: str,
    currency: str,
) -> PerformanceEventAdaptation:
    """Map supported canonical events for ONE workspace into report ``lines`` plus an exact coverage account."""
    workspace_id, start, end, currency = _validate_inputs(workspace_id, period_start, period_end, currency)
    if isinstance(events, (str, bytes)) or not isinstance(events, Sequence):
        raise OwnerPerformanceEventAdapterError("events_must_be_sequence")
    if len(events) > MAX_EVENTS:
        raise OwnerPerformanceEventAdapterError("too_many_events")
    if any(not isinstance(item, Event) for item in events):
        raise OwnerPerformanceEventAdapterError("invalid_event")

    excluded: Counter[str] = Counter()
    unsupported: Counter[str] = Counter()
    notes: Counter[str] = Counter()
    seen_ids: set[str] = set()
    duplicate_event_ids = 0
    shopify_latest: dict[tuple[str, str], Event] = {}
    shopify_dropped = 0
    shopify_conflicts = 0
    ledger_seen: set[str] = set()
    ledger_duplicates = 0
    lines: list[dict[str, Any]] = []
    source_refs: list[dict[str, str]] = []
    considered = 0

    # The replay hash is also the tie-breaker below: two events with the same id and time but
    # different content must resolve the same way whatever order the caller passed them in.
    hashed: list[tuple[Event, str]] = []
    for event in events:
        try:
            hashed.append((event, event.replay_hash()))
        except (ValueError, UnicodeError):
            excluded["event_not_serializable"] += 1

    # An event id is the canonical identity (the event repository ignores a repeated id), so the
    # earliest observation wins; a repeat whose content differs is counted, never silently merged.
    content_by_id: dict[str, set[str]] = {}
    for event, digest in hashed:
        content_by_id.setdefault(event.event_id, set()).add(digest)
    event_id_content_conflicts = sum(1 for digests in content_by_id.values() if len(digests) > 1)

    # Deterministic order regardless of how the caller sorted or repeated events.
    for event in (item[0] for item in sorted(hashed, key=lambda item: (item[0].occurred_at, item[0].event_id, item[1]))):
        if event.event_id in seen_ids:
            duplicate_event_ids += 1
            continue
        seen_ids.add(event.event_id)

        is_shopify = event.event_type == SHOPIFY_ORDER_EVENT
        is_ledger = event.event_type in LEDGER_METRIC
        if not (is_shopify or is_ledger):
            unsupported[event.event_type] += 1
            continue

        scope = _event_workspace(event)
        if not scope:
            excluded["workspace_unattributed"] += 1
            continue
        if scope != workspace_id:
            excluded["other_workspace"] += 1
            continue
        considered += 1

        if is_shopify:
            key = _shopify_observation_key(event)
            if key is None:
                excluded["order_id_missing"] += 1
                continue
            previous = shopify_latest.get(key)
            if previous is not None:
                shopify_dropped += 1
                if _signature(previous) != _signature(event):
                    shopify_conflicts += 1
            shopify_latest[key] = event  # sorted ascending, so the newest observation wins
            continue

        fingerprint = hashlib.sha256(_canonical([event.event_type, scope, event.payload]).encode()).hexdigest()
        if fingerprint in ledger_seen:
            ledger_duplicates += 1
            continue
        ledger_seen.add(fingerprint)
        line = _ledger_line(event, excluded)
        if line is not None:
            lines.append(line)
            source_refs.append(_source_ref(event, line["metric"]))

    for event in shopify_latest.values():
        line = _shopify_line(event, currency, excluded, notes)
        if line is not None:
            lines.append(line)
            source_refs.append(_source_ref(event, "revenue"))

    # Currency is carried from each event; a different currency is never converted or merged.
    kept: list[dict[str, Any]] = []
    for line in lines:
        if line["currency"] != currency:
            excluded["currency_mismatch"] += 1
            continue
        kept.append(line)

    kept.sort(key=lambda item: (item["occurred_on"], item["metric"], item["evidence_ref"]["evidence_id"]))
    kept_ids = {line["evidence_ref"]["evidence_id"] for line in kept}
    source_refs = [ref for ref in source_refs if ref["event_id"] in kept_ids]
    source_refs.sort(key=lambda item: (item["metric"], item["event_id"]))
    in_period = sum(1 for line in kept if start <= date.fromisoformat(line["occurred_on"]) <= end)

    metrics_present = sorted({line["metric"] for line in kept})
    coverage: dict[str, Any] = {
        "adapter": ADAPTER_VERSION,
        "report_authority": REPORT_AUTHORITY,
        "workspace_id": workspace_id,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "currency": currency,
        "events_received": len(events),
        "duplicate_event_ids_ignored": duplicate_event_ids,
        "event_id_content_conflicts": event_id_content_conflicts,
        "events_considered": considered,
        "lines_emitted": len(kept),
        "lines_in_period": in_period,
        "period_filtering": "delegated_to_report",
        "date_policy": "calendar date as written in the source timestamp; no timezone shifting",
        "metrics_with_lines": metrics_present,
        "metrics_without_lines": sorted(
            {"revenue", "refunds", "product_cost", "shipping_cost", "fees", "ad_spend"} - set(metrics_present)
        ),
        "metrics_never_sourced": ["shipping_cost", "fees"],
        "excluded": dict(sorted(excluded.items())),
        "unsupported_event_types": dict(sorted(unsupported.items())),
        "intentionally_not_mapped": {name: reason for name, reason in sorted(NOT_MAPPED_REASONS.items()) if name in unsupported},
        "shopify_orders": {
            "distinct_orders": len(shopify_latest),
            "older_duplicate_observations_dropped": shopify_dropped,
            "conflicting_duplicate_observations": shopify_conflicts,
        },
        "ledger_duplicates_ignored": ledger_duplicates,
        "notes": dict(sorted(notes.items())),
        "source_refs": source_refs,
        # True only when every supported event that belonged to this workspace became a line.
        "all_supported_events_used": not excluded,
        "claims": {
            "campaign_lift": False,
            "causal_attribution": False,
            "ads_ran_proven": False,
            "live_platform_validated": False,
            "observed_class_produced": any(line["evidence_class"] == "observed" for line in kept),
        },
        "safety": {
            "read_only": True,
            "network_calls": False,
            "provider_calls": False,
            "mutated": False,
            "ads_launched": False,
            "payments_created": False,
            "publishing": False,
            "launch_authorized": False,
        },
    }
    payload = {"currency": currency, "period_start": start.isoformat(), "period_end": end.isoformat(), "lines": kept}
    fingerprint = hashlib.sha256(_canonical({"payload": payload, "coverage": coverage}).encode()).hexdigest()
    return PerformanceEventAdaptation(payload=payload, coverage=coverage, fingerprint=fingerprint)


def _source_ref(event: Event, metric: str) -> dict[str, str]:
    return {
        "metric": metric,
        "event_id": _safe_ref(event.event_id),
        "event_type": event.event_type,
        "aggregate": f"{_safe_label(event.aggregate_type)}:{_safe_ref(event.aggregate_id)}",
        "replay_hash": event.replay_hash(),
    }


def _shopify_line(event: Event, currency: str, excluded: Counter[str], notes: Counter[str]) -> dict[str, Any] | None:
    mode = event.metadata.get("import_mode")
    evidence_class = SHOPIFY_IMPORT_MODE_CLASS.get(mode) if isinstance(mode, str) else None
    if evidence_class is None:
        excluded["evidence_class_unrecognized"] += 1
        return None
    payload = event.payload
    if payload.get("cancelled_at"):
        excluded["order_cancelled"] += 1
        return None
    status = payload.get("financial_status")
    status = status.strip().lower() if isinstance(status, str) else ""
    if status not in SHOPIFY_REVENUE_STATUSES:
        excluded["order_not_paid"] += 1
        return None
    order_currency = _currency(payload.get("currency"))
    if order_currency is None:
        excluded["currency_unavailable"] += 1
        return None
    amount = _decimal(payload.get("subtotal_price"))
    if amount is None:
        excluded["amount_unavailable"] += 1
        return None
    if not _plausible(amount):
        excluded["amount_out_of_range"] += 1
        return None
    created = _date_as_written(payload.get("created_at"))
    if created is None:
        excluded["order_date_unavailable"] += 1
        return None

    written = payload.get("created_at").strip()  # parsed above, so a non-empty string
    warnings = ["amount_is_subtotal_excluding_tax_and_shipping", f"order_created_at={written if _SAFE_TIMESTAMP.fullmatch(written) else created.isoformat()}"]
    if status in SHOPIFY_REFUND_STATUSES:
        warnings.append("order_has_refund_status_refund_amount_not_in_event")
        notes["revenue_orders_with_unquantified_refunds"] += 1
    return {
        "metric": "revenue",
        "evidence_class": evidence_class,
        "occurred_on": created.isoformat(),
        "amount": _plain(amount),
        "currency": order_currency,
        "source": SHOPIFY_ORDER_EVENT,
        "provenance": f"canonical_event:{_safe_label(event.source)}:{mode}",
        "evidence_ref": _evidence_ref(event, state=_CLASS_STATE[evidence_class], extra_warnings=warnings),
        "campaign_id": None,
    }


def _ledger_line(event: Event, excluded: Counter[str]) -> dict[str, Any] | None:
    payload = event.payload
    order_currency = _currency(payload.get("currency"))
    if order_currency is None:
        excluded["currency_not_recorded"] += 1
        return None
    evidence_class = payload.get("evidence_class")
    if evidence_class not in LEDGER_EVIDENCE_CLASSES:
        excluded["evidence_class_not_recorded"] += 1
        return None
    if evidence_class == "observed" and any(event.metadata.get(flag) for flag in ("dry_run", "advisory", "non_authoritative", "fixture")):
        excluded["observed_claim_contradicted_by_metadata"] += 1
        return None
    amount = _decimal(payload.get("amount"))
    if amount is None:
        excluded["amount_unavailable"] += 1
        return None
    if amount == 0:
        excluded["zero_amount_not_distinguishable_from_default"] += 1
        return None
    if not _plausible(amount):
        excluded["amount_out_of_range"] += 1
        return None
    occurred = _epoch_date(event.occurred_at)
    if occurred is None:
        excluded["event_date_unavailable"] += 1
        return None
    return {
        "metric": LEDGER_METRIC[event.event_type],
        "evidence_class": evidence_class,
        "occurred_on": occurred.isoformat(),
        "amount": _plain(amount),
        "currency": order_currency,
        "source": event.event_type,
        "provenance": f"canonical_event:{_safe_label(event.source)}",
        "evidence_ref": _evidence_ref(event, state=_CLASS_STATE[evidence_class]),
        "campaign_id": None,
    }


__all__ = [
    "ADAPTER_VERSION",
    "NOT_MAPPED_REASONS",
    "OwnerPerformanceEventAdapterError",
    "PerformanceEventAdaptation",
    "adapt_events_to_performance_report_payload",
]
