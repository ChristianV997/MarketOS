"""The four externally-sold CompanyOS service packages, canonically named.

This module does not edit ``evaluation.companyos.service_catalog`` — the
descriptive CompanyOS pricing catalog is under active parallel extension by
the financial-evidence-kernel lane (PR #248 adds its own
``billing_model``/``evidence_refs``/``service_package_economics`` fields to
that same file). Rather than collide with that in-flight, unmerged edit,
this module is a thin, additive layer on top of the catalog as it exists on
``main`` today: it aliases three of the four named services onto existing
``ServicePackage`` entries, defines the one package the catalog is missing
(Unit Economics + CAC/ROAS Diagnostic), and adds the client-facing fields
the integration spec requires (eligibility, acceptance criteria, scope
exclusions, data-quality requirements, next-step relationship, price state)
without changing ``ServicePackage`` itself.

Service *economics* (gross revenue, labor/tooling/contractor cost, reserve,
contribution profit/margin/per-hour, capacity, client-value-created, fee
recovery, minimum acceptable value, and the
``incremental_contribution``/``orders_required_to_recover_fee`` formulas)
are the canonical financial kernel's ``ServiceEconomics`` /
``calculate_service_economics`` — reused here, never re-derived.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from backend.economics.kernel import EvidenceRef, Money, calculate_service_economics

from evaluation.commerce.canonical import ServiceEngagement, WorkspaceReplayContext

from .service_catalog import (
    ServiceDeliverable,
    ServiceMarginAssumption,
    ServiceOperationalRequirement,
    ServicePackage,
    ServicePriceBand,
    default_service_catalog,
    package_map,
)

PRICE_STATES = frozenset({"planning_assumption", "validated"})

# Inputs calculate_service_economics needs to produce a trustworthy result;
# anything missing here means "we don't have enough client data", not "assume
# zero" — see build_service_engagement's data_inadequate handling.
REQUIRED_SERVICE_ECONOMICS_INPUTS: tuple[str, ...] = (
    "ad_spend", "contribution_margin", "roas_before", "roas_after",
    "cac_before", "cac_after", "delivery_hours",
)


def _unit_economics_diagnostic_package() -> ServicePackage:
    """The one client-facing package missing from the CompanyOS catalog.

    Scoped consistently with ``docs/SERVICE_MODULES.md``'s
    ``services.unit_economics`` module (3,000-25,000 MXN street pricing);
    priced here in USD to match every other entry in
    ``default_service_catalog()``.
    """
    deliverable = ServiceDeliverable(
        "unit-economics-cac-roas-diagnostic-deliverable",
        "Unit Economics + CAC/ROAS Diagnostic Report",
        "Margin, break-even CAC, and required-ROAS diagnostic derived from the canonical economics kernel.",
    )
    common_approval = ("scope approved", "claims and source evidence reviewed", "delivery owner assigned")
    return ServicePackage(
        package_id="unit-economics-cac-roas-diagnostic",
        name="Unit Economics + CAC/ROAS Diagnostic",
        department_owner="intelligence",
        price_min=150.0,
        price_max=1250.0,
        estimated_delivery_hours=6.0,
        estimated_variable_cost_percent=0.15,
        gross_margin_estimate=0.85,
        required_inputs=("supplier_cost", "retail_price", "shipping_cost", "monthly_ad_spend_or_cac"),
        approval_requirements=common_approval,
        handoff_department="launch",
        deliverables=(deliverable,),
        price_band=ServicePriceBand("USD", 150.0, 1250.0, "Planning band; final price requires client scope review."),
        margin_assumption=ServiceMarginAssumption(0.15, 0.85, "Offline planning assumption; not accounting advice."),
        operational_requirement=ServiceOperationalRequirement(
            "intelligence",
            ("supplier_cost", "retail_price", "shipping_cost", "monthly_ad_spend_or_cac"),
            common_approval,
            "launch",
        ),
    )


def catalog_with_canonical_services() -> list[ServicePackage]:
    """The existing CompanyOS catalog plus the one package it is missing."""
    return [*default_service_catalog(), _unit_economics_diagnostic_package()]


@dataclass(frozen=True)
class ClientServiceDefinition:
    """The client-facing contract for one of the four initial services.

    Wraps an existing (or newly-added) ``ServicePackage`` rather than
    redefining its price/hours/deliverables; adds only the fields the
    integration spec requires that ``ServicePackage`` does not carry.
    """

    canonical_name: str
    package: ServicePackage
    eligibility: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    scope_exclusions: tuple[str, ...]
    data_quality_requirements: tuple[str, ...]
    next_step_relationship: str
    price_state: str = "planning_assumption"

    def __post_init__(self) -> None:
        if self.price_state not in PRICE_STATES:
            raise ValueError(f"unknown price state: {self.price_state}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_name": self.canonical_name,
            "package": self.package.to_dict(),
            "eligibility": list(self.eligibility),
            "acceptance_criteria": list(self.acceptance_criteria),
            "scope_exclusions": list(self.scope_exclusions),
            "data_quality_requirements": list(self.data_quality_requirements),
            "next_step_relationship": self.next_step_relationship,
            "price_state": self.price_state,
        }


def canonical_client_services(packages: Mapping[str, ServicePackage] | None = None) -> tuple[ClientServiceDefinition, ...]:
    """The four initial client services, aliased onto CompanyOS packages."""
    lookup = packages if packages is not None else package_map(catalog_with_canonical_services())
    common_launch_exclusions = ("no publishing", "no ad spend", "no order placement")
    return (
        ClientServiceDefinition(
            "Product Validation Sprint",
            lookup["product-opportunity-report"],
            eligibility=("candidate has at least one supplier or marketplace evidence source",),
            acceptance_criteria=("client-ready opportunity report delivered", "evidence provenance disclosed"),
            scope_exclusions=("no supplier ordering", "no ad spend", "no publishing"),
            data_quality_requirements=("candidate_context", "marketplace_evidence"),
            next_step_relationship="unit-economics-cac-roas-diagnostic",
        ),
        ClientServiceDefinition(
            "Unit Economics + CAC/ROAS Diagnostic",
            lookup["unit-economics-cac-roas-diagnostic"],
            eligibility=("supplier_cost and retail_price are known",),
            acceptance_criteria=("break-even CAC and required ROAS reported", "margin verdict reported"),
            scope_exclusions=("no live ad spend", "no supplier negotiation"),
            data_quality_requirements=("supplier_cost", "retail_price", "shipping_cost"),
            next_step_relationship="launch-draft-pack",
        ),
        ClientServiceDefinition(
            "Launch Draft Pack",
            lookup["launch-draft-pack"],
            eligibility=("opportunity synthesis or unit economics diagnostic completed",),
            acceptance_criteria=("draft offer and creative package delivered", "Shopify/Medusa payloads remain status=draft"),
            scope_exclusions=common_launch_exclusions,
            data_quality_requirements=("opportunity synthesis", "consumer evidence"),
            next_step_relationship="managed-marketing-cro",
        ),
        ClientServiceDefinition(
            "Managed Acquisition and CRO",
            lookup["managed-marketing-cro"],
            eligibility=("launch draft approved", "budget cap approved", "measurement plan in place"),
            acceptance_criteria=(
                "managed test review delivered",
                "incremental_contribution and orders_required_to_recover_fee reported",
            ),
            scope_exclusions=("no autonomous spend changes without approval", "no platform publishing outside approved channels"),
            data_quality_requirements=("approved creative tests", "measurement plan", "roas_before", "roas_after", "cac_before", "cac_after"),
            next_step_relationship="none_terminal_retainer",
        ),
    )


def build_service_engagement(
    engagement_id: str,
    canonical_name: str,
    client_name: str,
    *,
    service_fee: Money,
    inputs: Mapping[str, Any],
    evidence_refs: tuple[EvidenceRef, ...] = (),
    context: WorkspaceReplayContext | None = None,
) -> ServiceEngagement:
    """Build a ``ServiceEngagement``, refusing to guess when client data is thin.

    Insufficient client data (any of ``REQUIRED_SERVICE_ECONOMICS_INPUTS``
    missing) produces ``data_adequate=False`` — surfaced as
    ``status="data_inadequate"`` by ``ServiceEngagement.to_dict`` — rather
    than an optimistic recommendation computed from placeholder numbers.
    """
    definitions = {item.canonical_name: item for item in canonical_client_services()}
    if canonical_name not in definitions:
        raise ValueError(f"unknown canonical service: {canonical_name}")
    package = definitions[canonical_name].package
    context = context or WorkspaceReplayContext()

    missing = tuple(f"missing_{name}" for name in REQUIRED_SERVICE_ECONOMICS_INPUTS if inputs.get(name) is None)
    if missing:
        return ServiceEngagement(
            engagement_id=engagement_id,
            package_id=package.package_id,
            client_name=client_name,
            stage="proposed",
            economics=None,
            evidence_refs=evidence_refs,
            context=context,
            data_adequate=False,
            reasons=missing,
        )

    economics = calculate_service_economics(
        package.package_id,
        service_fee,
        ad_spend=inputs["ad_spend"],
        contribution_margin=inputs["contribution_margin"],
        roas_before=inputs["roas_before"],
        roas_after=inputs["roas_after"],
        cac_before=inputs["cac_before"],
        cac_after=inputs["cac_after"],
        delivery_hours=inputs["delivery_hours"],
        capacity_hours=inputs.get("capacity_hours"),
        evidence_refs=evidence_refs,
        delivery_cost=inputs.get("labor_cost"),
        tooling_cost=inputs.get("tooling_cost"),
        pass_through_cost=inputs.get("contractor_cost"),
        refund_revision_reserve=inputs.get("reserve"),
        target_monthly_contribution=inputs.get("target_monthly_contribution"),
        client_value_created=inputs.get("client_value_created"),
        minimum_acceptable_value_multiple=inputs.get("minimum_acceptable_value_multiple", 1),
    )
    return ServiceEngagement(
        engagement_id=engagement_id,
        package_id=package.package_id,
        client_name=client_name,
        stage="scoped",
        economics=economics,
        evidence_refs=evidence_refs,
        context=context,
        data_adequate=True,
    )


__all__ = [
    "PRICE_STATES",
    "REQUIRED_SERVICE_ECONOMICS_INPUTS",
    "ClientServiceDefinition",
    "catalog_with_canonical_services",
    "canonical_client_services",
    "build_service_engagement",
]
