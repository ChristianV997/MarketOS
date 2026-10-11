"""Compose one offline proposal draft from the existing consulting services.

The draft is not an approval, a contract, an invoice, or authority to do work.
Client-visible fields leave only through ``export_client_evidence``.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from decimal import Decimal
from typing import Any, Mapping

from backend.organization.report_registry import ReportRegistry
from backend.workspaces.artifact_store import ArtifactStore
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry
from evaluation.commerce.kernel_integration import replay_fingerprint
from evaluation.trustos.client_workspace_isolation import export_client_evidence
from services.consulting_economics import ConsultingEconomicsInputError, build_consulting_economics_report
from services.consulting_engagement import ConsultingEngagementRequest, build_consulting_engagement
from services.consulting_evidence_register import (
    ConsultingEvidenceInputError,
    build_component_report_envelope,
    build_evidence_register,
)
from services.consulting_offers import ConsultingOfferRequest, get_offer_definition, build_consulting_offer_proposal
from services.consulting_offers.proposal import ConsultingOfferCatalogError
from services.consulting_offers.schemas import SchemaValidationError

_CODE = re.compile(r"^[a-z0-9_.:-]{1,80}$")
_SECRET_MARKERS = ("ghp_", "github_pat_", "bearer ", "-----begin", "api_key", "password", "client_secret")


class ConsultingProposalDraftError(ValueError):
    """Stable draft failure that does not echo caller content."""


def _code(value: object, fallback: str) -> str:
    text = str(value or "")
    lowered = text.casefold()
    if any(marker in lowered for marker in _SECRET_MARKERS) or _CODE.fullmatch(text) is None:
        return fallback
    return text


def _money_currency(value: object) -> str | None:
    if isinstance(value, Mapping) and "currency" in value:
        return str(value.get("currency", "")).upper()
    return None


def _economics_currency_conflict(economics: Mapping[str, Any], currency: str) -> bool:
    claimed = str(economics.get("currency", currency)).upper()
    if claimed != currency:
        return True
    for key, value in economics.items():
        found = _money_currency(value)
        if found is not None and found != currency:
            return True
    return False


def _catalog_package_price(offer_ids: tuple[str, ...], currency: str) -> dict[str, str] | None:
    amounts: list[tuple[str, str]] = []
    for offer_id in offer_ids:
        offer = get_offer_definition(offer_id)
        if offer.price_range.currency != currency:
            return None
        amounts.append((str(offer.price_range.minimum), offer.price_range.currency))
    if not amounts:
        return None
    total = sum((Decimal(amount) for amount, _ in amounts), Decimal("0"))
    return {
        "amount": str(total),
        "currency": currency,
        "source": "catalog_band",
        "provenance": "assumed",
        "evidence_state": "assumed",
    }


def _canonical_report_fingerprint(report: Any) -> str:
    payload = report.to_dict() if hasattr(report, "to_dict") else dict(report)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _envelopes(
    reports: list[Mapping[str, Any]],
    workspace_id: str,
    report_registry: ReportRegistry,
    expected_ids: tuple[str, ...],
) -> list[dict[str, Any]]:
    report_ids = [str(report.get("report_id", "")) for report in reports]
    expected_id_set = set(expected_ids)
    if (
        len(reports) != len(expected_ids)
        or len(report_ids) != len(set(report_ids))
        or set(report_ids) != expected_id_set
    ):
        raise ConsultingEvidenceInputError("component report set mismatch")
    envelopes = []
    for report, report_id in zip(reports, report_ids, strict=True):
        canonical = report_registry.get(report_id)
        if canonical is None or canonical.workspace_id != workspace_id:
            raise ConsultingEvidenceInputError("workspace mismatch")
        if str(report.get("workspace_id", "")) != canonical.workspace_id:
            raise ConsultingEvidenceInputError("workspace mismatch")
        if str(report.get("fingerprint", "")) != _canonical_report_fingerprint(canonical):
            raise ConsultingEvidenceInputError("component report fingerprint mismatch")
        if str(report.get("service_name", "")) != canonical.service_name:
            raise ConsultingEvidenceInputError("component report service mismatch")
        status = str(canonical.status)
        if status not in {"completed", "partial", "unavailable", "blocked", "draft", "empty"}:
            status = "partial"
        envelopes.append(build_component_report_envelope(
            report_id=canonical.report_id,
            fingerprint=_canonical_report_fingerprint(canonical),
            service=canonical.service_name,
            workspace_id=workspace_id,
            status=status,
        ))
    return envelopes


def _export_payload(workspace_id: str, status: str, blockers: list[str], evidence_required: list[str]) -> dict[str, Any]:
    return {
        "workspace_id": workspace_id,
        "status": status,
        "blockers": blockers,
        "evidence_required": evidence_required,
        "approvals_required": ["human review before any commitment"],
        "next_actions": ["Review this draft offline. It is not a commitment or authority to perform work."],
    }


def build_consulting_proposal_draft(
    request: Mapping[str, Any],
    *,
    workspace: ClientWorkspace,
    artifact_store: ArtifactStore,
    workspace_registry: WorkspaceRegistry,
    report_registry: ReportRegistry,
) -> dict[str, Any]:
    """Return one deterministic draft. The caller mapping is not mutated."""
    if not isinstance(request, Mapping):
        raise ConsultingProposalDraftError("invalid_request")
    incoming = copy.deepcopy(dict(request))
    currency = str(incoming.get("pricing_currency", "USD")).upper()
    blockers: list[str] = []
    unknowns = [str(item) for item in incoming.get("missing_information") or () if isinstance(item, str)]
    economics_body: dict[str, Any] = {"currency": currency, "recommendation": "not_run", "fingerprint": "", "blockers": []}
    register_body: dict[str, Any] = {"status": "not_run", "fingerprint": "", "gaps": [], "conflicts": [], "report_refs": []}
    engagement_body: dict[str, Any] = {"engagement_id": "", "status": "not_run", "fingerprint": ""}
    offer_body: dict[str, Any] = {"proposal_id": "", "status": "not_run", "fingerprint": "", "inclusions": [], "exclusions": [], "assumptions": []}

    try:
        offer_request = ConsultingOfferRequest.from_mapping(incoming)
        engagement_request = ConsultingEngagementRequest.from_mapping({
            **incoming,
            "selected_deliverables": tuple(incoming.get("selected_deliverables") or ()),
            "optional_upsell_recommendations": tuple(incoming.get("optional_upsell_offer_ids") or ()),
        })
    except (SchemaValidationError, Exception) as exc:
        if isinstance(exc, SchemaValidationError):
            raise ConsultingProposalDraftError(_code(str(exc).replace(" ", "_"), "invalid_request")) from None
        raise ConsultingProposalDraftError("invalid_request") from None

    if offer_request.workspace_id != workspace.workspace_id:
        raise ConsultingProposalDraftError("workspace_identity_mismatch")

    linked = offer_request.linked_component_report_ids
    supplied = incoming.get("component_reports")
    try:
        if isinstance(supplied, list):
            envelopes = _envelopes(
                supplied,
                workspace.workspace_id,
                report_registry,
                linked,
            )
        elif supplied is not None:
            raise ConsultingEvidenceInputError("component reports must be a list")
        else:
            envelopes = []
            for report_id in linked:
                report = report_registry.get(report_id)
                if report is None or report.workspace_id != workspace.workspace_id:
                    raise ConsultingEvidenceInputError("workspace mismatch")
                envelopes.append(build_component_report_envelope(
                    report_id=report.report_id,
                    fingerprint=_canonical_report_fingerprint(report),
                    service=report.service_name,
                    workspace_id=workspace.workspace_id,
                    status=report.status if report.status in {"completed", "partial", "unavailable", "blocked", "draft", "empty"} else "partial",
                ))
        register = build_evidence_register(envelopes, workspace_id=workspace.workspace_id, generated_at="offline-deterministic")
        register_body = {
            "status": register.status,
            "fingerprint": register.fingerprint,
            "gaps": list(register.gaps),
            "conflicts": list(register.conflicts),
            "report_refs": [
                {"report_id": item["report_id"], "service_name": item["service_name"], "status": item["status"]}
                for item in register.report_refs
            ],
        }
        unknowns.extend(register.gaps)
    except ConsultingEvidenceInputError:
        blockers.append("evidence_register_rejected")

    try:
        proposal = build_consulting_offer_proposal(
            offer_request,
            workspace=workspace,
            artifact_store=artifact_store,
            workspace_registry=workspace_registry,
            report_registry=report_registry,
        )
        engagement = build_consulting_engagement(
            engagement_request,
            workspace=workspace,
            artifact_store=artifact_store,
            workspace_registry=workspace_registry,
            report_registry=report_registry,
        )
    except ConsultingOfferCatalogError as exc:
        raise ConsultingProposalDraftError(_code(str(exc), "offer_rejected")) from None
    except Exception as exc:
        code = getattr(exc, "args", ("engagement_rejected",))[0]
        raise ConsultingProposalDraftError(_code(code, "engagement_rejected")) from None

    inclusions = [item for offer in proposal.selected_offers for item in offer.deliverables]
    exclusions = [item for offer in proposal.selected_offers for item in offer.exclusions]
    assumptions = list(dict.fromkeys([*offer_request.assumptions, *proposal.proposal_draft.get("assumptions", [])]))
    offer_body = {
        "proposal_id": proposal.proposal_id,
        "status": proposal.status,
        "fingerprint": proposal.fingerprint,
        "inclusions": inclusions,
        "exclusions": exclusions,
        "assumptions": assumptions,
    }
    engagement_body = {
        "engagement_id": engagement.engagement_id,
        "status": engagement.status,
        "fingerprint": engagement.fingerprint,
    }
    blockers.extend(_code(item, "review_blocker") for item in proposal.blockers)
    blockers.extend(_code(item, "review_blocker") for item in engagement.blockers)

    economics_input = incoming.get("economics") if isinstance(incoming.get("economics"), Mapping) else {}
    economics_copy = copy.deepcopy(dict(economics_input))
    if _economics_currency_conflict(economics_copy, currency) or _catalog_package_price(offer_request.selected_offer_ids, currency) is None:
        blockers.append("currency_mismatch")
        economics_body = {"currency": currency, "recommendation": "blocked", "fingerprint": "", "blockers": ["currency_mismatch"]}
    else:
        band = _catalog_package_price(offer_request.selected_offer_ids, currency)
        payload = {
            "service_id": offer_request.selected_offer_ids[0],
            "offering_name": "Consulting draft",
            "service_model": str(economics_copy.get("service_model") or "project"),
            "currency": currency,
            "evidence_mode": str(economics_copy.get("evidence_mode") or "fixture"),
            "evidence_id": str(economics_copy.get("evidence_id") or "consulting-proposal-draft"),
            "source_ref": str(economics_copy.get("source_ref") or "fixture://consulting-proposal-draft/economics"),
        }
        reserved = {
            "service_id",
            "offering_name",
            "currency",
            "evidence_mode",
            "evidence_id",
            "source_ref",
            "package_price",
            "service_fee",
        }
        payload.update({key: value for key, value in economics_copy.items() if key not in reserved})
        if "package_price" in economics_copy:
            payload["package_price"] = economics_copy["package_price"]
        elif "service_fee" in economics_copy:
            # Keep the economics service's legacy alias when no canonical
            # package_price was supplied. Do not also inject the catalog band:
            # the parser intentionally rejects both names together.
            payload["service_fee"] = economics_copy["service_fee"]
        elif band is not None:
            payload["package_price"] = band
        try:
            report = build_consulting_economics_report(payload)
        except ConsultingEconomicsInputError:
            economics_body = {
                "currency": currency,
                "recommendation": "blocked",
                "fingerprint": "",
                "blockers": ["economics_input_rejected"],
            }
            blockers.append("economics_incomplete")
        else:
            economics_body = {
                "currency": report.currency,
                "recommendation": report.recommendation,
                "fingerprint": report.fingerprint,
                "blockers": [_code(item, "economics_blocker") for item in report.blockers],
            }
            unknowns.extend(report.evidence_required)
            if report.recommendation in {"blocked", "needs_evidence"}:
                blockers.append("economics_incomplete")

    status = "blocked" if blockers else proposal.status
    if status not in {"draft_ready", "needs_evidence", "blocked"}:
        status = "blocked"
    export_evidence = ["catalog evidence review"] if proposal.selected_offers else []
    export_blockers = list(dict.fromkeys(blockers)) or []
    try:
        exported = export_client_evidence(
            workspace=workspace,
            registry=workspace_registry,
            provenance=f"derived://consulting-proposal-draft/{proposal.proposal_id}",
            evidence_state="requires_review",
            payload=_export_payload(workspace.workspace_id, status, export_blockers, export_evidence),
        ).to_dict()
    except Exception:
        exported = {}
        export_blockers = list(dict.fromkeys([*export_blockers, "export_rejected"]))
        status = "blocked"

    body = {
        "schema": "consulting-proposal-draft-v1",
        "workspace_id": workspace.workspace_id,
        "status": status,
        "authority": {
            "human_approved": False,
            "contract": False,
            "invoice": False,
            "work_authorized": False,
            "payment_authorized": False,
            "provider_calls": False,
        },
        "scope": {
            "text": offer_request.scope,
            "inclusions": inclusions,
            "exclusions": exclusions,
            "assumptions": assumptions,
            "unknowns": list(dict.fromkeys(unknowns)),
        },
        "evidence": register_body,
        "engagement": engagement_body,
        "economics": economics_body,
        "offer": offer_body,
        "client_export": exported,
        "blockers": export_blockers,
    }
    body["fingerprint"] = replay_fingerprint(body)
    if incoming != dict(request):
        raise ConsultingProposalDraftError("caller_metadata_mutated")
    return body


def render_consulting_proposal_markdown(draft: Mapping[str, Any]) -> str:
    authority = draft.get("authority") if isinstance(draft.get("authority"), Mapping) else {}
    scope = draft.get("scope") if isinstance(draft.get("scope"), Mapping) else {}
    economics = draft.get("economics") if isinstance(draft.get("economics"), Mapping) else {}
    lines = [
        "# Consulting proposal draft",
        "",
        "Draft only. Not an approval, contract, invoice, or authority to perform work.",
        f"Status: {draft.get('status', 'blocked')}",
        f"Human approved: {authority.get('human_approved', False)}",
        "",
        "## Scope",
        str(scope.get("text", "")),
        "",
        "## Inclusions",
        *[f"- {item}" for item in scope.get("inclusions") or ["None recorded."]],
        "",
        "## Exclusions",
        *[f"- {item}" for item in scope.get("exclusions") or ["None recorded."]],
        "",
        "## Assumptions",
        *[f"- {item}" for item in scope.get("assumptions") or ["None recorded."]],
        "",
        "## Unknowns",
        *[f"- {item}" for item in scope.get("unknowns") or ["None recorded."]],
        "",
        "## Economics",
        f"Currency: {economics.get('currency', 'unknown')}",
        f"Recommendation: {economics.get('recommendation', 'not_run')}",
        "Catalog bands are planning inputs, not a quote.",
        "",
    ]
    return "\n".join(lines)


__all__ = ["ConsultingProposalDraftError", "build_consulting_proposal_draft", "render_consulting_proposal_markdown"]
