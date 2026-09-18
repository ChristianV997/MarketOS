"""Portable consulting-service catalog used by CompanyOS planning.

The catalog is intentionally descriptive. It does not create invoices, payment
requests, contracts, or delivery commitments.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Iterable, Mapping

from backend.economics import CurrencyMismatchError, EvidenceRef, Money, ServiceEconomics, calculate_service_economics


@dataclass(frozen=True)
class ServiceDeliverable:
    deliverable_id: str
    name: str
    description: str
    approval_required: bool = True


@dataclass(frozen=True)
class ServicePriceBand:
    currency: str
    price_min: float
    price_max: float
    assumption_note: str

    @property
    def minimum_money(self) -> Money:
        return Money(Decimal(str(self.price_min)), self.currency, source="service_catalog", provenance="assumed")

    @property
    def maximum_money(self) -> Money:
        return Money(Decimal(str(self.price_max)), self.currency, source="service_catalog", provenance="assumed")


@dataclass(frozen=True)
class ServiceMarginAssumption:
    variable_cost_percent: float
    gross_margin_estimate: float
    cost_basis: str


@dataclass(frozen=True)
class ServiceOperationalRequirement:
    owner_department: str
    required_inputs: tuple[str, ...]
    approval_requirements: tuple[str, ...]
    handoff_department: str


@dataclass(frozen=True)
class ServicePackage:
    package_id: str
    name: str
    department_owner: str
    price_min: float
    price_max: float
    estimated_delivery_hours: float
    estimated_variable_cost_percent: float
    gross_margin_estimate: float
    required_inputs: tuple[str, ...]
    approval_requirements: tuple[str, ...]
    handoff_department: str
    deliverables: tuple[ServiceDeliverable, ...] = ()
    price_band: ServicePriceBand | None = None
    margin_assumption: ServiceMarginAssumption | None = None
    operational_requirement: ServiceOperationalRequirement | None = None
    billing_model: str = "fixed_fee"
    pricing_evidence_state: str = "assumed"
    evidence_refs: tuple[EvidenceRef, ...] = ()
    currency: str = "USD"
    variable_costs: tuple[Money, ...] = ()
    tooling_costs: tuple[Money, ...] = ()
    optional_pass_through_costs: tuple[Money, ...] = ()
    eligibility: tuple[str, ...] = ("required inputs supplied",)
    acceptance_criteria: tuple[str, ...] = ("deliverables reviewed",)
    exclusions: tuple[str, ...] = ("external actions and live provider execution",)
    next_step_relationship: str = "manual scope review"
    minimum_acceptable_value_multiple: float = 1.0

    def __post_init__(self) -> None:
        package_currency = self.price_band.currency if self.price_band else self.currency
        for item in (*self.variable_costs, *self.tooling_costs, *self.optional_pass_through_costs):
            if not isinstance(item, Money):
                raise ValueError("service cost must be money")
            if item.currency != package_currency:
                raise CurrencyMismatchError()
        object.__setattr__(self, "minimum_acceptable_value_multiple", float(self.minimum_acceptable_value_multiple))
        if self.minimum_acceptable_value_multiple < 0:
            raise ValueError("invalid service value multiple")

    @property
    def price_min_money(self) -> Money:
        band = self.price_band or ServicePriceBand(self.currency, self.price_min, self.price_max, "catalog assumption")
        return band.minimum_money

    @property
    def price_max_money(self) -> Money:
        band = self.price_band or ServicePriceBand(self.currency, self.price_min, self.price_max, "catalog assumption")
        return band.maximum_money

    @property
    def canonical_name(self) -> str:
        return {
            "product-opportunity-report": "Product Validation Sprint",
            "finance-planning-dashboard": "Unit Economics + CAC/ROAS Diagnostic",
            "launch-draft-pack": "Launch Draft Pack",
            "managed-marketing-cro": "Managed Acquisition/CRO",
        }.get(self.package_id, self.name)

    @property
    def canonical_package_id(self) -> str:
        return {
            "product-opportunity-report": "product-validation-sprint",
            "finance-planning-dashboard": "unit-economics-cac-roas-diagnostic",
            "launch-draft-pack": "launch-draft-pack",
            "managed-marketing-cro": "managed-acquisition-cro",
        }.get(self.package_id, self.package_id)

    def to_dict(self) -> dict[str, Any]:
        from backend.economics import canonical_json
        import json
        return json.loads(canonical_json(asdict(self)))


def _package(
    package_id: str,
    name: str,
    owner: str,
    price_min: float,
    price_max: float,
    hours: float,
    variable: float,
    inputs: Iterable[str],
    approvals: Iterable[str],
    handoff: str,
    deliverable: str,
) -> ServicePackage:
    margin = round(1.0 - variable, 4)
    deliverables = (ServiceDeliverable(f"{package_id}-deliverable", deliverable, f"Drafted {name} deliverable"),)
    return ServicePackage(
        package_id, name, owner, price_min, price_max, hours, variable, margin,
        tuple(inputs), tuple(approvals), handoff, deliverables,
        ServicePriceBand("USD", price_min, price_max, "Planning band; final price requires client scope review."),
        ServiceMarginAssumption(variable, margin, "Offline planning assumption; not accounting advice."),
        ServiceOperationalRequirement(owner, tuple(inputs), tuple(approvals), handoff),
        billing_model="fixed_fee", pricing_evidence_state="assumed", currency="USD",
        eligibility=tuple(inputs), acceptance_criteria=tuple(approvals), next_step_relationship=handoff,
    )


def default_service_catalog() -> list[ServicePackage]:
    common_approval = ("scope approved", "claims and source evidence reviewed", "delivery owner assigned")
    return [
        _package("product-opportunity-report", "Product Opportunity Report", "intelligence", 500, 1000, 8, .18, ("candidate context", "marketplace evidence"), common_approval, "sales", "client-ready opportunity report"),
        _package("launch-draft-pack", "Launch Draft Pack", "launch", 750, 1500, 14, .22, ("opportunity synthesis", "consumer evidence"), common_approval, "website_store_funnel", "draft offer and creative package"),
        _package("website-store-funnel-blueprint", "Website / Store / Funnel Blueprint", "website_store_funnel", 1000, 2500, 24, .28, ("launch draft pack", "brand context"), common_approval, "operations", "portable site blueprint"),
        _package("validated-store-website-build", "Validated Store / Website Build", "website_store_funnel", 2500, 7500, 60, .42, ("approved blueprint", "platform access after approval"), common_approval + ("publishing approval",), "operations", "implementation-ready build plan"),
        _package("managed-marketing-cro", "Managed Marketing / CRO Retainer", "consumer_attention", 1200, 3500, 24, .35, ("approved creative tests", "measurement plan"), common_approval + ("budget cap approved",), "finance", "managed test review"),
        _package("ai-sales-assistant-setup", "AI Sales Assistant Setup", "sales", 1500, 4000, 32, .32, ("sales process", "approved message drafts"), common_approval + ("consent policy approved",), "operations", "draft assistant configuration"),
        _package("sales-bot-revops-retainer", "Sales Bot / RevOps Retainer", "sales", 2000, 6000, 28, .38, ("approved sales workflow", "handoff policy"), common_approval + ("human escalation approved",), "management", "operating review and pipeline plan"),
        _package("finance-planning-dashboard", "Finance Planning Dashboard", "finance", 900, 2200, 20, .24, ("finance assumptions", "service catalog"), common_approval, "accounting", "forecast and budget model"),
        _package("accounting-automation-setup", "Accounting Automation Setup", "accounting", 1200, 3200, 28, .30, ("ledger seed", "chart of accounts"), common_approval + ("accountant review",), "finance", "ledger-ready accounting package"),
        _package("management-operating-system", "Management Operating System Setup", "management", 1800, 5000, 36, .26, ("department context", "approval policy"), common_approval, "operations", "weekly operating review system"),
        _package("full-revenue-operations-os", "Full Revenue Operations OS", "management", 5000, 15000, 90, .40, ("department context", "sales and finance context"), common_approval + ("phase plan approved",), "management", "cross-department operating blueprint"),
    ]


def catalog_to_dict(packages: Iterable[ServicePackage]) -> list[dict[str, Any]]:
    return [package.to_dict() for package in packages]


def package_map(packages: Iterable[ServicePackage]) -> dict[str, ServicePackage]:
    result = {package.package_id: package for package in packages}
    aliases = {
        "product-validation-sprint": "product-opportunity-report",
        "unit-economics-cac-roas-diagnostic": "finance-planning-dashboard",
        "managed-acquisition-cro": "managed-marketing-cro",
    }
    result.update({alias: result[target] for alias, target in aliases.items() if target in result})
    return result


def service_package_economics(
    package: ServicePackage,
    *,
    price: Money | None = None,
    ad_spend: Money | None = None,
    roas_before: Decimal | int | str | float = Decimal("0"),
    roas_after: Decimal | int | str | float = Decimal("0"),
    cac_before: Money | None = None,
    cac_after: Money | None = None,
    capacity_hours: Decimal | int | str | float | None = None,
) -> ServiceEconomics:
    """Expose typed economics from the existing catalog without a new catalog."""
    if not isinstance(package, ServicePackage):
        raise ValueError("invalid service package")
    fee = price or package.price_min_money
    spend = ad_spend or Money.zero(fee.currency, source="assumed_ad_spend")
    before = cac_before or Money.zero(fee.currency, source="assumed_cac")
    after = cac_after or Money.zero(fee.currency, source="assumed_cac")
    if package.evidence_refs:
        refs = package.evidence_refs
    else:
        refs = (EvidenceRef(f"service:{package.package_id}", source_type="service_catalog", evidence_state=package.pricing_evidence_state),)
    package_currency = package.price_band.currency if package.price_band else package.currency
    if fee.currency != package_currency:
        raise CurrencyMismatchError()
    delivery_cost = sum((item.amount for item in package.variable_costs), Decimal("0"))
    if not package.variable_costs:
        delivery_cost = fee.amount * (Decimal("1") - Decimal(str(package.gross_margin_estimate)))
    tooling_cost = sum((item.amount for item in package.tooling_costs), Decimal("0"))
    pass_through_cost = sum((item.amount for item in package.optional_pass_through_costs), Decimal("0"))
    return calculate_service_economics(
        package.package_id,
        fee,
        ad_spend=spend,
        contribution_margin=Decimal(str(package.gross_margin_estimate)),
        roas_before=roas_before,
        roas_after=roas_after,
        cac_before=before,
        cac_after=after,
        delivery_hours=Decimal(str(package.estimated_delivery_hours)),
        capacity_hours=capacity_hours,
        evidence_refs=refs,
        delivery_cost=Money(delivery_cost, fee.currency, source="service_catalog", provenance="assumed"),
        tooling_cost=Money(tooling_cost, fee.currency, source="service_catalog", provenance="assumed"),
        pass_through_cost=Money(pass_through_cost, fee.currency, source="service_catalog", provenance="assumed"),
        minimum_acceptable_value_multiple=package.minimum_acceptable_value_multiple,
    )


def load_service_catalog(seed: Mapping[str, Any] | None = None) -> list[ServicePackage]:
    """Use a safe seed only for price/name overrides; unknown fields are ignored."""
    packages = default_service_catalog()
    overrides = {str(item.get("package_id")): item for item in (seed or {}).get("packages", []) if isinstance(item, Mapping)}
    result: list[ServicePackage] = []
    for package in packages:
        override = overrides.get(package.package_id, {})
        if not isinstance(override, Mapping):
            result.append(package)
            continue
        try:
            low = max(0.0, float(override.get("price_min", package.price_min)))
            high = max(low, float(override.get("price_max", package.price_max)))
        except (TypeError, ValueError):
            low, high = package.price_min, package.price_max
        result.append(ServicePackage(
            package.package_id, package.name, package.department_owner, low, high,
            package.estimated_delivery_hours, package.estimated_variable_cost_percent,
            package.gross_margin_estimate, package.required_inputs, package.approval_requirements,
            package.handoff_department, package.deliverables,
            ServicePriceBand("USD", low, high, "Seed override; final price requires client scope review."),
            package.margin_assumption, package.operational_requirement,
            billing_model=package.billing_model, pricing_evidence_state=package.pricing_evidence_state,
            evidence_refs=package.evidence_refs, currency=package.currency,
            variable_costs=package.variable_costs, tooling_costs=package.tooling_costs,
            optional_pass_through_costs=package.optional_pass_through_costs,
            eligibility=package.eligibility, acceptance_criteria=package.acceptance_criteria,
            exclusions=package.exclusions, next_step_relationship=package.next_step_relationship,
            minimum_acceptable_value_multiple=package.minimum_acceptable_value_multiple,
        ))
    return result


__all__ = [
    "ServiceDeliverable", "ServicePriceBand", "ServiceMarginAssumption",
    "ServiceOperationalRequirement", "ServicePackage", "default_service_catalog",
    "catalog_to_dict", "load_service_catalog", "package_map", "service_package_economics",
]
