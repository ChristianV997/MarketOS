"""services.geographic_opportunity.serialization -- deterministic,
offline JSON-dict loaders for this service's own dataclasses.

Every ``Money``/``EvidenceRef`` value is loaded via
``backend.economics.kernel.Money.from_dict`` /
``backend.economics.kernel.EvidenceRef.from_dict`` -- the kernel already
owns money and evidence-reference serialization, so this module never
re-derives that logic. It only maps a plain, JSON-shaped dict onto this
service's own ``TradeOpportunityOffer`` and its component dataclasses;
every validation (missing-vs-explicit-zero, currency checks, vocabulary
membership, offering/geography-kind gating, ...) still happens inside
each dataclass's own ``__post_init__`` -- this module performs none of
its own.

``lane_from_dict`` is deliberately a bounded, practical subset of
``backend.economics.kernel.MarketLane``'s full ~19-field shape
(``lane_id``, ``origin``, ``ship_from``, ``warehouse``,
``destination_country``, ``destination_region``, ``currency``,
``tax_rate``, ``duty_rate``) -- the fields this domain's own fixtures
actually vary -- not a full ``MarketLane`` round-trip serializer. A
caller needing the remaining ``MarketLane`` fields (``brokerage_fee``,
payment fees, ``marketplace_permissions``, ...) must construct a
``MarketLane`` directly and pass it to ``TradeOpportunityOffer`` without
going through this loader.

This module performs no I/O of its own: it accepts an already-loaded
dict (typically read from a local JSON file by ``cli.py``) and returns
dataclass instances. It never contacts a live provider.
"""
from __future__ import annotations

from typing import Any, Mapping

from backend.economics.kernel import EconomicsError, EvidenceRef, MarketLane, Money

from .schemas import (
    BilateralTradeFlowObservation,
    CandidateBoundTradeIdentity,
    DestinationPriceObservation,
    FieldEvidence,
    FreightDutyAssumptions,
    RegulatoryComplianceObservation,
    ReturnsLeadTimeAssumptions,
    ServiceCapacityByGeography,
    TradeOpportunityOffer,
)

_MISSING_EVIDENCE = FieldEvidence(quality="missing")


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EconomicsError(f"invalid {field_name}: expected a JSON object")
    return value


def money_from_dict(data: Mapping[str, Any] | None, *, field_name: str = "money") -> Money | None:
    """``None``-tolerant pass-through to
    ``backend.economics.kernel.Money.from_dict`` -- the kernel already
    owns money serialization (including the ``"unknown"``-sentinel
    round-trip ``Money.to_dict`` itself produces); this exists only to
    give callers an entry point consistent with this module's other
    ``*_from_dict`` functions, never to re-derive kernel logic."""
    if data is None:
        return None
    return Money.from_dict(_require_mapping(data, field_name))


def evidence_ref_from_dict(data: Mapping[str, Any] | None) -> EvidenceRef | None:
    """``None``-tolerant pass-through to
    ``backend.economics.kernel.EvidenceRef.from_dict``."""
    if data is None:
        return None
    return EvidenceRef.from_dict(_require_mapping(data, "evidence_ref"))


def field_evidence_from_dict(data: Mapping[str, Any] | None) -> FieldEvidence:
    """Missing input maps to ``quality="missing"`` -- consistent with
    every dataclass in ``schemas.py`` defaulting its own ``evidence``
    field to the module-level missing sentinel, never to a fabricated
    ``"observed"``."""
    if data is None:
        return _MISSING_EVIDENCE
    mapping = _require_mapping(data, "evidence")
    return FieldEvidence(
        quality=mapping.get("quality", "missing"),
        evidence_ref=evidence_ref_from_dict(mapping.get("evidence_ref")),
        observed_at=mapping.get("observed_at", ""),
        note=mapping.get("note", ""),
    )


def lane_from_dict(data: Mapping[str, Any] | None) -> MarketLane | None:
    """Builds a ``MarketLane`` from the bounded, practical field subset
    documented in this module's own docstring. ``ship_from``/``warehouse``
    default to ``origin``/``destination_country`` respectively when
    omitted, matching this service's own test-fixture convention
    (``tests/services/test_geographic_opportunity/conftest.py::build_lane``).
    Every other ``MarketLane`` field keeps the kernel's own default."""
    if data is None:
        return None
    mapping = _require_mapping(data, "lane")
    origin = mapping.get("origin", "")
    destination_country = mapping.get("destination_country", "")
    kwargs: dict[str, Any] = {
        "lane_id": mapping.get("lane_id", ""),
        "origin": origin,
        "ship_from": mapping.get("ship_from", origin),
        "warehouse": mapping.get("warehouse", destination_country),
        "destination_country": destination_country,
        "destination_region": mapping.get("destination_region", ""),
    }
    for optional_field in ("currency", "tax_rate", "duty_rate"):
        if optional_field in mapping:
            kwargs[optional_field] = mapping[optional_field]
    return MarketLane(**kwargs)


def identity_from_dict(data: Mapping[str, Any] | None) -> CandidateBoundTradeIdentity:
    mapping = _require_mapping(data, "identity")
    return CandidateBoundTradeIdentity(
        candidate_id=mapping.get("candidate_id", ""),
        origin_country=mapping.get("origin_country", ""),
        destination_country=mapping.get("destination_country", ""),
        hs_code=mapping.get("hs_code", ""),
    )


def trade_flow_from_dict(data: Mapping[str, Any] | None) -> BilateralTradeFlowObservation | None:
    if data is None:
        return None
    mapping = _require_mapping(data, "trade_flow")
    return BilateralTradeFlowObservation(
        period=mapping.get("period", ""),
        trade_value=money_from_dict(mapping.get("trade_value"), field_name="trade_flow.trade_value"),
        trade_quantity=mapping.get("trade_quantity"),
        quantity_unit=mapping.get("quantity_unit", ""),
        unit_value=money_from_dict(mapping.get("unit_value"), field_name="trade_flow.unit_value"),
        evidence=field_evidence_from_dict(mapping.get("evidence")),
    )


def destination_price_from_dict(data: Mapping[str, Any] | None) -> DestinationPriceObservation | None:
    if data is None:
        return None
    mapping = _require_mapping(data, "destination_price")
    return DestinationPriceObservation(
        observed_price=money_from_dict(mapping.get("observed_price"), field_name="destination_price.observed_price"),
        price_type=mapping.get("price_type", "unknown"),
        sample_size=mapping.get("sample_size"),
        is_realized_sale=mapping.get("is_realized_sale", False),
        evidence=field_evidence_from_dict(mapping.get("evidence")),
    )


def freight_duty_from_dict(data: Mapping[str, Any] | None) -> FreightDutyAssumptions | None:
    if data is None:
        return None
    mapping = _require_mapping(data, "freight_duty")
    return FreightDutyAssumptions(
        supplier_shipping=money_from_dict(mapping.get("supplier_shipping"), field_name="freight_duty.supplier_shipping"),
        international_shipping=money_from_dict(mapping.get("international_shipping"), field_name="freight_duty.international_shipping"),
        domestic_shipping=money_from_dict(mapping.get("domestic_shipping"), field_name="freight_duty.domestic_shipping"),
        duty_rate=mapping.get("duty_rate"),
        tax_rate=mapping.get("tax_rate"),
        evidence=field_evidence_from_dict(mapping.get("evidence")),
    )


def returns_lead_time_from_dict(data: Mapping[str, Any] | None) -> ReturnsLeadTimeAssumptions | None:
    if data is None:
        return None
    mapping = _require_mapping(data, "returns_lead_time")
    return ReturnsLeadTimeAssumptions(
        return_rate=mapping.get("return_rate"),
        lead_time_minimum_days=mapping.get("lead_time_minimum_days"),
        lead_time_maximum_days=mapping.get("lead_time_maximum_days"),
        evidence=field_evidence_from_dict(mapping.get("evidence")),
    )


def service_capacity_from_dict(data: Mapping[str, Any] | None) -> ServiceCapacityByGeography | None:
    if data is None:
        return None
    mapping = _require_mapping(data, "service_capacity")
    return ServiceCapacityByGeography(
        geographic_coverage=tuple(mapping.get("geographic_coverage", ())),
        weekly_capacity_hours=mapping.get("weekly_capacity_hours"),
        capacity_available=mapping.get("capacity_available"),
        subcontractor_dependency=mapping.get("subcontractor_dependency"),
        sla_assumption=mapping.get("sla_assumption", ""),
        evidence=field_evidence_from_dict(mapping.get("evidence")),
    )


def regulatory_from_dict(data: Mapping[str, Any] | None) -> RegulatoryComplianceObservation | None:
    if data is None:
        return None
    mapping = _require_mapping(data, "regulatory")
    return RegulatoryComplianceObservation(
        status=mapping.get("status", "unassessed"),
        requirement_note=mapping.get("requirement_note", ""),
        evidence=field_evidence_from_dict(mapping.get("evidence")),
    )


def offer_from_dict(data: Mapping[str, Any]) -> TradeOpportunityOffer:
    """Builds one ``TradeOpportunityOffer`` from a plain JSON-shaped
    dict -- the sole entry point ``cli.py`` uses to load an
    operator-supplied offer file (or a fixture, in tests). Every
    validation (currency matching, offering/geography-kind gating,
    missing-vs-explicit-zero, regulatory-status vocabulary, ...) happens
    inside ``TradeOpportunityOffer.__post_init__`` and its component
    dataclasses -- this function performs no independent validation and
    reads no file itself."""
    mapping = _require_mapping(data, "offer")
    return TradeOpportunityOffer(
        identity=identity_from_dict(mapping.get("identity")),
        offering_kind=mapping.get("offering_kind", "unknown"),
        geography_kind=mapping.get("geography_kind", "unknown"),
        lane=lane_from_dict(mapping.get("lane")),
        trade_flow=trade_flow_from_dict(mapping.get("trade_flow")),
        destination_price=destination_price_from_dict(mapping.get("destination_price")),
        source_price=destination_price_from_dict(mapping.get("source_price")),
        origin_supplier_cost=money_from_dict(mapping.get("origin_supplier_cost"), field_name="origin_supplier_cost"),
        origin_supplier_cost_evidence=field_evidence_from_dict(mapping.get("origin_supplier_cost_evidence")),
        freight_duty=freight_duty_from_dict(mapping.get("freight_duty")),
        marketplace_fee_rate=mapping.get("marketplace_fee_rate"),
        marketplace_fee_evidence=field_evidence_from_dict(mapping.get("marketplace_fee_evidence")),
        returns_lead_time=returns_lead_time_from_dict(mapping.get("returns_lead_time")),
        service_capacity=service_capacity_from_dict(mapping.get("service_capacity")),
        regulatory=regulatory_from_dict(mapping.get("regulatory")),
        captured_at=mapping.get("captured_at", ""),
    )
