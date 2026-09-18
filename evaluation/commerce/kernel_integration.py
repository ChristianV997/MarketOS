"""Commerce integration contracts over the #248 financial-evidence kernel.

This module is the #250-owned adapter surface. It does not implement money
arithmetic. Every calculation calls ``backend.economics.kernel``. Live
orders, payments, ads, and provider calls stay disabled.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from backend.economics.kernel import (
    CurrencyMismatchError,
    EconomicsError,
    EvidenceRef,
    MarketLane,
    Money,
    ServiceEconomics,
    UnitEconomicsAssumptions,
    UnitEconomicsResult,
    calculate_service_economics,
    calculate_unit_economics,
    canonical_json,
)

from evaluation.commerce.business_model_economics import calculate_offer_economics
from evaluation.commerce.canonical import Offer
from evaluation.commerce.dry_run_lifecycle import DryRunLifecycleReport, DryRunScenarioInput, run_dry_run_lifecycle

SCHEMA = "MarketOS.CommerceKernelIntegration.v1"
CANONICAL_KERNEL_MODULE = "backend.economics.kernel"
FORBIDDEN_EXPORT = (
    "prompt",
    "formula",
    "heuristic",
    "source_code",
    "credential",
    "api_key",
    "token",
    "password",
    "payload",
    "trace",
    "internal",
)


class IntegrationError(EconomicsError):
    """Fail-closed adapter error. Does not invent a second money kernel."""


def _require_same_currency(*values: Money | None) -> str:
    currencies = {item.currency for item in values if item is not None}
    if len(currencies) != 1:
        raise CurrencyMismatchError()
    return next(iter(currencies))


def economics_payload(result: UnitEconomicsResult | ServiceEconomics) -> dict[str, Any]:
    """Canonical economics payload: kernel dict plus ownership metadata."""
    body = result.to_dict()
    body["schema"] = SCHEMA
    body["kernel_authority"] = CANONICAL_KERNEL_MODULE
    body["record_kind"] = "planning_record"
    body["live_actions_taken"] = False
    return body


def supplier_offer_to_economics(
    *,
    price: Money,
    product_cost: Money,
    lane: MarketLane,
    assumptions: UnitEconomicsAssumptions | None = None,
    evidence_refs: tuple[EvidenceRef, ...] = (),
) -> UnitEconomicsResult:
    """Map a supplier offer onto the #248 unit-economics kernel."""
    _require_same_currency(price, product_cost)
    if lane.currency != price.currency:
        raise CurrencyMismatchError()
    merged = assumptions or UnitEconomicsAssumptions(evidence_refs=evidence_refs)
    return calculate_unit_economics(price, product_cost, lane=lane, assumptions=merged)


def service_package_to_economics(
    *,
    package_id: str,
    service_fee: Money,
    inputs: Mapping[str, Any],
    evidence_refs: tuple[EvidenceRef, ...] = (),
) -> ServiceEconomics:
    """Map a CompanyOS service package onto kernel service economics."""
    required = ("ad_spend", "contribution_margin", "roas_before", "roas_after", "cac_before", "cac_after", "delivery_hours")
    missing = [name for name in required if inputs.get(name) is None]
    if missing:
        raise IntegrationError(f"missing service evidence: {', '.join(missing)}")
    return calculate_service_economics(
        package_id,
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


def compatibility_unit_economics(
    *,
    selling_price: Any,
    unit_cost: Any,
    currency: str,
    shipping_cost: Any | None = None,
) -> dict[str, Any]:
    """Preserve float-shaped caller signatures while using kernel math."""
    price = Money(str(selling_price), currency, source="compatibility", provenance="compatibility", evidence_state="assumed")
    cost = Money(str(unit_cost), currency, source="compatibility", provenance="compatibility", evidence_state="assumed")
    assumptions = UnitEconomicsAssumptions()
    if shipping_cost is not None:
        assumptions = UnitEconomicsAssumptions(
            supplier_shipping=Money(str(shipping_cost), currency, source="compatibility", provenance="compatibility", evidence_state="assumed")
        )
    result = calculate_unit_economics(price, cost, assumptions=assumptions)
    payload = economics_payload(result)
    payload["compatibility"] = {
        "selling_price": str(price.amount),
        "unit_cost": str(cost.amount),
        "currency": currency,
        "evidence_state": result.evidence_state,
        "missing_inputs": list(result.missing_inputs),
    }
    return payload


def client_safe_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    """TrustOS-shaped client export: drop internal keys and secret-shaped values."""
    blocked = set(FORBIDDEN_EXPORT)

    def _clean(value: Any, key: str | None = None) -> Any:
        if key and any(marker in key.lower() for marker in blocked):
            return None
        if isinstance(value, Mapping):
            out = {}
            for child_key, child in value.items():
                cleaned = _clean(child, str(child_key))
                if cleaned is not None:
                    out[child_key] = cleaned
            return out
        if isinstance(value, (list, tuple)):
            return [_clean(item) for item in value]
        return value

    cleaned = _clean(dict(payload))
    cleaned["schema"] = "MarketOS.ClientCommerceProjection.v1"
    cleaned["record_kind"] = "planning_record"
    cleaned["confidence"] = "planning_only"
    cleaned["live_actions_taken"] = False
    return cleaned


def replay_fingerprint(payload: Mapping[str, Any]) -> str:
    """Deterministic replay identity over a kernel payload."""
    encoded = canonical_json(payload) if hasattr(payload, "keys") else json.dumps(payload, sort_keys=True, default=str)
    if not isinstance(encoded, str):
        encoded = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def integrate_offer(offer: Offer, product_cost: Money | None = None) -> UnitEconomicsResult:
    return calculate_offer_economics(
        offer.business_model,
        price=offer.price,
        product_cost=product_cost,
        lane=offer.lane,
    )


def integrate_dry_run(scenario: DryRunScenarioInput) -> DryRunLifecycleReport:
    report = run_dry_run_lifecycle(scenario)
    if report.live_actions_taken:
        raise IntegrationError("dry-run lifecycle must not take live actions")
    return report


@dataclass(frozen=True)
class AuthorityInventory:
    kernel_module: str = CANONICAL_KERNEL_MODULE
    integration_module: str = "evaluation.commerce.kernel_integration"
    owns_money_arithmetic: str = CANONICAL_KERNEL_MODULE
    owns_commerce_mapping: str = "evaluation.commerce.kernel_integration"

    def to_dict(self) -> dict[str, str]:
        return {
            "kernel_module": self.kernel_module,
            "integration_module": self.integration_module,
            "owns_money_arithmetic": self.owns_money_arithmetic,
            "owns_commerce_mapping": self.owns_commerce_mapping,
        }


__all__ = [
    "SCHEMA",
    "CANONICAL_KERNEL_MODULE",
    "IntegrationError",
    "AuthorityInventory",
    "economics_payload",
    "supplier_offer_to_economics",
    "service_package_to_economics",
    "compatibility_unit_economics",
    "client_safe_projection",
    "replay_fingerprint",
    "integrate_offer",
    "integrate_dry_run",
]
