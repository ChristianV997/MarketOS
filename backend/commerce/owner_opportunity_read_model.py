"""Read-only owner opportunity review projection.

This module is a boundary adapter for the existing offline discovery service.
It deliberately does not rank, calculate economics, authorize actions, or
wire authentication.  The integration owner can expose this contract through
an authenticated read route without leaking the raw discovery payload.  The
input payload is the only snapshot source; durable run lookup is not available.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from backend.identity.workspaces import WorkspaceAccess
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry
from services.opportunity_discovery.service import (
    DISCOVERY_MODES,
    DiscoveryRun,
    EVIDENCE_CLASSES,
    OpportunityCandidate,
    OpportunityDecision,
    OpportunityDiscoveryError,
    run_discovery,
)

READ_MODEL_VERSION = "owner-opportunity-read-model-v1"
SYNTHESIS_AUTHORITY = "evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis"
MAX_READ_MODEL_BYTES = 128 * 1024
SNAPSHOT_RESOLUTION = {
    "source": "input_payload",
    "persisted": False,
    "resolver": "unavailable",
}
_INTERNAL_VALUE = re.compile(r"(?:system\s+prompt|internal\s+prompt|raw\s+payload|source\s+code|\bformula\b)", re.IGNORECASE)
_EVIDENCE_MODES = frozenset(
    {
        "live_readonly",
        "public_live",
        "authenticated_live",
        "manual_import",
        "fixture_demo",
        "fixture",
    }
)
_FRESHNESS_STATUSES = frozenset({"current", "stale", "future", "unknown"})
_PILLARS = (
    ("marketplace", "marketplace", frozenset({"competition", "demand", "marketplace", "price"})),
    ("supplier", "supplier", frozenset({"economics", "supplier", "supply"})),
    ("consumer_attention", "consumer", frozenset({"attention", "consumer", "creative", "engagement"})),
)

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


def _report_evidence(report: Any, candidate_id: str) -> tuple[Mapping[str, Any], ...]:
    """Read only bounded evidence metadata from a supplied report row."""
    if not isinstance(report, Mapping):
        return ()
    candidates = report.get("candidates")
    if not isinstance(candidates, list):
        return ()
    row = next(
        (
            item
            for item in candidates
            if isinstance(item, Mapping) and item.get("candidate_id") == candidate_id
        ),
        None,
    )
    if not isinstance(row, Mapping):
        return ()
    entries: list[Mapping[str, Any]] = []
    for field in ("evidence", "offers"):
        values = row.get(field)
        if isinstance(values, list):
            entries.extend(item for item in values if isinstance(item, Mapping))
    return tuple(entries)


def _report_has_candidate(report: Any, candidate_id: str) -> bool:
    if not isinstance(report, Mapping) or not isinstance(report.get("candidates"), list):
        return False
    return any(
        isinstance(item, Mapping) and item.get("candidate_id") == candidate_id
        for item in report["candidates"]
    )


def _reference_text(value: Any) -> str | None:
    """Keep only bounded, printable reference metadata from a report mapping."""
    if not isinstance(value, str) or not value.isprintable():
        return None
    if len(value.encode("utf-8")) > 512:
        return None
    return value


def _allowed_reference_value(value: Any, allowed: frozenset[str]) -> str | None:
    if isinstance(value, str) and value in allowed:
        return value
    return None


def _evidence_reference(item: Any) -> dict[str, Any] | None:
    """Project an evidence reference without exposing raw report internals."""
    if isinstance(item, Mapping):
        value = item.get
    else:
        value = lambda key: getattr(item, key, None)
    evidence_id = _reference_text(value("evidence_id"))
    source_type = _reference_text(value("source_type"))
    source_ref = _reference_text(value("source_ref"))
    if evidence_id is None and source_type is None and source_ref is None:
        return None
    status = _reference_text(value("status"))
    return {
        "evidence_id": evidence_id,
        "source_type": source_type,
        "source_ref": source_ref,
        "evidence_class": _allowed_reference_value(value("evidence_class"), EVIDENCE_CLASSES)
        or "unknown",
        "freshness": _allowed_reference_value(value("freshness"), _FRESHNESS_STATUSES)
        or "unknown",
        "status": status,
        "conflicting": value("conflicting") is True,
    }


def _evidence_coverage(candidate: OpportunityCandidate) -> dict[str, dict[str, Any]]:
    """Project pillar coverage without upgrading evidence or inventing freshness."""
    coverage: dict[str, dict[str, Any]] = {}
    for pillar, report_key, areas in _PILLARS:
        report = candidate.reports.get(report_key)
        report_entries = _report_evidence(report, candidate.candidate_id)
        candidate_entries = tuple(item for item in candidate.evidence if item.area in areas)
        entries = (*candidate_entries, *report_entries)
        evidence_refs: list[dict[str, Any]] = []
        seen_references: set[str] = set()
        for entry in entries:
            reference = _evidence_reference(entry)
            if reference is None:
                continue
            reference_key = _canonical(reference)
            if reference_key in seen_references:
                continue
            seen_references.add(reference_key)
            evidence_refs.append(reference)
        raw_mode = (
            _allowed_reference_value(report.get("evidence_mode"), _EVIDENCE_MODES)
            if isinstance(report, Mapping)
            else None
        )
        modes = {
            value
            for value in (
                raw_mode,
                *(
                    _allowed_reference_value(item.get("evidence_mode"), _EVIDENCE_MODES)
                    for item in report_entries
                ),
            )
            if value is not None
        }
        classes = {
            value
            for value in (
                *(
                    _allowed_reference_value(item.evidence_class, EVIDENCE_CLASSES)
                    for item in candidate_entries
                ),
                *(
                    _allowed_reference_value(item.get("evidence_class"), EVIDENCE_CLASSES)
                    for item in report_entries
                ),
            )
            if value is not None
        }
        freshness = {
            value
            for value in (
                *(
                    _allowed_reference_value(item.freshness, _FRESHNESS_STATUSES)
                    for item in candidate_entries
                ),
                *(
                    _allowed_reference_value(item.get("freshness"), _FRESHNESS_STATUSES)
                    for item in report_entries
                ),
            )
            if value is not None
        }
        conflicting = any(
            item.conflicting is True
            for item in candidate_entries
        ) or any(item.get("conflicting") is True for item in report_entries)
        supplied = bool(
            candidate_entries
            or report_entries
            or _report_has_candidate(report, candidate.candidate_id)
        )
        incomplete = supplied and not evidence_refs
        if not supplied:
            evidence_mode = "missing"
        elif raw_mode in _EVIDENCE_MODES:
            evidence_mode = raw_mode
        elif modes:
            evidence_mode = sorted(modes)[0]
        else:
            evidence_mode = "unknown" if supplied else "missing"
        fixture_only = supplied and (
            (classes and classes <= {"fixture"})
            or (not classes and modes and modes <= {"fixture", "fixture_demo"})
        )
        coverage[pillar] = {
            "status": "supplied" if supplied else "missing",
            "evidence_mode": evidence_mode,
            "evidence_classes": sorted(classes),
            "freshness_statuses": sorted(freshness) or ["unknown"],
            "missing": not supplied,
            "incomplete": incomplete,
            "stale": "stale" in freshness,
            "conflicting": conflicting,
            "fixture_only": fixture_only,
            "manual_imported": "manual" in classes or "manual_import" in modes,
            "evidence_count": len(evidence_refs),
            "evidence_refs": evidence_refs,
        }
    return coverage


def _next_research_pillar(coverage: Mapping[str, Mapping[str, Any]]) -> str | None:
    """Choose one stable research target; this never starts a fetch."""
    for state in ("missing", "incomplete", "conflicting", "stale"):
        for pillar in ("supplier", "marketplace", "consumer_attention"):
            if coverage.get(pillar, {}).get(state) is True:
                return pillar
    return None


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
    coverage = _evidence_coverage(candidate)
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
        "evidence_coverage": coverage,
        "economics": _economics_view(candidate, decision),
        "client_safe_export_status": decision.trustos_export.get("status", "unavailable"),
        "next_action": decision.synthesis.get("next_best_action") or decision.experiment.question,
        "next_research_step": decision.experiment.question,
        "next_research_pillar": _next_research_pillar(coverage),
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


def _ordered_candidates(run: DiscoveryRun) -> tuple[OpportunityCandidate, ...]:
    """Put ranked candidates first, then retain deterministic unranked items."""
    by_id = {candidate.candidate_id: candidate for candidate in run.candidates}
    ranked = tuple(
        by_id[candidate_id]
        for candidate_id in run.ranked_candidate_ids
        if candidate_id in by_id
    )
    ranked_ids = {candidate.candidate_id for candidate in ranked}
    remainder = tuple(
        candidate
        for candidate in run.candidates
        if candidate.candidate_id not in ranked_ids
    )
    return ranked + remainder


def build_owner_opportunity_read_model(
    mode: str,
    payload: Mapping[str, Any],
    *,
    workspace: ClientWorkspace | WorkspaceAccess | None = None,
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
    if workspace is not None and not isinstance(workspace, (ClientWorkspace, WorkspaceAccess)):
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
        for candidate in _ordered_candidates(run)
        if candidate.candidate_id in decisions
    )
    top_opportunity = opportunities[0] if opportunities else None
    next_research_step = (
        top_opportunity.get("next_research_step")
        if top_opportunity is not None
        else run.next_best_action
    )
    next_research_pillar = (
        top_opportunity.get("next_research_pillar")
        if top_opportunity is not None
        else None
    )
    top_coverage = (
        top_opportunity.get("evidence_coverage", {})
        if top_opportunity is not None
        else {}
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
        "next_research_step": next_research_step,
        "next_research_pillar": next_research_pillar,
        "evidence_coverage": top_coverage,
        "workspace_id": workspace.workspace_id if workspace is not None else None,
        "workspace_binding": "injected" if workspace is not None else "not_provided",
        "snapshot_resolution": dict(SNAPSHOT_RESOLUTION),
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
        next_research_step=str(safe_body["next_research_step"]),
        next_research_pillar=safe_body["next_research_pillar"],
        evidence_coverage=safe_body["evidence_coverage"],
        workspace_id=safe_body["workspace_id"],
        workspace_binding=safe_body["workspace_binding"],
        snapshot_resolution=safe_body["snapshot_resolution"],
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
    next_research_step: str
    next_research_pillar: str | None
    evidence_coverage: Mapping[str, Any]
    workspace_id: str | None
    workspace_binding: str
    snapshot_resolution: Mapping[str, Any]
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
            "next_research_step": self.next_research_step,
            "next_research_pillar": self.next_research_pillar,
            "evidence_coverage": dict(self.evidence_coverage),
            "workspace_id": self.workspace_id,
            "workspace_binding": self.workspace_binding,
            "snapshot_resolution": dict(self.snapshot_resolution),
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
    "SNAPSHOT_RESOLUTION",
    "SYNTHESIS_AUTHORITY",
    "build_owner_opportunity_read_model",
]
