"""Portable consulting-service catalog used by CompanyOS planning.

The catalog is intentionally descriptive. It does not create invoices, payment
requests, contracts, or delivery commitments.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    return {package.package_id: package for package in packages}


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
        ))
    return result


__all__ = [
    "ServiceDeliverable", "ServicePriceBand", "ServiceMarginAssumption",
    "ServiceOperationalRequirement", "ServicePackage", "default_service_catalog",
    "catalog_to_dict", "load_service_catalog", "package_map",
]
