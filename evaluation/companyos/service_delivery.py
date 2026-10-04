"""Client-facing productized-service delivery plane for CompanyOS.

This module composes existing canonical authorities instead of creating new
ones:

- :mod:`evaluation.companyos.service_catalog` remains the single service
  catalog and price/economics identity authority; this module only layers
  client-delivery metadata (description, eligibility, expected outcome,
  cost breakdown, price-evidence classification) on top of it.
- :mod:`backend.economics.kernel` (via :mod:`backend.economics`) remains the
  single money-arithmetic authority. Every dollar figure here is a
  ``Money``/``ServiceEconomics`` value produced by that kernel; no formula
  is reimplemented.
- :class:`backend.workspaces.client_workspace.ClientWorkspace` remains the
  tenant/workspace anchor; engagements are keyed by its ``workspace_id``.
- :mod:`backend.deliverables.package` (``DeliverablePackage`` /
  ``DeliverableSection``) remains the single deliverable-report container,
  registered in the existing :mod:`backend.deliverables.registry`
  ``DeliverableRegistry``. Client deliverables are distinguished only by
  ``package_type`` (prefixed ``client_``); no second report authority is
  created.
- :func:`evaluation.trustos.client_workspace_isolation.check_workspace_leakage`
  remains the sole internal-to-client export-boundary detector. Client
  deliverable payloads are checked against it before being considered
  client-safe.

This module is offline planning only. It never sends client messages,
collects payment, mutates a payment processor, places supplier orders, or
publishes anything. It never converts currency: every combination of two
``Money`` values across a currency mismatch fails closed via
``CurrencyMismatchError`` (inherited from the kernel), and this module adds
no conversion path of its own.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Mapping

from backend.deliverables.package import DeliverablePackage, DeliverableSection
from backend.deliverables.registry import DeliverableRegistry, get_deliverable_registry
from backend.economics import (
    CurrencyMismatchError,
    EvidenceRef,
    Money,
    ServiceEconomics,
    calculate_service_economics,
)
from backend.workspaces.client_workspace import ClientWorkspace

from .service_catalog import ServiceDeliverable, ServicePackage, default_service_catalog, package_map

# `check_workspace_leakage` is imported lazily inside
# build_client_service_deliverable(), not at module level: evaluation.trustos
# (via gate_runner.py) imports evaluation.companyos.approval_ledger, and this
# module is re-exported from evaluation/companyos/__init__.py, so a
# module-level import here completes a companyos -> trustos -> companyos
# circular-import cycle the first time either package is imported. Deferring
# the import to call time breaks the cycle without touching TrustOS, the
# Governor, or the Approval Ledger.

# ---------------------------------------------------------------------------
# A. Canonical service packages -- a compatibility layer over ServicePackage
# ---------------------------------------------------------------------------

PRICE_EVIDENCE_CLASSIFICATIONS = frozenset({"planning_assumption", "validated_price"})

CANONICAL_SERVICE_PACKAGE_IDS = (
    "product-validation-sprint",
    "unit-economics-cac-roas-diagnostic",
    "launch-draft-pack",
    "managed-acquisition-cro",
)


@dataclass(frozen=True)
class ClientFacingServicePackage:
    """Client-delivery metadata layered over the canonical ``ServicePackage``.

    Read-only compatibility view: every price/margin figure is delegated to
    ``evaluation.companyos.service_catalog`` and ``backend.economics.kernel``,
    never re-derived here.
    """

    package: ServicePackage
    description: str
    expected_outcome: str
    client_eligibility: tuple[str, ...]
    price_evidence_classification: str
    labor_cost: Money
    tooling_cost: Money
    optional_pass_through_cost: Money
    refund_revision_reserve: Money
    package_version: str = "v1"

    def __post_init__(self) -> None:
        if not isinstance(self.package, ServicePackage):
            raise ValueError("invalid service package")
        if self.price_evidence_classification not in PRICE_EVIDENCE_CLASSIFICATIONS:
            raise ValueError("invalid price evidence classification")
        currency = self.currency
        for money in (self.labor_cost, self.tooling_cost, self.optional_pass_through_cost, self.refund_revision_reserve):
            if not isinstance(money, Money):
                raise ValueError("service delivery cost must be money")
            if money.currency != currency:
                raise CurrencyMismatchError()

    @property
    def package_id(self) -> str:
        return self.package.canonical_package_id

    @property
    def name(self) -> str:
        return self.package.canonical_name

    @property
    def currency(self) -> str:
        return self.package.price_band.currency if self.package.price_band else self.package.currency

    @property
    def price_min_money(self) -> Money:
        return self.package.price_min_money

    @property
    def price_max_money(self) -> Money:
        return self.package.price_max_money

    @property
    def billing_model(self) -> str:
        return self.package.billing_model

    @property
    def estimated_delivery_hours(self) -> Decimal:
        return Decimal(str(self.package.estimated_delivery_hours))

    @property
    def required_client_inputs(self) -> tuple[str, ...]:
        return self.package.required_inputs

    @property
    def deliverables(self) -> tuple[ServiceDeliverable, ...]:
        return self.package.deliverables

    @property
    def acceptance_criteria(self) -> tuple[str, ...]:
        return self.package.acceptance_criteria

    @property
    def scope_exclusions(self) -> tuple[str, ...]:
        return self.package.exclusions

    @property
    def next_step_relationship(self) -> str:
        return self.package.next_step_relationship

    @property
    def pricing_evidence_state(self) -> str:
        return self.package.pricing_evidence_state

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "name": self.name,
            "description": self.description,
            "currency": self.currency,
            "price_min": self.price_min_money.to_dict(),
            "price_max": self.price_max_money.to_dict(),
            "billing_model": self.billing_model,
            "estimated_delivery_hours": str(self.estimated_delivery_hours),
            "estimated_labor_cost": self.labor_cost.to_dict(),
            "tooling_cost": self.tooling_cost.to_dict(),
            "optional_pass_through_cost": self.optional_pass_through_cost.to_dict(),
            "refund_revision_reserve": self.refund_revision_reserve.to_dict(),
            "required_client_inputs": list(self.required_client_inputs),
            "client_eligibility": list(self.client_eligibility),
            "deliverables": [item.name for item in self.deliverables],
            "acceptance_criteria": list(self.acceptance_criteria),
            "expected_outcome": self.expected_outcome,
            "scope_exclusions": list(self.scope_exclusions),
            "next_step_relationship": self.next_step_relationship,
            "price_evidence_state": self.pricing_evidence_state,
            "price_evidence_classification": self.price_evidence_classification,
            "package_version": self.package_version,
        }


def _money(amount: float, currency: str) -> Money:
    return Money(str(amount), currency, source="service_delivery_plane", provenance="assumed")


def _client_package(
    package_id: str,
    *,
    description: str,
    expected_outcome: str,
    client_eligibility: tuple[str, ...],
    classification: str,
    labor: float,
    tooling: float,
    pass_through: float,
    reserve: float,
    catalog: Mapping[str, ServicePackage],
) -> ClientFacingServicePackage:
    package = catalog[package_id]
    currency = package.price_band.currency if package.price_band else package.currency
    return ClientFacingServicePackage(
        package=package,
        description=description,
        expected_outcome=expected_outcome,
        client_eligibility=client_eligibility,
        price_evidence_classification=classification,
        labor_cost=_money(labor, currency),
        tooling_cost=_money(tooling, currency),
        optional_pass_through_cost=_money(pass_through, currency),
        refund_revision_reserve=_money(reserve, currency),
    )


def default_service_delivery_packages() -> tuple[ClientFacingServicePackage, ...]:
    """The 4 packages this plane represents, layered over the canonical catalog."""
    catalog = package_map(default_service_catalog())
    return (
        _client_package(
            "product-validation-sprint",
            catalog=catalog,
            description=(
                "A bounded, offline evidence review of one product candidate across "
                "marketplace demand, supplier feasibility, and consumer-attention "
                "signals, ending in a documented go/hold/no-go recommendation for "
                "further validation -- not a launch authorization."
            ),
            expected_outcome="A documented go/hold/no-go recommendation with named evidence gaps, not a guaranteed profitable launch.",
            client_eligibility=(
                "has a specific product candidate in mind",
                "can supply or approve collection of marketplace/supplier/consumer evidence",
                "not eligible for a product already live with real spend history -- see the Unit Economics diagnostic instead",
            ),
            classification="planning_assumption",
            labor=350.0, tooling=40.0, pass_through=0.0, reserve=35.0,
        ),
        _client_package(
            "unit-economics-cac-roas-diagnostic",
            catalog=catalog,
            description=(
                "A diagnostic of an existing product or campaign's unit economics: "
                "contribution margin and break-even CAC/ROAS, classified as "
                "data-driven when real order/spend history is supplied or as a "
                "planning estimate otherwise."
            ),
            expected_outcome="A documented contribution-margin and break-even CAC/ROAS figure with an explicit evidence classification.",
            client_eligibility=(
                "has at least one priced product or active campaign to diagnose",
                "ideally has 30+ days of order/spend history for a data-driven verdict rather than a planning estimate",
            ),
            classification="planning_assumption",
            labor=280.0, tooling=20.0, pass_through=0.0, reserve=20.0,
        ),
        _client_package(
            "launch-draft-pack",
            catalog=catalog,
            description=(
                "A draft offer, creative angle set, and store/funnel blueprint for "
                "one validated candidate, delivered as review-only drafts -- no "
                "publishing, ad spend, or provider mutation."
            ),
            expected_outcome="A reviewable draft offer and creative package ready for the client's own launch decision; not a published store or live campaign.",
            client_eligibility=(
                "has a Product Validation Sprint result or equivalent evidence in hand",
                "not eligible before supplier feasibility is at least partially evidenced",
            ),
            classification="planning_assumption",
            labor=550.0, tooling=60.0, pass_through=50.0, reserve=55.0,
        ),
        _client_package(
            "managed-acquisition-cro",
            catalog=catalog,
            description=(
                "A recurring, retainer-billed review of the client's own "
                "acquisition and conversion-rate data producing incremental-"
                "contribution and fee-recovery analysis -- never live ad "
                "management or spend authority."
            ),
            expected_outcome="A monthly incremental-contribution and fee-recovery report showing whether the retainer paid for itself; not a guarantee of ROAS improvement.",
            client_eligibility=(
                "has an active paid-acquisition channel with measurable spend and CAC/ROAS history",
                "data_inadequate clients (see the data-quality gate) are not eligible until evidence improves",
            ),
            classification="planning_assumption",
            labor=900.0, tooling=120.0, pass_through=0.0, reserve=90.0,
        ),
    )


# ---------------------------------------------------------------------------
# B. Client engagement lifecycle
# ---------------------------------------------------------------------------

ENGAGEMENT_STATES = (
    "intake", "screening", "data_inadequate", "eligible", "scoped",
    "evidence_collection", "analysis", "draft_ready", "client_review",
    "revision_requested", "approved", "delivered", "renewal_candidate",
    "upsell_candidate", "paused", "cancelled", "rejected",
)

# data_inadequate is a first-class, actionable state (not a warning flag):
# it is reachable from every stage that depends on client-supplied business
# data, and it always has a real way forward (resume screening once more
# evidence arrives) or out (reject/cancel) -- it is never a dead end that
# silently downgrades to an optimistic result.
_ENGAGEMENT_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "intake": ("screening", "paused", "cancelled"),
    "screening": ("eligible", "data_inadequate", "rejected", "paused"),
    "data_inadequate": ("screening", "rejected", "cancelled"),
    "eligible": ("scoped", "rejected", "paused"),
    "scoped": ("evidence_collection", "paused", "cancelled"),
    "evidence_collection": ("analysis", "data_inadequate", "paused"),
    "analysis": ("draft_ready", "data_inadequate", "paused"),
    "draft_ready": ("client_review", "paused"),
    "client_review": ("revision_requested", "approved", "paused"),
    "revision_requested": ("analysis", "cancelled"),
    "approved": ("delivered",),
    "delivered": ("renewal_candidate", "upsell_candidate", "cancelled"),
    "renewal_candidate": ("intake",),
    "upsell_candidate": ("intake",),
    "paused": ("intake", "screening", "eligible", "scoped", "evidence_collection", "analysis", "draft_ready", "client_review", "cancelled"),
    "cancelled": (),
    "rejected": (),
}


def _deterministic_id(*parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"svc-{digest[:24]}"


def new_engagement_id(client_id: str, workspace_id: str, package_id: str, created_at: str) -> str:
    return _deterministic_id("engagement", client_id, workspace_id, package_id, created_at)


@dataclass(frozen=True)
class ClientEngagement:
    engagement_id: str
    client_id: str
    workspace_id: str
    package_id: str
    scope: str
    intake_data: Mapping[str, Any]
    lifecycle_state: str
    data_quality_state: str
    evidence_set: tuple[EvidenceRef, ...]
    deliverable_ids: tuple[str, ...]
    planned_hours: Decimal
    consumed_hours: Decimal
    tooling_cost: Money
    fee: Money
    contribution: Money | None
    client_outcome: str
    approval_state: str
    delivery_state: str
    renewal_state: str
    assumptions: tuple[str, ...]
    missing_information: tuple[str, ...]
    evidence_references: tuple[str, ...]
    created_at: str
    updated_at: str
    history: tuple[str, ...] = ()
    read_only: bool = True
    network_calls: bool = False
    mutated: bool = False

    def __post_init__(self) -> None:
        if self.lifecycle_state not in ENGAGEMENT_STATES:
            raise ValueError("invalid engagement lifecycle state")
        if not self.client_id or not self.workspace_id:
            raise ValueError("engagement requires client_id and workspace_id")
        if self.tooling_cost.currency != self.fee.currency:
            raise CurrencyMismatchError()
        if self.contribution is not None and self.contribution.currency != self.fee.currency:
            raise CurrencyMismatchError()

    def to_dict(self) -> dict[str, Any]:
        return {
            "engagement_id": self.engagement_id,
            "client_id": self.client_id,
            "workspace_id": self.workspace_id,
            "package_id": self.package_id,
            "scope": self.scope,
            "intake_data": dict(self.intake_data),
            "lifecycle_state": self.lifecycle_state,
            "data_quality_state": self.data_quality_state,
            "evidence_set": [item.to_dict() for item in self.evidence_set],
            "deliverable_ids": list(self.deliverable_ids),
            "planned_hours": str(self.planned_hours),
            "consumed_hours": str(self.consumed_hours),
            "tooling_cost": self.tooling_cost.to_dict(),
            "fee": self.fee.to_dict(),
            "contribution": self.contribution.to_dict() if self.contribution else None,
            "client_outcome": self.client_outcome,
            "approval_state": self.approval_state,
            "delivery_state": self.delivery_state,
            "renewal_state": self.renewal_state,
            "assumptions": list(self.assumptions),
            "missing_information": list(self.missing_information),
            "evidence_references": list(self.evidence_references),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "history": list(self.history),
            "read_only": self.read_only,
            "network_calls": self.network_calls,
            "mutated": self.mutated,
        }


# "sk-" is a credential prefix only when it starts a token; it is also the tail of words such as
# desk-clamp-lamp or risk-review-pack, so it must not follow a letter or digit. A URL-escape (%3d) or a
# literal backslash escape (\\n) before it still counts as a boundary.
_SK_PREFIX = re.compile(r"(?<![a-z0-9])sk-|(?<=%[0-9a-f]{2})sk-|(?<=\\[nrt])sk-")
_SECRET_SHAPE_MARKERS = ("ghp_", "gho_", "ghu_", "ghs_", "ghr_", "-----begin", "bearer ")


def _reject_secret_shaped(value: str, *, field_name: str) -> None:
    lowered = value.lower()
    if _SK_PREFIX.search(lowered) or any(marker in lowered for marker in _SECRET_SHAPE_MARKERS):
        raise ValueError(f"secret-shaped value rejected in {field_name}")


def _reject_secret_shaped_recursive(value: Any, *, field_name: str) -> None:
    """Scan every string reachable from ``value``, including strings nested
    inside dicts/lists at any depth -- a secret pasted into a nested intake
    field (e.g. ``{"revenue": {"note": "sk-..."}}``) must be caught just as
    reliably as one in a top-level field."""
    if isinstance(value, str):
        _reject_secret_shaped(value, field_name=field_name)
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _reject_secret_shaped_recursive(item, field_name=f"{field_name}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_secret_shaped_recursive(item, field_name=f"{field_name}[{index}]")


def create_engagement(
    *,
    client_id: str,
    workspace: ClientWorkspace,
    package: ClientFacingServicePackage,
    scope: str,
    intake_data: Mapping[str, Any] | None = None,
    created_at: str = "offline-deterministic",
) -> ClientEngagement:
    if workspace.workspace_type != "client_service":
        raise ValueError("engagements require a client_service workspace")
    if not client_id:
        raise ValueError("client_id is required")
    _reject_secret_shaped(scope, field_name="scope")
    for key, value in (intake_data or {}).items():
        _reject_secret_shaped_recursive(value, field_name=f"intake_data.{key}")
    engagement_id = new_engagement_id(client_id, workspace.workspace_id, package.package_id, created_at)
    return ClientEngagement(
        engagement_id=engagement_id, client_id=client_id, workspace_id=workspace.workspace_id,
        package_id=package.package_id, scope=scope, intake_data=dict(intake_data or {}),
        lifecycle_state="intake", data_quality_state="unavailable", evidence_set=(), deliverable_ids=(),
        planned_hours=package.estimated_delivery_hours, consumed_hours=Decimal("0"),
        tooling_cost=package.tooling_cost, fee=package.price_min_money, contribution=None,
        client_outcome="pending", approval_state="not_requested", delivery_state="not_started",
        renewal_state="not_applicable", assumptions=(), missing_information=(), evidence_references=(),
        created_at=created_at, updated_at=created_at, history=("intake",),
    )


# Fields a lifecycle transition may legitimately update. Identity fields
# (engagement_id, client_id, workspace_id, package_id, created_at) are never
# in this set: allowing a transition call to change them would let a caller
# silently relabel one client's engagement as belonging to another
# workspace without going through create_engagement's validation or
# invalidating the engagement_id's own hash, defeating verify_engagement_id.
_MUTABLE_ENGAGEMENT_FIELDS = frozenset({
    "data_quality_state", "evidence_set", "deliverable_ids", "consumed_hours",
    "contribution", "client_outcome", "approval_state", "delivery_state",
    "renewal_state", "assumptions", "missing_information", "evidence_references",
})


def transition_engagement(engagement: ClientEngagement, new_state: str, *, updated_at: str = "offline-deterministic", **changes: Any) -> ClientEngagement:
    if new_state not in ENGAGEMENT_STATES:
        raise ValueError("unsupported engagement state")
    allowed = _ENGAGEMENT_TRANSITIONS.get(engagement.lifecycle_state, ())
    if new_state not in allowed:
        raise ValueError(f"invalid engagement transition: {engagement.lifecycle_state} -> {new_state}")
    unexpected = set(changes) - _MUTABLE_ENGAGEMENT_FIELDS
    if unexpected:
        raise ValueError(f"transition_engagement cannot change: {sorted(unexpected)}")
    return replace(engagement, lifecycle_state=new_state, updated_at=updated_at, history=engagement.history + (new_state,), **changes)


# ---------------------------------------------------------------------------
# C. Client business-data quality gate
#
# Distinct from evaluation.contracts.DataQuality (evidence provenance for
# product/campaign signals). This gate assesses the CLIENT's OWN supplied
# business data -- identity, offer identity, date range, revenue, orders,
# ad spend, CAC/ROAS inputs, product/fulfillment costs, shipping,
# returns/refunds, and payment/platform fees -- before any diagnostic is
# produced. Unknown values stay unknown here; they are never defaulted to
# zero (a missing field is recorded in ``missing_fields``, not silently
# treated as $0 revenue or 0 orders).
# ---------------------------------------------------------------------------

CLIENT_DATA_QUALITY_STATES = ("adequate", "partial", "stale", "conflicting", "insufficient", "blocked", "unavailable")
REQUIRED_CLIENT_DATA_FIELDS = (
    "client_identity", "product_offer_identity", "date_range", "revenue", "orders",
    "ad_spend", "cac_roas_inputs", "product_and_fulfillment_costs", "shipping",
    "returns_refunds", "payment_platform_fees",
)
_STATUS_PRIORITY = ("blocked", "unavailable", "insufficient", "conflicting", "stale", "partial", "adequate")


@dataclass(frozen=True)
class ClientDataQualityAssessment:
    status: str
    data_inadequate: bool
    present_fields: tuple[str, ...]
    missing_fields: tuple[str, ...]
    stale_fields: tuple[str, ...]
    conflicting_fields: tuple[str, ...]
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status not in CLIENT_DATA_QUALITY_STATES:
            raise ValueError("invalid client data quality status")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "data_inadequate": self.data_inadequate,
            "present_fields": list(self.present_fields),
            "missing_fields": list(self.missing_fields),
            "stale_fields": list(self.stale_fields),
            "conflicting_fields": list(self.conflicting_fields),
            "reasons": list(self.reasons),
        }


def assess_client_data_quality(
    intake: Mapping[str, Any] | None,
    *,
    max_age_days: float = 90.0,
    blocked: bool = False,
) -> ClientDataQualityAssessment:
    """Deterministically classify a client's own supplied business data.

    Expected per-field shape (all optional):
    ``{"orders": {"available": True, "as_of_days_ago": 10, "conflicting": False}, ...}``
    A field absent from ``intake`` is treated as unavailable.
    """
    if blocked:
        return ClientDataQualityAssessment("blocked", True, (), tuple(REQUIRED_CLIENT_DATA_FIELDS), (), (), ("intake explicitly blocked",))
    if not intake:
        return ClientDataQualityAssessment("unavailable", True, (), tuple(REQUIRED_CLIENT_DATA_FIELDS), (), (), ("no intake data supplied",))

    present: list[str] = []
    missing: list[str] = []
    stale: list[str] = []
    conflicting: list[str] = []
    reasons: list[str] = []

    for name in REQUIRED_CLIENT_DATA_FIELDS:
        field_value = intake.get(name)
        if not isinstance(field_value, Mapping) or not field_value.get("available"):
            missing.append(name)
            reasons.append(f"{name}_missing_or_unreliable")
            continue
        present.append(name)
        age = field_value.get("as_of_days_ago")
        if isinstance(age, (int, float)) and age > max_age_days:
            stale.append(name)
            reasons.append(f"{name}_stale")
        if field_value.get("conflicting"):
            conflicting.append(name)
            reasons.append(f"{name}_conflicting")

    if not missing and not stale and not conflicting:
        status = "adequate"
    elif len(missing) == len(REQUIRED_CLIENT_DATA_FIELDS):
        status = "insufficient"
    elif conflicting:
        status = "conflicting"
    elif stale:
        status = "stale"
    elif missing:
        status = "partial"
    else:
        status = "adequate"

    data_inadequate = bool(missing) or bool(conflicting) or bool(stale) or status in {"insufficient", "unavailable", "blocked"}
    return ClientDataQualityAssessment(status, data_inadequate, tuple(present), tuple(missing), tuple(stale), tuple(conflicting), tuple(reasons))


# ---------------------------------------------------------------------------
# D. Service economics -- pure pass-through to backend.economics.kernel
# ---------------------------------------------------------------------------

def evaluate_engagement_economics(
    package: ClientFacingServicePackage,
    *,
    fee: Money,
    ad_spend: Money,
    roas_before: Decimal | int | str | float,
    roas_after: Decimal | int | str | float,
    cac_before: Money,
    cac_after: Money,
    labor_cost: Money | None = None,
    contractor_cost: Money | None = None,
    tooling_cost: Money | None = None,
    pass_through_cost: Money | None = None,
    refund_revision_reserve: Money | None = None,
    delivery_hours: Decimal | int | str | float | None = None,
    capacity_hours: Decimal | int | str | float | None = None,
    target_monthly_contribution: Money | None = None,
    client_value_created: Money | None = None,
    minimum_acceptable_value_multiple: Decimal | int | str | float = Decimal("1"),
    evidence_refs: tuple[EvidenceRef, ...] = (),
) -> ServiceEconomics:
    """Compute one engagement's economics without duplicating kernel formulas.

    Currency is never converted: any override whose currency does not match
    ``fee.currency`` raises ``CurrencyMismatchError`` immediately, including
    package cost defaults when the caller quoted a different currency than
    the canonical package.
    """
    currency = fee.currency

    def _default_or(value: Money | None, package_value: Money) -> Money:
        if value is not None:
            return value
        if package_value.currency != currency:
            raise CurrencyMismatchError()
        return package_value

    labor = _default_or(labor_cost, package.labor_cost)
    # Explicit `is not None`, not `contractor_cost or ...`: an explicitly
    # supplied zero-amount Money is a valid, meaningful answer ("no
    # contractor cost on this engagement"), not an absent value that should
    # fall back to a default. `or` would happen to still work today because
    # Money defines no __bool__/__len__ (so any Money instance, including a
    # zero-amount one, is truthy) -- but relying on that absence is fragile
    # and reads as a bug at every future call site, so this is explicit.
    contractor = contractor_cost if contractor_cost is not None else Money.zero(currency, source="assumed_contractor_cost")
    if contractor.currency != currency:
        raise CurrencyMismatchError()
    delivery_cost = labor + contractor
    tooling = _default_or(tooling_cost, package.tooling_cost)
    pass_through = _default_or(pass_through_cost, package.optional_pass_through_cost)
    reserve = _default_or(refund_revision_reserve, package.refund_revision_reserve)

    return calculate_service_economics(
        package.package_id,
        fee,
        ad_spend=ad_spend,
        contribution_margin=Decimal(str(package.package.gross_margin_estimate)),
        roas_before=roas_before,
        roas_after=roas_after,
        cac_before=cac_before,
        cac_after=cac_after,
        delivery_hours=delivery_hours if delivery_hours is not None else package.estimated_delivery_hours,
        capacity_hours=capacity_hours,
        evidence_refs=evidence_refs,
        delivery_cost=delivery_cost,
        tooling_cost=tooling,
        pass_through_cost=pass_through,
        refund_revision_reserve=reserve,
        target_monthly_contribution=target_monthly_contribution,
        client_value_created=client_value_created,
        minimum_acceptable_value_multiple=minimum_acceptable_value_multiple,
    )


CLIENT_VALUE_CLASSIFICATIONS = (
    "unknown", "below_break_even", "break_even", "below_minimum_acceptable", "acceptable", "attractive",
)


def classify_client_value(economics: ServiceEconomics, *, attractive_multiple: Decimal | int | str | float = Decimal("3")) -> str:
    """Distinguish break-even, minimum-acceptable, and attractive client value."""
    if economics.client_value_multiple is None:
        return "unknown"
    multiple = economics.client_value_multiple
    attractive = attractive_multiple if isinstance(attractive_multiple, Decimal) else Decimal(str(attractive_multiple))
    if multiple < Decimal("1"):
        return "below_break_even"
    if multiple == Decimal("1"):
        return "break_even"
    if multiple >= attractive:
        return "attractive"
    if multiple >= economics.minimum_acceptable_value_multiple:
        return "acceptable"
    return "below_minimum_acceptable"


# ---------------------------------------------------------------------------
# E. Deliverable generation -- reuses backend.deliverables, not a new authority
# ---------------------------------------------------------------------------

CLIENT_DELIVERABLE_PACKAGE_TYPES: dict[str, str] = {
    "product-validation-sprint": "client_product_validation_sprint",
    "unit-economics-cac-roas-diagnostic": "client_unit_economics_diagnostic",
    "launch-draft-pack": "client_launch_draft_pack",
    "managed-acquisition-cro": "client_managed_acquisition_diagnostic",
}

_LEAK_MARKERS = ("-----begin", "<html", "other_client", "cross_client")
_FORBIDDEN_KEYS = {"internal_notes", "prompt", "source_code", "formula", "credentials", "raw_payload", "filesystem_path", "model_trace", "api_key", "private_key", "password"}


def _redact_client_unsafe_values(value: Any) -> Any:
    """Best-effort redaction once check_workspace_leakage flags a payload.

    Mirrors the same reuse-then-redact pattern already established in
    evaluation/commerce/product_validation_report.py: the TrustOS
    leakage detector remains the sole authority, this only removes what it
    flags rather than re-implementing detection.
    """
    if isinstance(value, Mapping):
        return {key: "[redacted: internal-only field removed]" if str(key).lower() in _FORBIDDEN_KEYS else _redact_client_unsafe_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_client_unsafe_values(item) for item in value]
    if isinstance(value, str) and (_SK_PREFIX.search(value.lower()) or any(marker in value.lower() for marker in _LEAK_MARKERS)):
        return "[redacted: client-unsafe value removed]"
    return value


def build_client_service_deliverable(
    engagement: ClientEngagement,
    package: ClientFacingServicePackage,
    economics: ServiceEconomics | None,
    data_quality: ClientDataQualityAssessment,
    *,
    observed_facts: tuple[str, ...] = (),
    assumptions: tuple[str, ...] = (),
    limitations: tuple[str, ...] = (),
    recommendation: str = "",
    next_action: str = "",
    generated_at: str = "offline-deterministic",
    registry: DeliverableRegistry | None = None,
) -> DeliverablePackage:
    """Build one client-safe deliverable for an engagement.

    When the client's own data is data_inadequate, this never produces an
    optimistic diagnostic: it returns a ``blocked`` package naming the exact
    missing evidence instead of computed figures.
    """
    from evaluation.trustos.client_workspace_isolation import check_workspace_leakage

    if not verify_engagement_id(engagement):
        raise ValueError("engagement identity failed verification (forged or tampered record)")
    if engagement.package_id != package.package_id:
        raise ValueError("engagement and package do not match")
    package_type = CLIENT_DELIVERABLE_PACKAGE_TYPES.get(package.package_id, f"client_{package.package_id}")

    if data_quality.data_inadequate or economics is None:
        status = "blocked"
        derived_values: dict[str, Any] = {}
        confidence = "insufficient"
        recommendation = recommendation or "Supply the missing client data before this diagnostic can be produced."
        next_action = next_action or "Collect the missing evidence and resubmit intake."
    else:
        status = "completed"
        derived_values = {
            "contribution": economics.contribution.to_dict() if economics.contribution else None,
            "contribution_margin": str(economics.contribution_margin) if economics.contribution_margin is not None else "unknown",
            "incremental_contribution": economics.incremental_contribution.to_dict(),
            "orders_required_to_recover_fee": str(economics.orders_required_to_recover_fee) if economics.orders_required_to_recover_fee is not None else "unknown",
            "client_value_classification": classify_client_value(economics),
        }
        confidence = economics.evidence_state

    payload: dict[str, Any] = {
        "observed_facts": list(observed_facts),
        "assumptions": list(assumptions),
        "derived_values": derived_values,
        "missing_evidence": list(dict.fromkeys((*data_quality.missing_fields, *engagement.missing_information))),
        "confidence": confidence,
        "limitations": list(limitations),
        "recommendation": recommendation,
        "next_action": next_action,
        "evidence_references": [item.to_dict() for item in engagement.evidence_set],
        "currency": package.currency,
        "source_timestamps": {"generated_at": generated_at},
    }
    # Redaction runs unconditionally, not gated on check_workspace_leakage's
    # own findings: that detector's SECRET_KEYS/DATA_CLASSES matching does
    # not cover every key this module itself treats as forbidden (e.g.
    # "formula", "internal_notes", "filesystem_path"), so gating redaction
    # on its result left this module's own forbidden-key list unenforced
    # whenever no *other* marker also happened to be present. Redaction is
    # cheap and idempotent, so there is no reason to skip it.
    leakage_findings = check_workspace_leakage(payload, client_safe=True)
    payload = _redact_client_unsafe_values(payload)
    # Every client-facing string is derived from the redacted payload, not
    # the original arguments: recommendation/next_action/exec_summary must
    # never carry a value that bypassed redaction.
    recommendation = str(payload["recommendation"])
    next_action = str(payload["next_action"])
    exec_summary = (
        f"{package.name}: client data is currently data_inadequate ({data_quality.status}). No diagnostic is produced until the missing evidence below is supplied."
        if status == "blocked"
        else f"{package.name}: {recommendation or 'see analysis'}."
    )

    section = DeliverableSection("client_deliverable", package.name, 1, exec_summary, exec_summary, metadata=payload)
    deliverable_id = _deterministic_id("deliverable", engagement.engagement_id, package.package_id, generated_at)
    dp = DeliverablePackage(
        package_id=deliverable_id,
        workspace_id=engagement.workspace_id,
        package_type=package_type,
        title=f"{package.name} for engagement {engagement.engagement_id}",
        objective=package.expected_outcome,
        status=status,
        sections=[section],
        executive_summary=exec_summary,
        recommendations=[recommendation] if recommendation else [],
        risk_flags=list(data_quality.reasons),
        missing_evidence=list(payload["missing_evidence"]),
        next_actions=[next_action] if next_action else [],
        metadata={
            "currency": package.currency,
            "confidence": confidence,
            "client_id": engagement.client_id,
            "leakage_findings": len(leakage_findings),
            "read_only": True,
            "network_calls": False,
            "mutated": False,
        },
    )
    reg = registry or get_deliverable_registry()
    reg.register_package(dp)
    return dp


# ---------------------------------------------------------------------------
# F. Workspace-scoped access -- reuses DeliverableRegistry's own filtering
# ---------------------------------------------------------------------------

def verify_engagement_id(engagement: ClientEngagement) -> bool:
    """Recompute the deterministic engagement id from its own client_id,
    workspace_id, package_id, and created_at, and compare it against the
    id the record actually carries. A record whose workspace_id (or any
    other identity field) was mutated after construction -- e.g. an
    attempt to relabel Client A's engagement as belonging to Client B's
    workspace -- fails this check even though every individual field still
    looks well-formed."""
    expected = new_engagement_id(engagement.client_id, engagement.workspace_id, engagement.package_id, engagement.created_at)
    return expected == engagement.engagement_id


def get_client_engagement_for_workspace(
    engagements: Mapping[str, ClientEngagement], *, workspace_id: str, engagement_id: str
) -> ClientEngagement | None:
    """Return an engagement only when its workspace_id matches the caller's."""
    if not workspace_id:
        raise ValueError("workspace_id is required for client engagement access")
    engagement = engagements.get(engagement_id)
    if engagement is None or engagement.workspace_id != workspace_id:
        return None
    if not verify_engagement_id(engagement):
        return None
    return engagement


def list_client_deliverables_for_workspace(
    registry: DeliverableRegistry, *, workspace_id: str, package_type: str | None = None, limit: int = 50
) -> tuple[DeliverablePackage, ...]:
    """List deliverables scoped strictly to one workspace_id.

    Never call ``registry.list_packages`` without ``workspace_id`` from a
    client-facing call site -- that is how cross-client leakage would occur.
    """
    if not workspace_id:
        raise ValueError("workspace_id is required for client deliverable access")
    return tuple(registry.list_packages(workspace_id=workspace_id, package_type=package_type, limit=limit))


# ---------------------------------------------------------------------------
# Top-level deterministic snapshot, consistent with other CompanyOS reports
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ServiceDeliveryPlaneReport:
    report_version: str
    generated_at: str
    packages: tuple[Mapping[str, Any], ...]
    read_only: bool = True
    network_calls: bool = False
    mutated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": self.report_version,
            "generated_at": self.generated_at,
            "packages": [dict(item) for item in self.packages],
            "read_only": self.read_only,
            "network_calls": self.network_calls,
            "mutated": self.mutated,
        }


def build_service_delivery_plane_report(
    *, generated_at: str = "offline-deterministic", packages: tuple[ClientFacingServicePackage, ...] | None = None
) -> ServiceDeliveryPlaneReport:
    packages = packages or default_service_delivery_packages()
    return ServiceDeliveryPlaneReport("service-delivery-plane-v1", generated_at, tuple(item.to_dict() for item in packages))


__all__ = [
    "PRICE_EVIDENCE_CLASSIFICATIONS", "CANONICAL_SERVICE_PACKAGE_IDS", "ClientFacingServicePackage",
    "default_service_delivery_packages",
    "ENGAGEMENT_STATES", "ClientEngagement", "create_engagement", "transition_engagement", "new_engagement_id",
    "CLIENT_DATA_QUALITY_STATES", "REQUIRED_CLIENT_DATA_FIELDS", "ClientDataQualityAssessment", "assess_client_data_quality",
    "evaluate_engagement_economics", "CLIENT_VALUE_CLASSIFICATIONS", "classify_client_value",
    "CLIENT_DELIVERABLE_PACKAGE_TYPES", "build_client_service_deliverable",
    "verify_engagement_id", "get_client_engagement_for_workspace", "list_client_deliverables_for_workspace",
    "ServiceDeliveryPlaneReport", "build_service_delivery_plane_report",
]
