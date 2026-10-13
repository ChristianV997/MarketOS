"""Client-safe projection for the canonical product-opportunity synthesis.

This module is a route-neutral adapter.  Discovery and opportunity synthesis
remain the authorities for validation, economics, and ranking; TrustOS remains
the only client-export boundary.  The adapter only selects client-visible
metadata and never accepts a workspace identifier as authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from backend.commerce.owner_opportunity_read_model import (
    OwnerOpportunityReadModelError,
    build_owner_opportunity_read_model,
)
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry
from evaluation.trustos.client_workspace_isolation import (
    ClientWorkspaceEvidenceExport,
    ClientWorkspaceExportError,
    export_client_evidence,
)


REPORT_VERSION = "client-safe-product-opportunity-report-v1"
REPORT_PROVENANCE = "derived://client-safe-product-opportunity"
MAX_REPORT_BYTES = 64_000

_PILLAR_AREAS = {
    "marketplace": frozenset({"market", "marketplace", "demand"}),
    "supplier": frozenset({"supplier", "supply"}),
    "consumer_attention": frozenset({"consumer", "attention", "consumer_attention"}),
}
_SECRET_SHAPED_VALUE = re.compile(r"(?i)(?:sk[_-](?:live|test|proj)[_-][A-Za-z0-9_-]{4,})")
_COVERAGE_FIELDS = (
    "status",
    "evidence_mode",
    "evidence_classes",
    "freshness_statuses",
    "missing",
    "incomplete",
    "stale",
    "conflicting",
    "fixture_only",
    "manual_imported",
    "evidence_count",
    "evidence_refs",
)
_MAX_COVERAGE_REFERENCES = 32
_MAX_COVERAGE_REFERENCE_BYTES = 512


class ClientSafeProductOpportunityReportError(ValueError):
    """Stable, non-reflective projection error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _reject_secret_shaped_values(value: Any) -> None:
    """Protect the report itself in addition to the canonical export scan."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            _reject_secret_shaped_values(key)
            _reject_secret_shaped_values(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject_secret_shaped_values(child)
    elif isinstance(value, str) and _SECRET_SHAPED_VALUE.search(value):
        raise ClientSafeProductOpportunityReportError("sensitive_value_rejected")


def _evidence_view(item: Mapping[str, Any]) -> dict[str, Any]:
    """Keep evidence references and status, never evidence payloads."""
    return {
        "evidence_id": item.get("evidence_id"),
        "area": item.get("area"),
        "source_type": item.get("source_type"),
        "source_ref": item.get("source_ref"),
        "evidence_class": item.get("evidence_class"),
        "evidence_age": item.get("freshness", "unknown"),
        "status": item.get("status"),
        "conflicting": bool(item.get("conflicting", False)),
    }


def _bounded_coverage_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.isprintable():
        return None
    if len(value.encode("utf-8")) > _MAX_COVERAGE_REFERENCE_BYTES:
        return None
    return value


def _bounded_coverage_strings(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    values = {
        text
        for item in value
        if (text := _bounded_coverage_text(item)) is not None
    }
    return sorted(values)


def _coverage_reference_view(value: Any) -> dict[str, Any] | None:
    """Project one read-model reference without copying arbitrary metadata."""
    if not isinstance(value, Mapping):
        return None
    projected: dict[str, Any] = {}
    for field in ("evidence_id", "source_type", "source_ref", "status"):
        text = _bounded_coverage_text(value.get(field))
        if text is not None:
            projected[field] = text
    for field in ("evidence_class", "freshness"):
        text = _bounded_coverage_text(value.get(field))
        projected[field] = text if text is not None else "unknown"
    projected["conflicting"] = value.get("conflicting") is True
    if not any(field in projected for field in ("evidence_id", "source_type", "source_ref")):
        return None
    return projected


def _evidence_coverage_view(value: Any) -> dict[str, dict[str, Any]]:
    """Pass through only the bounded, client-safe read-model coverage fields."""
    if not isinstance(value, Mapping):
        return {}
    projected: dict[str, dict[str, Any]] = {}
    for pillar in _PILLAR_AREAS:
        raw = value.get(pillar)
        if not isinstance(raw, Mapping):
            continue
        item: dict[str, Any] = {}
        for field in _COVERAGE_FIELDS:
            if field not in raw:
                continue
            raw_value = raw[field]
            if field in {"status", "evidence_mode"}:
                item[field] = _bounded_coverage_text(raw_value) or "unknown"
            elif field in {"evidence_classes", "freshness_statuses"}:
                item[field] = _bounded_coverage_strings(raw_value)
            elif field in {"missing", "incomplete", "stale", "conflicting", "fixture_only", "manual_imported"}:
                item[field] = raw_value is True
            elif field == "evidence_count":
                item[field] = raw_value if isinstance(raw_value, int) and not isinstance(raw_value, bool) and raw_value >= 0 else 0
            elif field == "evidence_refs":
                raw_refs = raw_value if isinstance(raw_value, (list, tuple)) else ()
                item[field] = [
                    reference
                    for raw_reference in raw_refs[:_MAX_COVERAGE_REFERENCES]
                    if (reference := _coverage_reference_view(raw_reference)) is not None
                ]
                item["evidence_refs_truncated"] = len(raw_refs) > _MAX_COVERAGE_REFERENCES
        projected[pillar] = item
    return projected


def _currency_boundaries(economics: Mapping[str, Any]) -> dict[str, Any]:
    currencies: set[str] = set()
    declared = economics.get("currency")
    if isinstance(declared, str) and declared:
        currencies.add(declared)
    for value in economics.get("assumptions", {}).values() if isinstance(economics.get("assumptions"), Mapping) else ():
        if isinstance(value, Mapping) and isinstance(value.get("currency"), str) and value["currency"]:
            currencies.add(value["currency"])
    scenarios = economics.get("scenarios", {})
    if isinstance(scenarios, Mapping):
        for scenario in scenarios.values():
            if isinstance(scenario, Mapping) and isinstance(scenario.get("currency"), str) and scenario["currency"]:
                currencies.add(scenario["currency"])
    return {
        "currencies": sorted(currencies),
        "mixed_currency": len(currencies) > 1,
        "conversion_applied": False,
    }


def _candidate_view(candidate: Mapping[str, Any]) -> dict[str, Any]:
    evidence = [_evidence_view(item) for item in candidate.get("evidence", ()) if isinstance(item, Mapping)]
    by_pillar = {
        pillar: [item for item in evidence if item["area"] in areas]
        for pillar, areas in _PILLAR_AREAS.items()
    }
    economics = candidate.get("economics", {})
    if not isinstance(economics, Mapping):
        economics = {}
    missing = {str(item) for item in economics.get("missing_inputs", ()) if isinstance(item, str)}
    assumptions = economics.get("assumptions", {})
    if not isinstance(assumptions, Mapping):
        assumptions = {}
    conflicts = sorted(
        {
            str(item["area"])
            for item in evidence
            if item["conflicting"]
        }
    )
    unknowns = sorted(missing | {item["area"] for item in evidence if item["evidence_age"] in {"stale", "future", "unknown"}})
    return {
        "candidate_id": candidate.get("candidate_id"),
        "name": candidate.get("name"),
        "offering_kind": candidate.get("offering_kind"),
        "category": candidate.get("category"),
        "evidence_by_pillar": by_pillar,
        "evidence_coverage": _evidence_coverage_view(candidate.get("evidence_coverage")),
        "evidence_classes": list(candidate.get("evidence_classes", ())),
        "economics": {
            "status": economics.get("status", "unknown"),
            "missing_inputs": sorted(missing),
            "currency_boundaries": _currency_boundaries(economics),
            "scenarios": dict(economics.get("scenarios", {})) if isinstance(economics.get("scenarios"), Mapping) else {},
            "assumptions": {str(key): value for key, value in sorted(assumptions.items(), key=lambda item: str(item[0]))},
        },
        "conflicts": conflicts,
        "unknowns": unknowns,
        "evidence_gaps": list(candidate.get("evidence_gaps", ())),
        "blockers": list(candidate.get("blockers", ())),
        "ranking": dict(candidate.get("ranking", {})),
        "recommendation": candidate.get("recommendation"),
        "readiness": candidate.get("readiness"),
        "next_action": candidate.get("next_action"),
    }


def _safe_export_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    """Map the report into TrustOS' existing metadata-only export shape."""
    evidence_required = []
    for candidate in report["candidates"]:
        evidence_required.append(
            {
                "candidate_id": candidate["candidate_id"],
                "evidence_by_pillar": candidate["evidence_by_pillar"],
                "evidence_coverage": candidate["evidence_coverage"],
                "evidence_classes": candidate["evidence_classes"],
                "economics": candidate["economics"],
                "conflicts": candidate["conflicts"],
                "unknowns": candidate["unknowns"],
            }
        )
    return {
        "workspace_id": report["workspace_id"],
        "status": "requires_review",
        "blockers": list(report["blockers"]),
        "evidence_required": evidence_required,
        "approvals_required": ["human evidence review"],
        "next_actions": [report["next_best_action"]],
    }


@dataclass(frozen=True)
class ClientSafeProductOpportunityReport:
    """Deterministic client-safe report plus its canonical TrustOS envelope."""

    report: Mapping[str, Any]
    export: ClientWorkspaceEvidenceExport
    markdown: str

    def to_dict(self) -> dict[str, Any]:
        result = dict(self.report)
        result["client_export"] = self.export.to_dict()
        return result


def render_markdown(report: ClientSafeProductOpportunityReport | Mapping[str, Any]) -> str:
    data = report.report if isinstance(report, ClientSafeProductOpportunityReport) else report
    lines = [
        "# Client-Safe Product Opportunity Report",
        "",
        f"- Schema: `{data['schema']}`",
        f"- Workspace: `{data['workspace_id']}`",
        f"- Mode: `{data['mode']}`",
        f"- Status: `{data['status']}`",
        f"- Fingerprint: `{data['fingerprint']}`",
        "",
        "This is offline planning evidence, not supplier proof, launch authorization, spend approval, or live validation.",
        "",
        "## Candidates",
        "",
        "| Candidate | Kind | Readiness | Recommendation | Currency boundary |",
        "|---|---|---|---|---|",
    ]
    for candidate in data["candidates"]:
        currencies = ", ".join(candidate["economics"]["currency_boundaries"]["currencies"]) or "unknown"
        lines.append(
            f"| `{candidate['candidate_id']}` | {candidate['offering_kind']} | {candidate['readiness']} | {candidate['recommendation']} | {currencies} |")
        lines.append("")
        lines.append("  Evidence: " + ", ".join(
            f"{pillar}={len(refs)}" for pillar, refs in candidate["evidence_by_pillar"].items()
        ))
        lines.append("  Unknowns: " + (", ".join(candidate["unknowns"]) or "none recorded"))
        lines.append("  Conflicts: " + (", ".join(candidate["conflicts"]) or "none recorded"))
    lines.extend(
        [
            "",
            "## Blockers and Next Action",
            "",
            "- Blockers: " + (", ".join(data["blockers"]) or "none recorded"),
            f"- Next action: {data['next_best_action']}",
            "",
        ]
    )
    rendered = "\n".join(lines)
    if len(rendered.encode("utf-8")) > MAX_REPORT_BYTES:
        raise ClientSafeProductOpportunityReportError("output_size_exceeded")
    return rendered


def build_client_safe_product_opportunity_report(
    mode: str,
    payload: Mapping[str, Any],
    *,
    workspace: ClientWorkspace,
    registry: WorkspaceRegistry,
) -> ClientSafeProductOpportunityReport:
    """Build and export a client-safe view from a registered workspace.

    The workspace object is an already-resolved server-side identity.  A raw
    payload workspace selector is only checked by the canonical discovery
    service for consistency and never selects the workspace.
    """
    if not isinstance(workspace, ClientWorkspace):
        raise ClientSafeProductOpportunityReportError("invalid_workspace")
    if not isinstance(registry, WorkspaceRegistry):
        raise ClientSafeProductOpportunityReportError("invalid_workspace_registry")
    try:
        read_model = build_owner_opportunity_read_model(
            mode,
            payload,
            workspace=workspace,
            registry=registry,
        ).to_dict()
    except OwnerOpportunityReadModelError as exc:
        raise ClientSafeProductOpportunityReportError(exc.code) from None

    candidates = tuple(_candidate_view(item) for item in read_model["opportunities"])
    report_body = {
        "schema": REPORT_VERSION,
        "workspace_id": workspace.workspace_id,
        "run_id": read_model["run_id"],
        "mode": read_model["mode"],
        "status": read_model["status"],
        "candidate_count": read_model["candidate_count"],
        "ranked_candidate_ids": list(read_model["ranked_candidate_ids"]),
        "candidates": list(candidates),
        "blockers": list(read_model["blockers"]),
        "next_best_action": read_model["next_best_action"],
        "authorities": {
            "synthesis": "evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis",
            "discovery": "services.opportunity_discovery.service.run_discovery",
            "client_export": "evaluation.trustos.client_workspace_isolation.export_client_evidence",
        },
        "safety": dict(read_model["safety"]),
    }
    report_body["fingerprint"] = _fingerprint(report_body)
    _reject_secret_shaped_values(report_body)
    if len(_canonical(report_body).encode("utf-8")) > MAX_REPORT_BYTES:
        raise ClientSafeProductOpportunityReportError("output_size_exceeded")
    try:
        exported = export_client_evidence(
            workspace=workspace,
            registry=registry,
            provenance=f"{REPORT_PROVENANCE}/{read_model['run_id']}",
            evidence_state="requires_review",
            payload=_safe_export_payload(report_body),
        )
    except ClientWorkspaceExportError as exc:
        raise ClientSafeProductOpportunityReportError(exc.code) from None
    except Exception:
        raise ClientSafeProductOpportunityReportError("export_rejected") from None
    markdown = render_markdown(report_body)
    return ClientSafeProductOpportunityReport(report_body, exported, markdown)


__all__ = [
    "ClientSafeProductOpportunityReport",
    "ClientSafeProductOpportunityReportError",
    "MAX_REPORT_BYTES",
    "REPORT_VERSION",
    "build_client_safe_product_opportunity_report",
    "render_markdown",
]
