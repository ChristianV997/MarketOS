"""Shared fixture-loading helpers for services.supplier_logistics_research
tests. Converts the plain-JSON fixtures under
tests/fixtures/supplier_logistics_research/ into the module's own frozen
dataclasses -- this conversion is test-only and intentionally lives here,
not in the production module, since fixtures are a test concern.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from backend.economics.kernel import EvidenceRef, MarketLane, Money
from evaluation.commerce.canonical import SupplierOfferIdentity
from services.supplier_logistics_research.schemas import (
    CandidateBoundSupplierIdentity,
    CustomsDutyTaxProfile,
    FieldEvidence,
    GoodsLogisticsProfile,
    LeadTimeWindow,
    MoqAvailability,
    ReturnsDefectAssumptions,
    ServiceCapacityProfile,
    ShippingCostProfile,
    SupplierLogisticsOffer,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "supplier_logistics_research"


def load_fixture_json(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text())


def _money(data: dict[str, Any] | None) -> Money | None:
    if data is None:
        return None
    return Money(Decimal(data["amount"]), data["currency"])


def _evidence(data: dict[str, Any] | None) -> FieldEvidence:
    if data is None:
        return FieldEvidence(quality="missing")
    evidence_ref = None
    if data.get("human_confirmed") is not None or data.get("evidence_state") is not None:
        evidence_ref = EvidenceRef(
            evidence_id=data.get("evidence_id", "fixture-evidence"),
            evidence_state=data.get("evidence_state", "unknown"),
            human_confirmed=bool(data.get("human_confirmed", False)),
        )
    return FieldEvidence(
        quality=data["quality"],
        evidence_ref=evidence_ref,
        observed_at=data.get("observed_at", ""),
        note=data.get("note", ""),
    )


def _lane(data: dict[str, Any] | None) -> MarketLane | None:
    if data is None:
        return None
    return MarketLane(
        lane_id=data["lane_id"],
        origin=data["origin"],
        ship_from=data["ship_from"],
        warehouse=data["warehouse"],
        destination_country=data["destination_country"],
        currency=data.get("currency", "MXN"),
        tax_rate=Decimal(data.get("tax_rate", "0")),
        duty_rate=Decimal(data.get("duty_rate", "0")),
    )


def _goods(data: dict[str, Any] | None) -> GoodsLogisticsProfile | None:
    if data is None:
        return None
    moq = data["moq_availability"]
    lead = data["lead_time"]
    customs = data["customs"]
    returns = data["returns_defects"]
    shipping = data["shipping"]
    return GoodsLogisticsProfile(
        moq_availability=MoqAvailability(
            minimum_order_quantity=moq.get("minimum_order_quantity"),
            available_quantity=moq.get("available_quantity"),
            availability_status=moq.get("availability_status", "unknown"),
            evidence=_evidence(moq.get("evidence")),
        ),
        lead_time=LeadTimeWindow(
            minimum_days=lead.get("minimum_days"),
            maximum_days=lead.get("maximum_days"),
            evidence=_evidence(lead.get("evidence")),
        ),
        fulfillment_mode=data.get("fulfillment_mode", "unknown"),
        customs=CustomsDutyTaxProfile(
            duty_rate=None if customs.get("duty_rate") is None else Decimal(customs["duty_rate"]),
            tax_rate=None if customs.get("tax_rate") is None else Decimal(customs["tax_rate"]),
            hs_code=customs.get("hs_code", ""),
            evidence=_evidence(customs.get("evidence")),
        ),
        returns_defects=ReturnsDefectAssumptions(
            return_rate=None if returns.get("return_rate") is None else Decimal(returns["return_rate"]),
            defect_rate=None if returns.get("defect_rate") is None else Decimal(returns["defect_rate"]),
            warranty_rate=None if returns.get("warranty_rate") is None else Decimal(returns["warranty_rate"]),
            evidence=_evidence(returns.get("evidence")),
        ),
        shipping=ShippingCostProfile(
            supplier_shipping=_money(shipping.get("supplier_shipping")),
            domestic_shipping=_money(shipping.get("domestic_shipping")),
            international_shipping=_money(shipping.get("international_shipping")),
            evidence=_evidence(shipping.get("evidence")),
        ),
        supplier_evidence=_evidence(data.get("supplier_evidence")),
        logistics_evidence=_evidence(data.get("logistics_evidence")),
    )


def _service(data: dict[str, Any] | None) -> ServiceCapacityProfile | None:
    if data is None:
        return None
    return ServiceCapacityProfile(
        weekly_capacity_hours=None if data.get("weekly_capacity_hours") is None else Decimal(data["weekly_capacity_hours"]),
        delivery_hours_per_unit=None if data.get("delivery_hours_per_unit") is None else Decimal(data["delivery_hours_per_unit"]),
        business_hours=data.get("business_hours", ""),
        subcontractor_dependency=data.get("subcontractor_dependency"),
        subcontractor_notes=data.get("subcontractor_notes", ""),
        sla_assumption=data.get("sla_assumption", ""),
        geographic_coverage=tuple(data.get("geographic_coverage", ())),
        evidence=_evidence(data.get("evidence")),
    )


def build_offer_from_fixture(data: dict[str, Any]) -> SupplierLogisticsOffer:
    identity = CandidateBoundSupplierIdentity(
        candidate_id=data["candidate_id"],
        supplier_offer=SupplierOfferIdentity(
            supplier_id=data["supplier_id"],
            offer_id=data["offer_id"],
            supplier_sku=data["supplier_sku"],
        ),
    )
    return SupplierLogisticsOffer(
        identity=identity,
        offering_kind=data["offering_kind"],
        quoted_price=_money(data.get("quoted_price")),
        price_evidence=_evidence(data.get("price_evidence")),
        goods=_goods(data.get("goods")),
        service=_service(data.get("service")),
        lane=_lane(data.get("lane")),
        captured_at=data.get("captured_at", ""),
    )


def load_offer_fixture(name: str) -> SupplierLogisticsOffer:
    return build_offer_from_fixture(load_fixture_json(name))


@pytest.fixture
def offer_factory():
    return load_offer_fixture
