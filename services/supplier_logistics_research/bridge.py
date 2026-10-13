"""Bridge sanitized supplier evidence into the existing logistics report.

This module is an adapter, not a second supplier scorer.  It consumes the
merged ``SupplierFeasibilityEvidence`` contract produced by the offline
supplier importer and delegates all money arithmetic to the existing
``services.supplier_logistics_research.report`` and canonical economics
kernel.  Missing values stay missing and source provenance is retained.
"""
from __future__ import annotations

import hashlib
from decimal import Decimal, InvalidOperation
from typing import Any

from backend.adapters.research.supplier_feasibility import SupplierFeasibilityEvidence
from backend.economics.kernel import EvidenceRef, MarketLane, Money
from evaluation.commerce.canonical import SupplierOfferIdentity

from . import controls
from .report import build_supplier_logistics_report
from .schemas import (
    CandidateBoundSupplierIdentity,
    CustomsDutyTaxProfile,
    FieldEvidence,
    GoodsLogisticsProfile,
    LeadTimeWindow,
    MoqAvailability,
    ReturnsDefectAssumptions,
    ShippingCostProfile,
    SupplierLogisticsOffer,
    SupplierLogisticsReport,
)

_KNOWN_PROVENANCE = frozenset({"observed", "derived", "assumed", "unavailable", "malformed", "blocked", "manual_import", "fixture", "live_readonly", "stale", "conflicting"})
_QUALITY_BY_PROVENANCE = {
    "observed": "observed",
    "fixture": "fixture",
    "manual_import": "manual",
    "stale": "stale",
    "conflicting": "conflicting",
}
_EVIDENCE_STATE_BY_PROVENANCE = {
    "observed": "observed",
    "derived": "derived",
    "assumed": "assumed",
    "fixture": "fixture",
    "live_readonly": "live_readonly",
    "stale": "stale",
    "conflicting": "unknown",
    "malformed": "rejected",
    "blocked": "rejected",
    "unavailable": "unknown",
    "manual_import": "assumed",
}


def _decimal_value(value: Any, field_name: str) -> Decimal:
    exact = getattr(value, "decimal_amount", None)
    try:
        result = exact if isinstance(exact, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field_name}") from exc
    if not result.is_finite() or result < Decimal("0"):
        raise ValueError(f"invalid {field_name}")
    return result


def _provenance(record: SupplierFeasibilityEvidence, field_name: str, value: Any) -> str:
    mode = str(record.evidence_mode).strip()
    if mode in {"stale", "conflicting"}:
        return mode
    raw = str(record.field_provenance.get(field_name, "")).strip()
    if raw in _KNOWN_PROVENANCE:
        return raw
    if value is None:
        return "unavailable"
    return mode if mode in _KNOWN_PROVENANCE else "unavailable"


def _quality(record: SupplierFeasibilityEvidence, field_name: str, value: Any) -> str:
    if value is None:
        return "missing"
    if "conflicting_supplier_offer" in record.warnings:
        return "conflicting"
    provenance = _provenance(record, field_name, value)
    if provenance in {"stale", "conflicting"}:
        return provenance
    return _QUALITY_BY_PROVENANCE.get(provenance, "manual")


def _state(provenance: str) -> str:
    return _EVIDENCE_STATE_BY_PROVENANCE.get(provenance, "unknown")


def _evidence(record: SupplierFeasibilityEvidence, field_name: str, value: Any) -> FieldEvidence:
    provenance = _provenance(record, field_name, value)
    evidence_id = hashlib.sha256(
        f"{record.candidate_id}|{record.supplier_product_id}|{field_name}".encode("utf-8")
    ).hexdigest()[:20]
    reference = EvidenceRef(
        evidence_id=f"supplier-evidence-{evidence_id}",
        source_type=record.source_type,
        source_url=record.source_url,
        document_ref=record.supplier_product_id,
        origin=record.warehouse_region,
        destination=record.destination_region,
        captured_at=record.observed_at,
        extraction_method="sanitized_supplier_import",
        evidence_state=_state(provenance),
        human_confirmed=False,
        warnings=tuple(record.warnings),
    )
    note = ""
    if provenance in {"derived", "assumed", "unavailable", "malformed", "blocked", "live_readonly"}:
        note = f"source_provenance={provenance}"
    return FieldEvidence(
        quality=_quality(record, field_name, value),
        evidence_ref=reference,
        observed_at=record.observed_at,
        note=note,
        provenance=provenance,
    )


def _money(record: SupplierFeasibilityEvidence, field_name: str, value: Any, currency: str | None) -> Money | None:
    if value is None or currency is None:
        return None
    return Money(
        _decimal_value(value, field_name),
        currency,
        source="supplier_evidence",
        provenance=_provenance(record, field_name, value),
        evidence_state=_state(_provenance(record, field_name, value)),
        evidence_ref=_evidence(record, field_name, value).evidence_ref,
    )


def _fulfillment_mode(value: str) -> str:
    normalized = value.strip().lower()
    if "drop" in normalized:
        return "dropship"
    if "fba" in normalized:
        return "wholesale_fba"
    if "3pl" in normalized:
        return "third_party_3pl"
    if "freight" in normalized:
        return "direct_freight"
    return "unknown"


def build_offer_from_supplier_evidence(
    record: SupplierFeasibilityEvidence,
    *,
    lane: MarketLane | None = None,
) -> SupplierLogisticsOffer:
    """Adapt one sanitized importer record to the canonical report input.

    The adapter never upgrades evidence: even an ``observed`` source record
    receives ``human_confirmed=False`` in its evidence reference.  A caller
    must provide any market-lane assumptions explicitly; no FX or tax/duty
    values are inferred here.
    """
    if not isinstance(record, SupplierFeasibilityEvidence):
        raise TypeError("record must be SupplierFeasibilityEvidence")
    controls.reject_unsafe_input(record.to_dict(), field_name="supplier evidence")
    currency = record.currency.upper() if isinstance(record.currency, str) and record.currency.strip() else None
    quoted_price = _money(record, "unit_cost", record.unit_cost, currency)
    shipping_currency = (
        record.shipping_currency.upper()
        if isinstance(record.shipping_currency, str) and record.shipping_currency.strip()
        else None
    )
    supplier_shipping = _money(record, "shipping_cost", record.shipping_cost, shipping_currency)
    price_evidence = _evidence(record, "unit_cost", record.unit_cost)
    shipping_evidence = _evidence(record, "shipping_cost", record.shipping_cost)
    logistics_value = all(
        value not in (None, "")
        for value in (record.warehouse_region, record.destination_region, record.delivery_min_days, record.delivery_max_days)
    )
    logistics_evidence = _evidence(record, "logistics", True if logistics_value else None)
    goods = GoodsLogisticsProfile(
        moq_availability=MoqAvailability(
            minimum_order_quantity=record.moq,
            available_quantity=record.inventory_quantity,
            availability_status=record.inventory_status or "unknown",
            evidence=_evidence(record, "moq", record.moq if record.moq is not None else record.inventory_quantity),
        ),
        lead_time=LeadTimeWindow(
            minimum_days=record.delivery_min_days,
            maximum_days=record.delivery_max_days,
            evidence=_evidence(record, "delivery_window", record.delivery_min_days if record.delivery_min_days is not None else record.delivery_max_days),
        ),
        fulfillment_mode=_fulfillment_mode(record.fulfillment_method),
        customs=CustomsDutyTaxProfile(evidence=_evidence(record, "customs", None)),
        returns_defects=ReturnsDefectAssumptions(evidence=_evidence(record, "returns", None)),
        shipping=ShippingCostProfile(
            supplier_shipping=supplier_shipping,
            evidence=shipping_evidence,
        ),
        supplier_evidence=_evidence(record, "supplier_product_id", record.supplier_product_id or None),
        logistics_evidence=logistics_evidence,
    )
    identity = CandidateBoundSupplierIdentity(
        candidate_id=record.candidate_id,
        supplier_offer=SupplierOfferIdentity(
            supplier_id=record.supplier,
            offer_id=record.supplier_product_id or record.candidate_id,
            supplier_sku=record.supplier_sku or record.supplier_product_id or record.candidate_id,
        ),
    )
    return SupplierLogisticsOffer(
        identity=identity,
        offering_kind="goods",
        quoted_price=quoted_price,
        price_evidence=price_evidence,
        goods=goods,
        lane=lane,
        captured_at=record.observed_at,
    )


def build_report_from_supplier_evidence(
    record: SupplierFeasibilityEvidence,
    *,
    target_price: Money | None,
    generated_at: str,
    lane: MarketLane | None = None,
) -> SupplierLogisticsReport:
    """Build the existing deterministic report from imported evidence."""
    offer = build_offer_from_supplier_evidence(record, lane=lane)
    return build_supplier_logistics_report(offer, generated_at=generated_at, target_price=target_price)


__all__ = ["build_offer_from_supplier_evidence", "build_report_from_supplier_evidence"]
