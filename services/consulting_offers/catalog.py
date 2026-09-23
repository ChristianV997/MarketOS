"""Offer definitions layered on the existing CompanyOS service catalog.

This module owns client-facing offer composition only. Price bands are derived
from existing ``ServicePackage`` entries; no second price, economics, or
promotion authority is introduced here.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from evaluation.companyos.service_catalog import ServicePackage, package_map
from evaluation.companyos.service_engagement import catalog_with_canonical_services

from .schemas import OfferDefinition, PlanningPriceRange


_OFFER_SPECS: dict[str, dict[str, Any]] = {
    "diagnostic-audit": {
        "name": "Diagnostic Audit",
        "summary": "Bounded review of the client's stated objective, available evidence, and decision blockers.",
        "source_package_ids": ("product-validation-sprint",),
        "component_services": ("product_research", "customer_intelligence"),
        "required_inputs": ("client objective", "candidate or service context", "review scope"),
        "evidence_requirements": ("client context", "source references", "human scope confirmation"),
        "deliverables": ("diagnostic findings summary", "evidence gap register", "prioritized next action"),
        "exclusions": ("no legal opinion", "no supplier approval", "no live provider execution", "no launch authorization"),
        "assumptions": ("Price and turnaround are planning assumptions until scope review.",),
        "human_review_points": ("Confirm objective and scope.", "Review evidence provenance and open gaps."),
        "turnaround_days": 5,
        "upgrade_offer_ids": ("market-research-sprint", "unit-service-economics"),
    },
    "market-research-sprint": {
        "name": "Market-Research Sprint",
        "summary": "Structured market and customer research review for a product, service, or hybrid opportunity.",
        "source_package_ids": ("product-validation-sprint",),
        "component_services": ("product_research", "customer_intelligence"),
        "required_inputs": ("offering context", "target geography", "research questions"),
        "evidence_requirements": ("market observations", "customer evidence", "source freshness and provenance"),
        "deliverables": ("market evidence summary", "customer segment hypotheses", "conflict and freshness register"),
        "exclusions": ("market proxies are not sales proof", "no supplier commitment", "no advertising execution", "no legal clearance"),
        "assumptions": ("Observed, manual, and fixture evidence retain their original ceiling.",),
        "human_review_points": ("Confirm research questions.", "Review conflicting or stale observations."),
        "turnaround_days": 10,
        "upgrade_offer_ids": ("supplier-logistics-feasibility", "unit-service-economics"),
    },
    "unit-service-economics": {
        "name": "Unit and Service Economics",
        "summary": "Evidence-constrained economics review for a commercial product or service offer.",
        "source_package_ids": ("unit-economics-cac-roas-diagnostic",),
        "component_services": ("unit_economics", "profit_stack_advisor"),
        "required_inputs": ("price or fee", "cost evidence", "delivery or capacity assumptions", "currency"),
        "evidence_requirements": ("explicit costs", "currency metadata", "cost provenance", "missing-input status"),
        "deliverables": ("economics input register", "assumption ledger", "canonical-kernel handoff checklist"),
        "exclusions": ("missing costs remain unavailable", "no accounting advice", "no profit guarantee", "no budget or ad spend execution"),
        "assumptions": ("Price ranges are catalog planning bands, not quotes.",),
        "human_review_points": ("Confirm currency and cost basis.", "Review missing or conflicting economics inputs."),
        "turnaround_days": 7,
        "upgrade_offer_ids": ("supplier-logistics-feasibility", "full-commercial-assessment"),
    },
    "supplier-logistics-feasibility": {
        "name": "Supplier and Logistics Feasibility",
        "summary": "Read-only review of supplier and delivery evidence without treating a listing as fulfillment proof.",
        "source_package_ids": ("product-validation-sprint",),
        "component_services": ("supplier_feasibility", "product_research"),
        "required_inputs": ("candidate or service delivery context", "destination geography", "supplier evidence"),
        "evidence_requirements": ("supplier identity evidence", "shipping evidence", "returns and support evidence"),
        "deliverables": ("supplier evidence matrix", "delivery-risk checklist", "next verification request"),
        "exclusions": ("no supplier order", "no inventory reservation", "no shipping guarantee", "no provider call"),
        "assumptions": ("Manual or fixture supplier evidence is not authenticated supplier proof.",),
        "human_review_points": ("Review supplier source and permission status.", "Confirm destination and returns assumptions."),
        "turnaround_days": 8,
        "upgrade_offer_ids": ("unit-service-economics", "full-commercial-assessment"),
        "supported_offering_kinds": ("product", "hybrid", "unknown"),
    },
    "marketing-publicity-strategy": {
        "name": "Marketing and Publicity Strategy",
        "summary": "Evidence-labeled positioning, customer-intelligence, and creative planning for a future human-reviewed test.",
        "source_package_ids": ("managed-acquisition-cro",),
        "component_services": ("customer_intelligence", "creative_growth"),
        "required_inputs": ("audience context", "objective", "claims and evidence constraints"),
        "evidence_requirements": ("customer observations", "message provenance", "claims review"),
        "deliverables": ("positioning hypotheses", "publicity angles", "draft test plan and review checklist"),
        "exclusions": ("no ad spend", "no publishing", "no outbound messaging", "no performance claim"),
        "assumptions": ("Creative and attention signals remain planning evidence only.",),
        "human_review_points": ("Review claims and audience fit.", "Approve any future test scope separately."),
        "turnaround_days": 8,
        "upgrade_offer_ids": ("full-commercial-assessment",),
    },
    "full-commercial-assessment": {
        "name": "Full Commercial Assessment",
        "summary": "Bounded synthesis of research, economics, supplier feasibility, and marketing readiness for human review.",
        "source_package_ids": ("product-validation-sprint", "unit-economics-cac-roas-diagnostic", "managed-acquisition-cro"),
        "component_services": ("product_research", "customer_intelligence", "unit_economics", "supplier_feasibility", "creative_growth", "profit_stack_advisor"),
        "required_inputs": ("offering context", "geography", "evidence register", "cost and currency inputs", "scope approval"),
        "evidence_requirements": ("research provenance", "supplier and logistics evidence", "explicit economics inputs", "claims review"),
        "deliverables": ("cross-component assessment", "evidence ceiling summary", "decision blockers and next-action plan"),
        "exclusions": ("no launch authorization", "no payment or order execution", "no ad or publicity execution", "no legal or accounting opinion"),
        "assumptions": ("The assessment preserves each component's evidence state and does not upgrade weak evidence.",),
        "human_review_points": ("Review all component reports.", "Resolve conflicts and missing inputs.", "Approve any separate follow-on scope."),
        "turnaround_days": 15,
        "upgrade_offer_ids": (),
    },
}


def _package_index() -> dict[str, ServicePackage]:
    return package_map(catalog_with_canonical_services())


def _price_range(package_ids: tuple[str, ...], packages: dict[str, ServicePackage]) -> PlanningPriceRange:
    selected = [packages[package_id] for package_id in package_ids]
    currencies = {package.price_min_money.currency for package in selected}
    if len(currencies) != 1:
        raise ValueError("catalog package currencies do not match")
    currency = next(iter(currencies))
    minimum = sum((package.price_min_money.amount for package in selected), Decimal("0"))
    maximum = sum((package.price_max_money.amount for package in selected), Decimal("0"))
    return PlanningPriceRange(currency, minimum, maximum, package_ids)


def all_offer_definitions() -> tuple[OfferDefinition, ...]:
    packages = _package_index()
    result: list[OfferDefinition] = []
    for offer_id in _OFFER_SPECS:
        spec = _OFFER_SPECS[offer_id]
        package_ids = tuple(spec["source_package_ids"])
        if any(package_id not in packages for package_id in package_ids):
            raise ValueError("catalog package authority unavailable")
        result.append(OfferDefinition(
            offer_id=offer_id,
            name=spec["name"],
            summary=spec["summary"],
            supported_offering_kinds=tuple(spec.get("supported_offering_kinds", ("product", "service", "hybrid", "unknown"))),
            source_package_ids=package_ids,
            component_services=tuple(spec["component_services"]),
            required_inputs=tuple(spec["required_inputs"]),
            evidence_requirements=tuple(spec["evidence_requirements"]),
            deliverables=tuple(spec["deliverables"]),
            exclusions=tuple(spec["exclusions"]),
            assumptions=tuple(spec["assumptions"]),
            human_review_points=tuple(spec["human_review_points"]),
            turnaround_days=spec["turnaround_days"],
            upgrade_offer_ids=tuple(spec["upgrade_offer_ids"]),
            price_range=_price_range(package_ids, packages),
        ))
    return tuple(result)


def get_offer_definition(offer_id: str) -> OfferDefinition:
    for offer in all_offer_definitions():
        if offer.offer_id == offer_id:
            return offer
    raise KeyError("unknown consulting offer")


__all__ = ["all_offer_definitions", "get_offer_definition"]
