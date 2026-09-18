"""Client-service delivery plane.

Consumes the CompanyOS service catalog, finance planner, and TrustOS export
boundary. Does not create a second catalog, money kernel, Governor, Approval
Ledger, CRM, or payment processor. All money values are planning assumptions
unless the caller labels them otherwise. Currencies are never converted.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from typing import Any, Mapping

from evaluation.companyos.finance import ClientProjectMargin, build_finance_plan
from evaluation.companyos.service_catalog import ServicePackage, default_service_catalog, package_map

SCHEMA = "MarketOS.ServiceDelivery.v1"
SUPPORTED_CURRENCIES = frozenset({"USD", "MXN", "CAD"})
LIFECYCLE = (
    "draft",
    "intake_requested",
    "intake_received",
    "data_quality_assessed",
    "evidence_collection",
    "analysis_in_progress",
    "internal_review",
    "client_review",
    "delivered",
    "revision_requested",
    "accepted",
    "renewal_or_upsell",
    "blocked",
    "rejected",
    "cancelled",
    "data_inadequate",
)
QUALITY_STATES = frozenset(
    {"adequate", "partial", "stale", "conflicting", "insufficient", "blocked", "unavailable"}
)
PRICE_EVIDENCE = frozenset({"planning_assumption", "validated_price"})
QUALITY_REQUIRED = (
    "orders",
    "revenue",
    "cac",
    "contribution_margin",
    "period_start",
    "period_end",
    "channel",
    "returns_refunds",
    "ad_spend",
    "offer_id",
)
SECRET_SHAPED = re.compile(
    r"(?is)(ghp_[A-Za-z0-9_]{20,}|sk-(?:live|test)?-?[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|bearer [A-Za-z0-9._-]{10,})"
)
FORBIDDEN_KEY = re.compile(
    r"(?i)(prompt|formula|heuristic|source_code|credential|api[_-]?key|token|password|payload|trace|internal|filepath|file_path)"
)
PRIORITY_ALIASES = {
    "product-validation-sprint": "product-opportunity-report",
    "unit-economics-diagnostic": "finance-planning-dashboard",
    "launch-draft-pack": "launch-draft-pack",
    "managed-acquisition-cro": "managed-marketing-cro",
}
PRIORITY_LABELS = {
    "product-validation-sprint": "Product Validation Sprint",
    "unit-economics-diagnostic": "Unit Economics + CAC/ROAS Diagnostic",
    "launch-draft-pack": "Launch Draft Pack",
    "managed-acquisition-cro": "Managed Acquisition and CRO",
}
PLANNING_OVERLAY = {
    "product-validation-sprint": {
        "billing_model": "fixed_scope",
        "labor_cost": "180",
        "tooling_cost": "40",
        "contractor_cost": "0",
        "refund_revision_reserve": "50",
        "pass_through_usage_cost": "0",
        "eligibility": ("candidate context", "marketplace evidence"),
        "expected_outcome": "Go/no-go product validation record",
        "exclusions": ("live supplier outreach", "ad spend", "store publishing"),
        "next_step": "launch-draft-pack",
    },
    "unit-economics-diagnostic": {
        "billing_model": "fixed_scope",
        "labor_cost": "220",
        "tooling_cost": "25",
        "contractor_cost": "0",
        "refund_revision_reserve": "60",
        "pass_through_usage_cost": "0",
        "eligibility": ("fee", "CAC or ROAS pair", "single currency"),
        "expected_outcome": "Planning diagnostic of contribution and fee recovery",
        "exclusions": ("FX conversion", "live ad accounts", "invoices"),
        "next_step": "managed-acquisition-cro",
    },
    "launch-draft-pack": {
        "billing_model": "fixed_scope",
        "labor_cost": "260",
        "tooling_cost": "35",
        "contractor_cost": "80",
        "refund_revision_reserve": "75",
        "pass_through_usage_cost": "0",
        "eligibility": ("opportunity synthesis", "consumer evidence"),
        "expected_outcome": "Draft offer and creative package at status=draft",
        "exclusions": ("publishing", "domain purchase", "ad launch"),
        "next_step": "managed-acquisition-cro",
    },
    "managed-acquisition-cro": {
        "billing_model": "retainer",
        "labor_cost": "420",
        "tooling_cost": "90",
        "contractor_cost": "120",
        "refund_revision_reserve": "110",
        "pass_through_usage_cost": "0",
        "eligibility": ("approved creative tests", "measurement plan"),
        "expected_outcome": "Managed test review planning record",
        "exclusions": ("autonomous spend", "customer messaging"),
        "next_step": "renewal_or_upsell",
    },
}
ALLOWED_TRANSITIONS = {
    "draft": {"intake_requested", "cancelled", "rejected", "blocked"},
    "intake_requested": {"intake_received", "cancelled", "blocked"},
    "intake_received": {"data_quality_assessed", "data_inadequate", "cancelled"},
    "data_quality_assessed": {"evidence_collection", "data_inadequate", "blocked"},
    "evidence_collection": {"analysis_in_progress", "data_inadequate", "blocked"},
    "analysis_in_progress": {"internal_review", "blocked"},
    "internal_review": {"client_review", "blocked"},
    "client_review": {"delivered", "revision_requested", "rejected"},
    "delivered": {"revision_requested", "accepted"},
    "revision_requested": {"analysis_in_progress", "internal_review", "cancelled"},
    "accepted": {"renewal_or_upsell"},
    "renewal_or_upsell": {"intake_requested"},
    "blocked": {"draft", "cancelled"},
    "rejected": set(),
    "cancelled": set(),
    "data_inadequate": {"intake_requested", "cancelled"},
}


class ServiceDeliveryError(ValueError):
    """Fail-closed delivery-plane validation error."""


def _dec(value: Any, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ServiceDeliveryError(f"invalid {field}")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ServiceDeliveryError(f"invalid {field}") from exc
    if not result.is_finite():
        raise ServiceDeliveryError(f"invalid {field}")
    return result


def _money(value: Any, field: str) -> Decimal:
    result = _dec(value, field)
    if result < 0:
        raise ServiceDeliveryError(f"{field} must be >= 0")
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ServiceDeliveryError(f"invalid {field}")
    text = " ".join(value.split())
    if SECRET_SHAPED.search(text):
        raise ServiceDeliveryError(f"{field} contains secret-shaped text")
    return text


def _currency(value: Any) -> str:
    currency = _text(value, "currency").upper()
    if currency not in SUPPORTED_CURRENCIES:
        raise ServiceDeliveryError(f"unsupported currency: {currency}")
    return currency


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def list_priority_packages(catalog: Mapping[str, ServicePackage] | None = None) -> list[dict[str, Any]]:
    return [resolve_priority_package(alias, catalog) for alias in PRIORITY_ALIASES]


def resolve_priority_package(alias: str, catalog: Mapping[str, ServicePackage] | None = None) -> dict[str, Any]:
    key = _text(alias, "package").replace("_", "-").lower()
    if key not in PRIORITY_ALIASES:
        raise ServiceDeliveryError(f"unsupported priority package: {alias}")
    packages = catalog or package_map(default_service_catalog())
    catalog_id = PRIORITY_ALIASES[key]
    package = packages.get(catalog_id)
    if package is None:
        raise ServiceDeliveryError(f"catalog package missing: {catalog_id}")
    overlay = PLANNING_OVERLAY[key]
    currency = package.price_band.currency if package.price_band else "USD"
    if currency not in SUPPORTED_CURRENCIES:
        raise ServiceDeliveryError("catalog currency unsupported")
    return {
        "schema": SCHEMA,
        "package_id": key,
        "catalog_package_id": catalog_id,
        "name": PRIORITY_LABELS[key],
        "description": f"Planning view over catalog package {catalog_id}",
        "currency": currency,
        "price_min": str(Decimal(str(package.price_min)).quantize(Decimal("0.01"))),
        "price_max": str(Decimal(str(package.price_max)).quantize(Decimal("0.01"))),
        "billing_model": overlay["billing_model"],
        "estimated_hours": str(package.estimated_delivery_hours),
        "labor_cost": overlay["labor_cost"],
        "tooling_cost": overlay["tooling_cost"],
        "contractor_cost": overlay["contractor_cost"],
        "refund_revision_reserve": overlay["refund_revision_reserve"],
        "pass_through_usage_cost": overlay["pass_through_usage_cost"],
        "required_inputs": list(package.required_inputs),
        "eligibility": list(overlay["eligibility"]),
        "deliverables": [item.name for item in package.deliverables],
        "acceptance_criteria": list(package.approval_requirements),
        "expected_outcome": overlay["expected_outcome"],
        "exclusions": list(overlay["exclusions"]),
        "next_step_relationship": overlay["next_step"],
        "price_evidence_state": "planning_assumption",
        "price_state": "planning_assumption_versus_validated_price",
    }


def assess_data_quality(intake: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(intake)
    if "returns_refunds" not in normalized and ("returns" in normalized or "refunds" in normalized):
        normalized["returns_refunds"] = normalized.get("returns", normalized.get("refunds"))
    missing = [field for field in QUALITY_REQUIRED if normalized.get(field) in (None, "", [])]
    stale = bool(normalized.get("stale"))
    conflicting = bool(normalized.get("conflicting"))
    currency = str(normalized.get("currency") or "")
    if currency and currency.upper() not in SUPPORTED_CURRENCIES:
        return {"state": "blocked", "missing": missing, "reason": "unsupported_currency"}
    if normalized.get("unavailable"):
        return {"state": "unavailable", "missing": missing, "reason": "source_unavailable"}
    if conflicting:
        return {"state": "conflicting", "missing": missing, "reason": "conflicting_metrics"}
    if stale:
        return {"state": "stale", "missing": missing, "reason": "period_stale"}
    if len(missing) >= 5:
        return {"state": "insufficient", "missing": missing, "reason": "too_few_metrics"}
    if missing:
        return {"state": "partial", "missing": missing, "reason": "partial_intake"}
    return {"state": "adequate", "missing": [], "reason": "required_fields_present"}


def artifact_id(workspace_id: str, engagement_id: str, package_id: str) -> str:
    digest = hashlib.sha256(f"{workspace_id}:{engagement_id}:{package_id}".encode("utf-8")).hexdigest()[:24]
    return f"svc-{workspace_id[:12]}-{digest}"


def verify_artifact_id(workspace_id: str, engagement_id: str, package_id: str, presented: str) -> bool:
    return presented == artifact_id(workspace_id, engagement_id, package_id)


@dataclass(frozen=True)
class ServiceEconomics:
    currency: str
    gross_service_revenue: Decimal
    labor_cost: Decimal
    tooling_cost: Decimal
    contractor_cost: Decimal
    revision_refund_reserve: Decimal
    contribution_profit: Decimal
    contribution_margin: Decimal
    contribution_per_hour: Decimal
    capacity_hours: Decimal
    max_simultaneous_clients: int
    target_monthly_contribution: Decimal
    required_clients: int
    incremental_contribution: Decimal | None
    orders_required_to_recover_fee: Decimal | None
    client_break_even: bool
    client_attractive_value: bool
    minimum_acceptable_value: bool
    evidence_state: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in payload.items():
            if isinstance(value, Decimal):
                payload[key] = str(value)
        return payload


def calculate_service_economics(
    package_view: Mapping[str, Any],
    *,
    fee: Any,
    consumed_hours: Any,
    ad_spend: Any | None = None,
    contribution_margin: Any | None = None,
    roas_before: Any | None = None,
    roas_after: Any | None = None,
    cac_before: Any | None = None,
    cac_after: Any | None = None,
    capacity_hours: Any = "160",
    target_monthly_contribution: Any = "4000",
    currency: str | None = None,
) -> ServiceEconomics:
    pack_currency = _currency(currency or package_view["currency"])
    if _currency(package_view["currency"]) != pack_currency:
        raise ServiceDeliveryError("currency mismatch; FX is not performed")
    fee_amt = _money(fee, "fee")
    hours = _dec(consumed_hours, "consumed_hours")
    if hours <= 0:
        raise ServiceDeliveryError("consumed_hours must be > 0")
    labor = _money(package_view["labor_cost"], "labor_cost")
    tooling = _money(package_view["tooling_cost"], "tooling_cost")
    contractor = _money(package_view["contractor_cost"], "contractor_cost")
    reserve = _money(package_view["refund_revision_reserve"], "refund_revision_reserve")
    costs = labor + tooling + contractor + reserve
    profit = (fee_amt - costs).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    margin = (profit / fee_amt).quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN) if fee_amt else Decimal("0")
    per_hour = (profit / hours).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    cap = _dec(capacity_hours, "capacity_hours")
    package_hours = _dec(package_view["estimated_hours"], "estimated_hours")
    max_clients = int(cap // package_hours) if package_hours > 0 else 0
    target = _money(target_monthly_contribution, "target_monthly_contribution")
    required = int((target / profit).to_integral_value(rounding=ROUND_HALF_EVEN)) if profit > 0 else 0

    incremental = None
    if None not in (ad_spend, contribution_margin, roas_before, roas_after):
        incremental = (
            _money(ad_spend, "ad_spend")
            * _dec(contribution_margin, "contribution_margin")
            * (_dec(roas_after, "roas_after") - _dec(roas_before, "roas_before"))
            - fee_amt
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    recovery = None
    if None not in (cac_before, cac_after):
        delta = _dec(cac_before, "cac_before") - _dec(cac_after, "cac_after")
        if delta <= 0:
            raise ServiceDeliveryError("CAC improvement must be > 0 to recover a fee")
        recovery = (fee_amt / delta).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    client_value = incremental if incremental is not None else profit
    return ServiceEconomics(
        currency=pack_currency,
        gross_service_revenue=fee_amt,
        labor_cost=labor,
        tooling_cost=tooling,
        contractor_cost=contractor,
        revision_refund_reserve=reserve,
        contribution_profit=profit,
        contribution_margin=margin,
        contribution_per_hour=per_hour,
        capacity_hours=cap,
        max_simultaneous_clients=max_clients,
        target_monthly_contribution=target,
        required_clients=required,
        incremental_contribution=incremental,
        orders_required_to_recover_fee=recovery,
        client_break_even=bool(client_value >= 0),
        client_attractive_value=bool(client_value >= fee_amt),
        minimum_acceptable_value=bool(client_value >= reserve),
        evidence_state="planning_assumption",
    )


def transition(current: str, nxt: str, *, quality_state: str | None = None) -> str:
    if current not in LIFECYCLE or nxt not in LIFECYCLE:
        raise ServiceDeliveryError("unknown lifecycle state")
    if nxt not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ServiceDeliveryError(f"illegal transition {current} -> {nxt}")
    if nxt == "analysis_in_progress" and quality_state in {"insufficient", "blocked", "unavailable"}:
        raise ServiceDeliveryError("insufficient data cannot become an optimistic diagnostic")
    return nxt


def open_engagement(
    *,
    client_id: str,
    workspace_id: str,
    package_alias: str,
    scope: str,
    intake: Mapping[str, Any],
    fee: Any,
    planned_hours: Any,
    currency: str | None = None,
) -> dict[str, Any]:
    workspace = _text(workspace_id, "workspace_id")
    client = _text(client_id, "client_id")
    if client.startswith("internal-") or workspace.startswith("internal-"):
        raise ServiceDeliveryError("internal ecommerce workspace cannot enter the client plane")
    package = resolve_priority_package(package_alias)
    requested_currency = _currency(currency or package["currency"])
    if requested_currency != package["currency"]:
        raise ServiceDeliveryError("currency mismatch; FX is not performed")
    quality = assess_data_quality(intake)
    state = "intake_received"
    if quality["state"] in {"insufficient", "blocked"}:
        state = "data_inadequate"
    elif quality["state"] == "unavailable":
        state = "blocked"
    engagement_id = hashlib.sha256(
        f"{client}:{workspace}:{package['package_id']}:{scope}".encode("utf-8")
    ).hexdigest()[:16]
    economics = None
    if state not in {"data_inadequate", "blocked"}:
        economics = calculate_service_economics(
            package,
            fee=fee,
            consumed_hours=planned_hours,
            ad_spend=intake.get("ad_spend"),
            contribution_margin=intake.get("contribution_margin"),
            roas_before=intake.get("roas_before"),
            roas_after=intake.get("roas_after"),
            cac_before=intake.get("cac_before"),
            cac_after=intake.get("cac_after"),
            currency=requested_currency,
        ).to_dict()
    return {
        "schema": SCHEMA,
        "engagement_id": engagement_id,
        "client_id": client,
        "workspace_id": workspace,
        "service_package": package,
        "scope": _text(scope, "scope"),
        "intake": _clean(intake),
        "evidence_set": list(intake.get("evidence_set") or ()),
        "data_quality_state": quality["state"],
        "data_quality": quality,
        "deliverables": package["deliverables"],
        "planned_hours": str(planned_hours),
        "consumed_hours": str(planned_hours),
        "tooling_cost": package["tooling_cost"],
        "fee": str(fee),
        "contribution": economics,
        "client_outcome": None,
        "approval_state": "planning_record",
        "delivery_state": state,
        "renewal_state": "not_started",
        "assumptions": ("Catalog prices are planning assumptions.", "No invoice or payment is created."),
        "missing_information": quality["missing"],
        "evidence_references": list(intake.get("evidence_references") or ()),
        "artifact_id": artifact_id(workspace, engagement_id, package["package_id"]),
        "generated_at": _now(),
        "record_kind": "planning_record",
    }


def catalog_margins() -> tuple[ClientProjectMargin, ...]:
    plan = build_finance_plan(packages=default_service_catalog())
    return plan.client_project_margins


def _clean(value: Any) -> Any:
    if isinstance(value, Mapping):
        out = {}
        for key, item in value.items():
            if FORBIDDEN_KEY.search(str(key)):
                continue
            out[key] = _clean(item)
        return out
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, tuple):
        return [_clean(item) for item in value]
    if isinstance(value, str) and SECRET_SHAPED.search(value):
        return "[redacted]"
    return value


def render_client_deliverable(engagement: Mapping[str, Any], *, other_workspace: str | None = None) -> dict[str, Any]:
    if other_workspace and other_workspace != engagement.get("workspace_id"):
        raise ServiceDeliveryError("cross-workspace export blocked")
    presented = engagement.get("artifact_id")
    package_id = engagement["service_package"]["package_id"]
    if not verify_artifact_id(
        engagement["workspace_id"], engagement["engagement_id"], package_id, str(presented)
    ):
        raise ServiceDeliveryError("forged artifact id")
    if engagement.get("data_quality_state") in {"insufficient", "blocked", "unavailable"}:
        raise ServiceDeliveryError("inadequate data cannot render an optimistic diagnostic")
    body = _clean(
        {
            "schema": "MarketOS.ClientServiceDeliverable.v1",
            "package": engagement["service_package"]["name"],
            "package_id": package_id,
            "workspace_id": engagement["workspace_id"],
            "artifact_id": presented,
            "observed_facts": list(engagement.get("evidence_set") or ()),
            "assumptions": list(engagement.get("assumptions") or ()),
            "derived_values": engagement.get("contribution"),
            "missing_evidence": list(engagement.get("missing_information") or ()),
            "confidence": "planning_only",
            "limitations": ["Planning record only.", "Not a live commercial authorization."],
            "recommendation": "Review evidence quality before any spend or launch.",
            "next_action": engagement["service_package"]["next_step_relationship"],
            "evidence_references": list(engagement.get("evidence_references") or ()),
            "currency": engagement["service_package"]["currency"],
            "generated_at": engagement.get("generated_at"),
            "record_kind": "planning_record",
        }
    )
    encoded = json.dumps(body, sort_keys=True, default=str)
    if any(marker in encoded.lower() for marker in ("internal prompt", "proprietary formula", "heuristic weight")):
        raise ServiceDeliveryError("unsafe export content")
    return body


__all__ = [
    "SCHEMA",
    "SUPPORTED_CURRENCIES",
    "LIFECYCLE",
    "QUALITY_STATES",
    "ServiceDeliveryError",
    "ServiceEconomics",
    "list_priority_packages",
    "resolve_priority_package",
    "assess_data_quality",
    "artifact_id",
    "verify_artifact_id",
    "calculate_service_economics",
    "transition",
    "open_engagement",
    "catalog_margins",
    "render_client_deliverable",
]
