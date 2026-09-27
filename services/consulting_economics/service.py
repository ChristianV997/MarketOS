"""Bounded consulting-economics adapter over the canonical economics kernel.

This module is deliberately an adapter, not a second financial authority. It
normalizes product-agnostic consulting inputs, makes missing evidence explicit,
delegates calculations to ``backend.economics.kernel``, and projects only the
allowlisted fields accepted by the existing TrustOS client boundary.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from backend.economics.kernel import (
    CurrencyMismatchError,
    EconomicsError,
    EvidenceRef,
    Money,
    ServiceEconomics,
    calculate_service_economics,
    canonical_json,
)
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry
from evaluation.companyos.service_delivery import classify_client_value
from evaluation.trustos.client_workspace_isolation import (
    ClientWorkspaceEvidenceExport,
    export_client_evidence,
)

CONSULTING_ECONOMICS_SCHEMA = "MarketOS.ConsultingEconomics.v1"
SERVICE_MODELS = ("project", "retainer", "milestone", "recurring")
SCENARIOS = ("conservative", "base", "upside", "downside")
EVIDENCE_MODES = ("fixture", "manual")
MONEY_FIELDS = (
    "package_price",
    "internal_labor_cost",
    "contractor_cost",
    "tooling_cost",
    "pass_through_cost",
    "payment_fees",
    "acquisition_cost",
    "revision_support_reserve",
    "fixed_monthly_cost",
    "target_monthly_contribution",
    "client_value_created",
)
COST_FIELDS = (
    "internal_labor_cost",
    "contractor_cost",
    "tooling_cost",
    "pass_through_cost",
    "payment_fees",
    "acquisition_cost",
    "revision_support_reserve",
)
REQUIRED_FIELDS = ("package_price", "internal_labor_cost", "delivery_hours")
_SAFE_TEXT = re.compile(r"^[^\x00-\x1f\x7f]{1,160}$")
_ZERO = Decimal("0")
_ONE = Decimal("1")

# These are visible planning sensitivities, not market facts. Callers can
# replace them per scenario with explicit inputs. Money scaling itself uses
# Money.multiply, so this adapter does not reimplement financial arithmetic.
_DEFAULT_FACTORS: dict[str, dict[str, Decimal]] = {
    "conservative": {"price": Decimal("0.90"), "cost": Decimal("1.10"), "hours": Decimal("1.10")},
    "base": {"price": _ONE, "cost": _ONE, "hours": _ONE},
    "upside": {"price": Decimal("1.10"), "cost": Decimal("0.90"), "hours": Decimal("0.90")},
    "downside": {"price": Decimal("0.80"), "cost": Decimal("1.20"), "hours": Decimal("1.20")},
}


class ConsultingEconomicsInputError(ValueError):
    """Stable validation error for the consulting-economics boundary."""


def _decimal(value: Any, field_name: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ConsultingEconomicsInputError(f"invalid {field_name}")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ConsultingEconomicsInputError(f"invalid {field_name}") from None
    if not result.is_finite():
        raise ConsultingEconomicsInputError(f"invalid {field_name}")
    return result


def _safe_text(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return ""
    if not isinstance(value, str) or not _SAFE_TEXT.fullmatch(value.strip()):
        raise ConsultingEconomicsInputError(f"invalid {field_name}")
    return value.strip()


def _scale_money(value: Money | None, factor: Decimal) -> Money | None:
    return value.multiply(factor) if value is not None else None


def _stable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Money):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _stable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_stable(item) for item in value]
    return value


@dataclass(frozen=True)
class ConsultingEconomicsRequest:
    """Typed request for any consulting, agency, or productized service."""

    service_id: str
    offering_name: str
    service_model: str
    currency: str
    package_price: Any = None
    internal_labor_hours: Any = None
    internal_labor_cost: Any = None
    contractor_cost: Any = None
    tooling_cost: Any = None
    pass_through_cost: Any = None
    payment_fees: Any = None
    acquisition_cost: Any = None
    revision_support_reserve: Any = None
    delivery_hours: Any = None
    capacity_hours: Any = None
    maximum_concurrent_clients: Any = None
    fixed_monthly_cost: Any = None
    target_monthly_contribution: Any = None
    client_value_created: Any = None
    minimum_acceptable_value_multiple: Any = Decimal("1")
    evidence_mode: str = "fixture"
    evidence_id: str = ""
    source_ref: str = ""
    fx_provenance: Mapping[str, Any] | None = None
    scenario_overrides: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ConsultingEconomicsRequest":
        if not isinstance(value, Mapping):
            raise ConsultingEconomicsInputError("request must be an object")
        raw = dict(value)
        if "package_price" not in raw and "service_fee" in raw:
            raw["package_price"] = raw.pop("service_fee")
        elif "package_price" in raw and "service_fee" in raw:
            raise ConsultingEconomicsInputError("duplicate package price fields")
        allowed = {item.name for item in cls.__dataclass_fields__.values()}
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise ConsultingEconomicsInputError("unknown consulting economics field")
        return cls(**raw)


def _parse_fx(value: Mapping[str, Any] | None) -> tuple[Decimal, str, Decimal, str]:
    if not isinstance(value, Mapping):
        raise ConsultingEconomicsInputError("currency mismatch requires FX provenance")
    rate = _decimal(value.get("rate"), "FX rate")
    timestamp = _safe_text(value.get("timestamp"), "FX timestamp")
    uncertainty = _decimal(value.get("uncertainty", "0"), "FX uncertainty")
    source = _safe_text(value.get("source", "manual_fx"), "FX source")
    if rate <= _ZERO or uncertainty < _ZERO or uncertainty > _ONE:
        raise ConsultingEconomicsInputError("invalid FX provenance")
    return rate, timestamp, uncertainty, source


def _parse_money(
    value: Any,
    field_name: str,
    currency: str,
    fx_provenance: Mapping[str, Any] | None,
) -> Money | None:
    if value is None:
        return None
    if isinstance(value, Money):
        money = value
    elif isinstance(value, Mapping):
        if "amount" not in value:
            raise ConsultingEconomicsInputError(f"invalid {field_name}")
        try:
            money = Money(
                value["amount"],
                str(value.get("currency", currency)).upper(),
                source=_safe_text(value.get("source", "explicit"), f"{field_name} source"),
                provenance=_safe_text(value.get("provenance", "manual"), f"{field_name} provenance"),
                evidence_state=_safe_text(value.get("evidence_state", "unknown"), f"{field_name} evidence state"),
            )
        except (EconomicsError, ConsultingEconomicsInputError):
            raise ConsultingEconomicsInputError(f"invalid {field_name}") from None
    else:
        raise ConsultingEconomicsInputError(f"invalid {field_name}")
    if money.currency != currency:
        fx = value.get("fx") if isinstance(value, Mapping) else None
        fx = fx or fx_provenance
        rate, timestamp, uncertainty, source = _parse_fx(fx)
        try:
            money = money.convert(currency, exchange_rate=rate, exchange_rate_timestamp=timestamp, uncertainty=uncertainty, source=source)
        except EconomicsError:
            raise ConsultingEconomicsInputError(f"invalid FX for {field_name}") from None
    if money.evidence_state in {"live_readonly", "verified"}:
        raise ConsultingEconomicsInputError(f"live evidence is not supported for {field_name}")
    if money.amount < _ZERO:
        raise ConsultingEconomicsInputError(f"negative {field_name} is not allowed")
    return money


def _evidence_ref(request: ConsultingEconomicsRequest) -> EvidenceRef:
    mode = _safe_text(request.evidence_mode, "evidence mode")
    if mode not in EVIDENCE_MODES:
        raise ConsultingEconomicsInputError("live evidence mode is not supported")
    evidence_id = _safe_text(request.evidence_id or f"{request.service_id}-evidence", "evidence id")
    source_ref = _safe_text(request.source_ref, "source reference", allow_empty=True)
    return EvidenceRef(
        evidence_id=evidence_id,
        source_type=mode,
        document_ref=source_ref,
        extraction_method=mode,
        evidence_state="fixture" if mode == "fixture" else "assumed",
        human_confirmed=False,
    )


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    recommendation: str
    evidence_status: str
    missing_evidence: tuple[str, ...] = ()
    unavailable_metrics: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    next_action: str = ""
    economics: ServiceEconomics | None = None
    minimum_viable_price: Money | None = None
    break_even_client_count: Decimal | None = None
    maximum_concurrent_clients: Decimal | None = None
    explicit_zero_inputs: tuple[str, ...] = ()
    classification_detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "recommendation": self.recommendation,
            "evidence_status": self.evidence_status,
            "missing_evidence": list(self.missing_evidence),
            "unavailable_metrics": list(self.unavailable_metrics),
            "blockers": list(self.blockers),
            "next_action": self.next_action,
            "economics": self.economics.to_dict() if self.economics else None,
            "minimum_viable_price": self.minimum_viable_price.to_dict() if self.minimum_viable_price else None,
            "break_even_client_count": str(self.break_even_client_count) if self.break_even_client_count is not None else None,
            "maximum_concurrent_clients": str(self.maximum_concurrent_clients) if self.maximum_concurrent_clients is not None else None,
            "explicit_zero_inputs": list(self.explicit_zero_inputs),
            "classification_detail": self.classification_detail,
        }


@dataclass(frozen=True)
class ConsultingEconomicsReport:
    schema: str
    service_id: str
    offering_name: str
    service_model: str
    currency: str
    evidence_class: str
    recommendation: str
    scenarios: tuple[ScenarioResult, ...]
    blockers: tuple[str, ...]
    evidence_required: tuple[str, ...]
    next_action: str
    safety: Mapping[str, Any]
    fingerprint: str

    def _body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "service_id": self.service_id,
            "offering_name": self.offering_name,
            "service_model": self.service_model,
            "currency": self.currency,
            "evidence_class": self.evidence_class,
            "recommendation": self.recommendation,
            "scenarios": [item.to_dict() for item in self.scenarios],
            "blockers": list(self.blockers),
            "evidence_required": list(self.evidence_required),
            "next_action": self.next_action,
            "safety": dict(self.safety),
        }

    def to_dict(self) -> dict[str, Any]:
        body = self._body()
        body["fingerprint"] = self.fingerprint
        return _stable(body)

    def client_safe_payload(self, workspace_id: str) -> dict[str, Any]:
        """Return only fields accepted by the existing TrustOS export boundary."""
        return {
            "workspace_id": workspace_id,
            "status": self.recommendation,
            "blockers": list(self.blockers),
            "evidence_required": list(self.evidence_required),
            "approvals_required": ["human review before any live action"],
            "next_actions": [self.next_action],
        }


def _request_values(request: ConsultingEconomicsRequest, scenario: str) -> dict[str, Any]:
    values = {name: getattr(request, name) for name in MONEY_FIELDS}
    values.update({
        "delivery_hours": request.delivery_hours if request.delivery_hours is not None else request.internal_labor_hours,
        "capacity_hours": request.capacity_hours,
        "maximum_concurrent_clients": request.maximum_concurrent_clients,
        "minimum_acceptable_value_multiple": request.minimum_acceptable_value_multiple,
    })
    overrides = request.scenario_overrides.get(scenario, {})
    if overrides and not isinstance(overrides, Mapping):
        raise ConsultingEconomicsInputError("invalid scenario overrides")
    for key, value in overrides.items():
        if key not in values:
            raise ConsultingEconomicsInputError("unknown scenario field")
        values[key] = value
    factors = _DEFAULT_FACTORS[scenario]
    if not overrides:
        values["package_price"] = _scale_money(_parse_money(values["package_price"], "package price", request.currency.upper(), request.fx_provenance), factors["price"])
        for field_name in MONEY_FIELDS:
            if field_name != "package_price":
                parsed = _parse_money(values[field_name], field_name, request.currency.upper(), request.fx_provenance)
                values[field_name] = _scale_money(parsed, factors["cost"] if field_name in COST_FIELDS else _ONE)
        if values["delivery_hours"] is not None:
            values["delivery_hours"] = _decimal(values["delivery_hours"], "delivery hours") * factors["hours"]
        if values["capacity_hours"] is not None:
            values["capacity_hours"] = _decimal(values["capacity_hours"], "capacity hours")
    else:
        for field_name in MONEY_FIELDS:
            values[field_name] = _parse_money(values[field_name], field_name, request.currency.upper(), request.fx_provenance)
    return values


def _scenario(
    request: ConsultingEconomicsRequest,
    scenario: str,
    evidence_ref: EvidenceRef,
) -> ScenarioResult:
    currency = request.currency.upper()
    values = _request_values(request, scenario)
    parsed: dict[str, Money | None] = {
        name: _parse_money(values[name], name, currency, request.fx_provenance) if name not in {"package_price"} or values[name] is not None else None
        for name in MONEY_FIELDS
    }
    explicit_zero = tuple(sorted(name for name, value in parsed.items() if value is not None and value.amount == _ZERO))
    missing = [name for name in REQUIRED_FIELDS if (parsed.get(name) if name != "delivery_hours" else values.get(name)) is None]
    if values.get("delivery_hours") is not None:
        delivery_hours = _decimal(values["delivery_hours"], "delivery hours")
        if delivery_hours < _ZERO:
            raise ConsultingEconomicsInputError("negative delivery hours is not allowed")
    else:
        delivery_hours = None
    capacity_hours = None if values.get("capacity_hours") is None else _decimal(values["capacity_hours"], "capacity hours")
    if capacity_hours is not None and capacity_hours < _ZERO:
        raise ConsultingEconomicsInputError("negative capacity hours is not allowed")
    if missing:
        missing_tuple = tuple(sorted(missing))
        return ScenarioResult(
            scenario,
            "needs_evidence",
            "incomplete",
            missing_evidence=missing_tuple,
            unavailable_metrics=("contribution", "minimum_viable_price", "break_even_client_count"),
            next_action=f"Collect: {', '.join(missing_tuple)}.",
            explicit_zero_inputs=explicit_zero,
        )

    missing_costs = tuple(sorted(name for name in COST_FIELDS if parsed.get(name) is None))
    package_price = parsed["package_price"]
    internal_labor = parsed["internal_labor_cost"]
    assert isinstance(package_price, Money) and isinstance(internal_labor, Money)
    zero = Money.zero(currency, source="unavailable_kernel_context")
    direct_cost = internal_labor
    for field_name in ("contractor_cost", "payment_fees", "acquisition_cost"):
        direct_cost = direct_cost + (parsed[field_name] or Money.zero(currency, source=f"unavailable_{field_name}"))
    tooling = parsed["tooling_cost"] or Money.zero(currency, source="unavailable_tooling_cost")
    pass_through = parsed["pass_through_cost"] or Money.zero(currency, source="unavailable_pass_through_cost")
    reserve = parsed["revision_support_reserve"] or Money.zero(currency, source="unavailable_revision_support_reserve")
    economics = calculate_service_economics(
        request.service_id,
        package_price,
        ad_spend=zero,
        contribution_margin=Decimal("0"),
        roas_before=Decimal("0"),
        roas_after=Decimal("0"),
        cac_before=zero,
        cac_after=zero,
        delivery_hours=delivery_hours,
        capacity_hours=capacity_hours,
        evidence_refs=(evidence_ref,),
        delivery_cost=direct_cost,
        tooling_cost=tooling,
        pass_through_cost=pass_through,
        refund_revision_reserve=reserve,
        target_monthly_contribution=parsed["target_monthly_contribution"],
        client_value_created=parsed["client_value_created"],
        minimum_acceptable_value_multiple=values["minimum_acceptable_value_multiple"],
    )
    unavailable = []
    if capacity_hours is None:
        unavailable.append("capacity_metrics")
    if parsed["client_value_created"] is None:
        unavailable.append("client_value_multiple")
    if parsed["acquisition_cost"] is None:
        unavailable.append("acquisition_cost")
    maximum_clients = economics.maximum_simultaneous_clients
    explicit_max = values.get("maximum_concurrent_clients")
    if explicit_max is not None:
        explicit_max_decimal = _decimal(explicit_max, "maximum concurrent clients")
        if explicit_max_decimal < _ZERO:
            raise ConsultingEconomicsInputError("negative maximum concurrent clients is not allowed")
        maximum_clients = explicit_max_decimal if maximum_clients is None else min(maximum_clients, explicit_max_decimal)
    fixed = parsed["fixed_monthly_cost"]
    break_even_clients = None
    if fixed is not None and economics.contribution is not None and economics.contribution.amount > _ZERO:
        break_even_clients = fixed.amount / economics.contribution.amount
    elif fixed is None:
        unavailable.append("break_even_client_count")
    minimum_price = None if missing_costs else package_price - economics.contribution
    over_capacity = capacity_hours is not None and delivery_hours > capacity_hours
    if over_capacity:
        recommendation = "blocked"
        evidence_status = "complete"
        blockers = ("delivery_hours_exceed_capacity",)
        next_action = "Reduce delivery hours or increase bounded capacity before accepting the engagement."
    elif missing_costs:
        recommendation = "needs_evidence"
        evidence_status = "incomplete"
        next_action = f"Collect: {', '.join(missing_costs)} before relying on contribution or pricing."
    elif economics.contribution is None or economics.contribution.amount <= _ZERO:
        recommendation = "below_break_even"
        evidence_status = "complete"
        next_action = "Reprice or reduce delivery costs before accepting the engagement."
    elif economics.client_value_multiple is not None:
        detail = classify_client_value(economics)
        recommendation = {"attractive": "attractive", "acceptable": "acceptable", "below_break_even": "below_break_even", "break_even": "acceptable", "below_minimum_acceptable": "needs_evidence"}.get(detail, "needs_evidence")
        evidence_status = "complete"
        next_action = "Review the value evidence and approve scope before any live action."
    else:
        detail = "client_value_unavailable"
        recommendation = "acceptable"
        evidence_status = "complete"
        next_action = "Validate client value and capacity before making a commercial commitment."
    return ScenarioResult(
        scenario,
        recommendation,
        evidence_status,
        missing_evidence=missing_costs,
        unavailable_metrics=tuple(sorted(set(unavailable))),
        blockers=blockers if over_capacity else (),
        next_action=next_action,
        economics=economics,
        minimum_viable_price=minimum_price,
        break_even_client_count=break_even_clients,
        maximum_concurrent_clients=maximum_clients,
        explicit_zero_inputs=explicit_zero,
        classification_detail=locals().get("detail", "direct_contribution"),
    )


def _blocked_report(request: ConsultingEconomicsRequest | None, reason: str) -> ConsultingEconomicsReport:
    service_id = request.service_id if request else "unknown"
    offering_name = request.offering_name if request else "unknown"
    service_model = request.service_model if request else "unknown"
    currency = request.currency.upper() if request else "unknown"
    body = {
        "schema": CONSULTING_ECONOMICS_SCHEMA,
        "service_id": service_id,
        "offering_name": offering_name,
        "service_model": service_model,
        "currency": currency,
        "evidence_class": "unavailable",
        "recommendation": "blocked",
        "scenarios": [],
        "blockers": [reason],
        "evidence_required": [],
        "next_action": "Correct the bounded input contract and rerun offline.",
        "safety": _safety(),
    }
    fingerprint = hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
    return ConsultingEconomicsReport(
        schema=body["schema"],
        service_id=body["service_id"],
        offering_name=body["offering_name"],
        service_model=body["service_model"],
        currency=body["currency"],
        evidence_class=body["evidence_class"],
        recommendation=body["recommendation"],
        scenarios=(),
        blockers=tuple(body["blockers"]),
        evidence_required=tuple(body["evidence_required"]),
        next_action=body["next_action"],
        safety=body["safety"],
        fingerprint=fingerprint,
    )


def _safety() -> dict[str, Any]:
    return {
        "mode": "offline_dry_run",
        "provider_calls": False,
        "credential_reads": False,
        "network_calls": False,
        "database_writes": False,
        "orders_payments_bookings": False,
        "publishing": False,
        "guaranteed_profit_claim": False,
        "client_safe_export": "TrustOS_allowlisted_projection_only",
    }


def build_consulting_economics_report(value: ConsultingEconomicsRequest | Mapping[str, Any]) -> ConsultingEconomicsReport:
    """Build a deterministic offline report; invalid data returns ``blocked``."""
    request: ConsultingEconomicsRequest | None = None
    try:
        request = value if isinstance(value, ConsultingEconomicsRequest) else ConsultingEconomicsRequest.from_mapping(value)
        request = replace(
            request,
            service_id=_safe_text(request.service_id, "service id"),
            offering_name=_safe_text(request.offering_name, "offering name"),
            service_model=_safe_text(request.service_model, "service model"),
            currency=_safe_text(request.currency, "currency").upper(),
        )
        if request.service_model not in SERVICE_MODELS:
            raise ConsultingEconomicsInputError("unsupported service model")
        if request.evidence_mode not in EVIDENCE_MODES:
            raise ConsultingEconomicsInputError("live evidence mode is not supported")
        evidence_ref = _evidence_ref(request)
        results = tuple(_scenario(request, scenario, evidence_ref) for scenario in SCENARIOS)
        base = next(item for item in results if item.name == "base")
        blockers = tuple(sorted(set(base.blockers)))
        required = tuple(sorted(set(base.missing_evidence)))
        body = {
            "schema": CONSULTING_ECONOMICS_SCHEMA,
            "service_id": request.service_id,
            "offering_name": request.offering_name,
            "service_model": request.service_model,
            "currency": request.currency.upper(),
            "evidence_class": request.evidence_mode,
            "recommendation": base.recommendation,
            "scenarios": [item.to_dict() for item in results],
            "blockers": list(blockers),
            "evidence_required": list(required),
            "next_action": base.next_action,
            "safety": _safety(),
        }
        fingerprint = hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
        return ConsultingEconomicsReport(
            schema=body["schema"],
            service_id=body["service_id"],
            offering_name=body["offering_name"],
            service_model=body["service_model"],
            currency=body["currency"],
            evidence_class=body["evidence_class"],
            recommendation=body["recommendation"],
            scenarios=results,
            blockers=tuple(body["blockers"]),
            evidence_required=tuple(body["evidence_required"]),
            next_action=body["next_action"],
            safety=body["safety"],
            fingerprint=fingerprint,
        )
    except (ConsultingEconomicsInputError, EconomicsError, CurrencyMismatchError) as error:
        return _blocked_report(request, str(error))


def render_consulting_economics_markdown(report: ConsultingEconomicsReport) -> str:
    """Render a stable operator report without timestamps or raw inputs."""
    lines = [
        "# Consulting Economics Report",
        "",
        "> **OFFLINE DRY RUN** — no providers, credentials, orders, payments, bookings, or publishing were used.",
        "",
        f"- Service: `{report.service_id}`",
        f"- Offering: {report.offering_name}",
        f"- Model: `{report.service_model}`",
        f"- Recommendation: **{report.recommendation}**",
        f"- Evidence class: `{report.evidence_class}`",
        f"- Fingerprint: `{report.fingerprint}`",
        "",
        "## Scenarios",
        "",
        "| Scenario | Recommendation | Evidence | Contribution | Margin | Next action |",
        "|---|---|---|---:|---:|---|",
    ]
    for scenario in report.scenarios:
        economics = scenario.economics
        contribution = str(economics.contribution.amount) if economics and economics.contribution else "unavailable"
        margin = str(economics.contribution_margin) if economics and economics.contribution_margin is not None else "unavailable"
        lines.append(f"| {scenario.name} | {scenario.recommendation} | {scenario.evidence_status} | {contribution} | {margin} | {scenario.next_action} |")
    lines.extend(["", "## Evidence and Safety", "", f"- Required evidence: {', '.join(report.evidence_required) or 'none'}", f"- Next action: {report.next_action}", "- Client output is available only through the existing TrustOS allowlist.", ""])
    return "\n".join(lines)


def export_client_safe_report(
    report: ConsultingEconomicsReport,
    *,
    workspace: ClientWorkspace,
    registry: WorkspaceRegistry,
) -> ClientWorkspaceEvidenceExport:
    """Delegate client-safe export to TrustOS; never register or create a workspace."""
    return export_client_evidence(
        workspace=workspace,
        registry=registry,
        provenance="manual://consulting-economics/report",
        evidence_state="present",
        payload=report.client_safe_payload(workspace.workspace_id),
    )


__all__ = [
    "CONSULTING_ECONOMICS_SCHEMA",
    "SCENARIOS",
    "SERVICE_MODELS",
    "ConsultingEconomicsInputError",
    "ConsultingEconomicsReport",
    "ConsultingEconomicsRequest",
    "ScenarioResult",
    "build_consulting_economics_report",
    "export_client_safe_report",
    "render_consulting_economics_markdown",
]
