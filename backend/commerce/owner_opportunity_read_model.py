"""Read-only owner opportunity review projection.

This module is a boundary adapter for the existing offline discovery service.
It deliberately does not rank, calculate economics, authorize actions, or
wire authentication.  The integration owner can expose this contract through
an authenticated read route without leaking the raw discovery payload.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry
from services.opportunity_discovery.service import (
    DISCOVERY_MODES,
    DiscoveryRun,
    OpportunityCandidate,
    OpportunityDecision,
    OpportunityDiscoveryError,
    run_discovery,
)

READ_MODEL_VERSION = "owner-opportunity-read-model-v1"
SYNTHESIS_AUTHORITY = "evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis"
MAX_READ_MODEL_BYTES = 128 * 1024
_INTERNAL_VALUE = re.compile(r"(?:system\s+prompt|internal\s+prompt|raw\s+payload|source\s+code|\bformula\b)", re.IGNORECASE)

_ECONOMIC_OUTPUT_FIELDS = frozenset(
    {
        "scenario",
        "status",
        "currency",
        "evidence_state",
        "missing_inputs",
        "service_fee",
        "ad_spend",
        "roas_before",
        "roas_after",
        "delivery_hours",
        "capacity_hours",
        "contribution_margin",
        "contribution_margin_after_cac",
        "break_even_roas",
        "target_roas",
        "net_sales",
        "product_cost",
        "supplier_shipping",
        "domestic_shipping",
        "international_shipping",
        "delivery_cost",
        "tooling_cost",
        "pass_through_cost",
        "revision_reserve",
        "cac",
        "cac_before",
        "cac_after",
        "contribution_before_cac",
        "contribution_after_cac",
        "cash_required_per_order",
        "minimum_viable_price",
        "break_even_client_count",
        "maximum_concurrent_clients",
        "explicit_zero_inputs",
    }
)

_ASSUMPTION_FIELDS = frozenset(
    {
        "supplier_shipping",
        "domestic_shipping",
        "international_shipping",
        "brokerage_fee",
        "payment_fee_rate",
        "payment_fee_fixed",
        "platform_fee_rate",
        "platform_fee_fixed",
        "marketplace_fee_rate",
        "affiliate_fee_rate",
        "tax_rate",
        "duty_rate",
        "return_rate",
        "defect_rate",
        "warranty_rate",
        "support_reserve_rate",
        "chargeback_rate",
        "fx_reserve_rate",
        "discount_rate",
        "conversion_rate",
        "ad_spend",
        "cac",
        "refund_lag_days",
        "target_margin_rate",
    }
)


class OwnerOpportunityReadModelError(ValueError):
    """Stable contract error without reflecting caller-controlled values."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _safe_value(value: Any) -> Any:
    """Return bounded JSON data for explicitly allowlisted projection fields."""
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise OwnerOpportunityReadModelError("non_finite_projection_value")
        return value
    if isinstance(value, str):
        if (
            not value.isprintable()
            or len(value.encode("utf-8")) > 512
            or _INTERNAL_VALUE.search(value) is not None
        ):
            raise OwnerOpportunityReadModelError("invalid_projection_text")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise OwnerOpportunityReadModelError("invalid_projection_field")
        return {
            key: _safe_value(value[key])
            for key in sorted(value, key=str)
        }
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    raise OwnerOpportunityReadModelError("unsupported_projection_value")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _evidence_view(candidate: OpportunityCandidate) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "evidence_id": item.evidence_id,
            "area": item.area,
            "status": item.status,
            "evidence_class": item.evidence_class,
            "source_type": item.source_type,
            "source_ref": item.source_ref,
            "freshness": item.freshness,
            "conflicting": item.conflicting,
            "notes": list(item.notes),
        }
        for item in candidate.evidence
    )


def _assumptions_view(candidate: OpportunityCandidate) -> dict[str, Any]:
    raw = candidate.economics.get("assumptions", {})
    if not isinstance(raw, Mapping):
        return {}
    return {
        key: _safe_value(raw[key])
        for key in sorted(raw)
        if key in _ASSUMPTION_FIELDS
    }


def _scenario_view(scenario: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _safe_value(scenario[key])
        for key in sorted(scenario)
        if key in _ECONOMIC_OUTPUT_FIELDS
    }


def _economics_view(candidate: OpportunityCandidate, decision: OpportunityDecision) -> dict[str, Any]:
    scenarios = {
        str(name): _scenario_view(values)
        for name, values in sorted(decision.scenarios.items(), key=lambda item: str(item[0]))
        if isinstance(values, Mapping)
    }
    missing = set(str(item) for item in decision.metrics.get("economics_missing_inputs", ()))
    for values in scenarios.values():
        missing.update(str(item) for item in values.get("missing_inputs", ()))
    return {
        "status": str(decision.metrics.get("economics_status", "unknown")),
        "currency": candidate.economics.get("currency") or candidate.geography.get("currency"),
        "missing_inputs": sorted(missing),
        "assumptions": _assumptions_view(candidate),
        "scenarios": scenarios,
    }


def _opportunity_view(candidate: OpportunityCandidate, decision: OpportunityDecision) -> dict[str, Any]:
    synthesis_score = decision.metrics.get("synthesis_score")
    synthesis_confidence = decision.synthesis.get("evidence_confidence")
    return {
        "candidate_id": candidate.candidate_id,
        "name": candidate.name,
        "offering_kind": candidate.offering_kind,
        "category": candidate.category,
        "evidence": list(_evidence_view(candidate)),
        "evidence_classes": list(decision.evidence_classes),
        "evidence_confidence": decision.metrics.get("evidence_confidence"),
        "synthesis_confidence": synthesis_confidence,
        "confidence_grade": decision.synthesis.get("confidence_grade", "unknown"),
        "ranking": {
            "score": synthesis_score,
            "authority": SYNTHESIS_AUTHORITY,
        },
        "recommendation": decision.recommendation,
        "readiness": decision.readiness,
        "blockers": list(decision.blockers),
        "evidence_gaps": list(decision.evidence_gaps),
        "economics": _economics_view(candidate, decision),
        "client_safe_export_status": decision.trustos_export.get("status", "unavailable"),
        "next_action": decision.synthesis.get("next_best_action") or decision.experiment.question,
    }


def _safety_view(run: DiscoveryRun) -> dict[str, Any]:
    return {
        "read_only": True,
        "network_calls": False,
        "provider_calls": False,
        "credentials_present": False,
        "orders_created": False,
        "payments_created": False,
        "ads_launched": False,
        "publishing": False,
        "database_writes": False,
        "launch_authorized": False,
        "execution_classification": run.execution_classification,
    }


def build_owner_opportunity_read_model(
    mode: str,
    payload: Mapping[str, Any],
    *,
    workspace: ClientWorkspace | None = None,
    registry: WorkspaceRegistry | None = None,
) -> "OwnerOpportunityReadModel":
    """Build a deterministic owner projection from the canonical discovery run.

    ``workspace`` and ``registry`` are dependency-injected authorities for the
    integration owner.  This function never creates or resolves a workspace,
    and a route must not treat a payload workspace string as authentication.
    """
    if mode not in DISCOVERY_MODES:
        raise OwnerOpportunityReadModelError("invalid_mode")
    if not isinstance(payload, Mapping):
        raise OwnerOpportunityReadModelError("payload_must_be_object")
    if registry is not None and not isinstance(registry, WorkspaceRegistry):
        raise OwnerOpportunityReadModelError("invalid_workspace_registry")
    if workspace is not None and not isinstance(workspace, ClientWorkspace):
        raise OwnerOpportunityReadModelError("invalid_workspace")
    if workspace is not None and payload.get("workspace_id") not in (None, workspace.workspace_id):
        raise OwnerOpportunityReadModelError("workspace_mismatch")
    try:
        run = run_discovery(mode, payload, workspace=workspace, registry=registry)
    except OpportunityDiscoveryError as exc:
        raise OwnerOpportunityReadModelError(exc.code) from None

    decisions = {item.candidate_id: item for item in run.decisions}
    opportunities = tuple(
        _opportunity_view(candidate, decisions[candidate.candidate_id])
        for candidate in run.candidates
        if candidate.candidate_id in decisions
    )
    body = {
        "schema": READ_MODEL_VERSION,
        "run_id": payload.get("run_id", "opportunity-discovery-v1"),
        "mode": run.mode,
        "status": run.status,
        "candidate_count": len(opportunities),
        "ranked_candidate_ids": list(run.ranked_candidate_ids),
        "opportunities": list(opportunities),
        "blockers": list(run.blockers),
        "next_best_action": run.next_best_action,
        "workspace_id": workspace.workspace_id if workspace is not None else None,
        "workspace_binding": "injected" if workspace is not None else "not_provided",
        "authorities": {
            "input_and_evidence_gates": "services.opportunity_discovery.service.run_discovery",
            "economics": "backend.economics.kernel",
            "ranking": SYNTHESIS_AUTHORITY,
            "client_export": "evaluation.trustos.client_workspace_isolation.export_client_evidence",
        },
        "safety": _safety_view(run),
    }
    safe_body = _safe_value(body)
    if len(_canonical(safe_body).encode("utf-8")) > MAX_READ_MODEL_BYTES:
        raise OwnerOpportunityReadModelError("output_size_exceeded")
    return OwnerOpportunityReadModel(
        schema=READ_MODEL_VERSION,
        run_id=str(safe_body["run_id"]),
        mode=run.mode,
        status=run.status,
        candidate_count=len(opportunities),
        ranked_candidate_ids=tuple(run.ranked_candidate_ids),
        opportunities=tuple(safe_body["opportunities"]),
        blockers=tuple(run.blockers),
        next_best_action=run.next_best_action,
        workspace_id=safe_body["workspace_id"],
        workspace_binding=safe_body["workspace_binding"],
        authorities=safe_body["authorities"],
        safety=safe_body["safety"],
        fingerprint=_fingerprint(safe_body),
    )


@dataclass(frozen=True)
class OwnerOpportunityReadModel:
    """Stable, route-neutral JSON contract for owner opportunity review."""

    schema: str
    run_id: str
    mode: str
    status: str
    candidate_count: int
    ranked_candidate_ids: tuple[str, ...]
    opportunities: tuple[Mapping[str, Any], ...]
    blockers: tuple[str, ...]
    next_best_action: str
    workspace_id: str | None
    workspace_binding: str
    authorities: Mapping[str, str]
    safety: Mapping[str, Any]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        body = {
            "schema": self.schema,
            "run_id": self.run_id,
            "mode": self.mode,
            "status": self.status,
            "candidate_count": self.candidate_count,
            "ranked_candidate_ids": list(self.ranked_candidate_ids),
            "opportunities": [dict(item) for item in self.opportunities],
            "blockers": list(self.blockers),
            "next_best_action": self.next_best_action,
            "workspace_id": self.workspace_id,
            "workspace_binding": self.workspace_binding,
            "authorities": dict(self.authorities),
            "safety": dict(self.safety),
        }
        body["fingerprint"] = self.fingerprint
        return body


__all__ = [
    "MAX_READ_MODEL_BYTES",
    "OwnerOpportunityReadModel",
    "OwnerOpportunityReadModelError",
    "READ_MODEL_VERSION",
    "SYNTHESIS_AUTHORITY",
    "build_owner_opportunity_read_model",
]
