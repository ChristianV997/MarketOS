"""Canonical service-engagement projection producer for the read-only
frontend workbench (PR #264 / #271).

This module does not duplicate the frontend adapter
(``frontend/src/features/service-delivery-workbench/lib/adaptServiceProjection.ts``,
untouched by this module) or its API route (``api/routes/service_delivery_workbench.py``,
untouched by this module). It produces data in the ``service-delivery-plane-v1``
shape that adapter already knows how to consume: an enriched
``ClientEngagement.to_dict()`` per engagement, with a handful of additive
sub-objects (``evidence_set`` entries carrying an ``evidence_class``,
``economics``, ``financial_readiness``, ``capacity``, ``next_best_action``)
that let the existing, already-tested adapter render richer detail instead
of falling back to its own defaults. Every key this module adds is one the
adapter already reads and gracefully defaults when absent -- nothing here
recalculates money, re-ranks engagements, or invents a lifecycle state.

Canonical authorities reused, never re-derived:

- :mod:`evaluation.companyos.service_delivery` (``ClientEngagement``,
  ``ClientFacingServicePackage``, ``ClientDataQualityAssessment``).
- :mod:`backend.economics.kernel` (``ServiceEconomics``, ``Money``) via
  the existing ``evaluate_engagement_economics()``.
- :mod:`evaluation.companyos.service_delivery_artifact`
  (``classify_evidence_ref``, ``build_service_delivery_artifact``) for
  evidence classification and the next-human-action string.
- :func:`evaluation.trustos.client_workspace_isolation.check_workspace_leakage`
  as the sole export boundary -- applied to the whole envelope before it is
  considered emittable.

No second service catalog, price book, financial engine, API client,
database, or workflow engine is created. Every action stays draft-only and
offline: this module never writes to ``artifacts/`` itself (a caller
decides whether/where to persist the returned dict), never calls a
provider, and never mutates a client, payment, or lifecycle record.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from backend.economics import Money, ServiceEconomics

from .service_delivery import (
    ClientDataQualityAssessment,
    ClientEngagement,
    ClientFacingServicePackage,
)
from backend.economics import EvidenceRef

from .service_delivery_artifact import ServiceDeliveryArtifact, classify_evidence_ref


def _frontend_evidence_class_for_kernel_state(evidence_state: str) -> str:
    """Route a raw ``backend.economics.kernel`` evidence_state string (e.g.
    ``ServiceEconomics.evidence_state``) through the same artifact
    classification layer real evidence references go through, rather than
    feeding a kernel-vocabulary string into the artifact-vocabulary-to-
    frontend-vocabulary map directly (they are different vocabularies; only
    coincidentally overlapping strings would "work" by accident)."""
    return _frontend_evidence_class(classify_evidence_ref(EvidenceRef("economics", evidence_state=evidence_state)))

PROJECTION_REPORT_VERSION = "service-delivery-plane-v1"

# Mirrors frontend/src/features/service-delivery-workbench/contracts/serviceEngagementProjection.ts
# EVIDENCE_CLASSES -- the frontend's own vocabulary, not this backend's
# ARTIFACT_EVIDENCE_CLASSIFICATIONS. Translating at the producer boundary
# means the frontend adapter's own normalizeEvidenceClass() never has to
# guess at a backend-internal string it does not recognize.
_ARTIFACT_TO_FRONTEND_EVIDENCE_CLASS: dict[str, str] = {
    "planning_assumption": "assumption",
    "fixture": "fixture",
    "manual_import": "manual_import",
    "derived": "derived",
    "supplier_claimed": "supplier_claimed",
    "supplier_documented": "supplier_documented",
    "public_observed": "observed",
    # The frontend has no purpose-built slot for "verified but not
    # live_readonly" evidence. Mapping it to "manual_import" rather than
    # "live_validated" is the fail-closed choice: it never overclaims, even
    # though it understates a genuinely stronger evidence state than a raw
    # manual import.
    "sample_verified": "manual_import",
    "live_validated": "live_validated",
    "unavailable": "unavailable",
}


def _frontend_evidence_class(artifact_classification: str) -> str:
    return _ARTIFACT_TO_FRONTEND_EVIDENCE_CLASS.get(artifact_classification, "unavailable")


def _display_money(money: Money | None, evidence_class: str) -> dict[str, Any] | None:
    if money is None:
        return None
    return {
        "amount_label": str(money.amount),
        "currency": money.currency,
        "evidence_class": evidence_class,
        "source": "backend_service_economics",
        "display_only": True,
    }


_FIELD_LABELS: dict[str, str] = {
    # No "/" in any label: a slash surrounded by whitespace trips
    # check_workspace_leakage's filesystem-path heuristic (it conservatively
    # treats "word / word" the same as a path fragment like "/etc/passwd").
    # That heuristic is this repo's shared export boundary and is not this
    # module's to loosen, so these labels are worded without one instead.
    "client_identity": "Client identity",
    "product_offer_identity": "Product or offer identity",
    "date_range": "Reporting date range",
    "revenue": "Revenue",
    "orders": "Orders",
    "ad_spend": "Ad spend",
    "cac_roas_inputs": "CAC and ROAS inputs",
    "product_and_fulfillment_costs": "Product and fulfillment costs",
    "shipping": "Shipping",
    "returns_refunds": "Returns and refunds",
    "payment_platform_fees": "Payment and platform fees",
}


def _intake_fields(data_quality: ClientDataQualityAssessment) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for name in (*data_quality.present_fields, *data_quality.missing_fields):
        if name in data_quality.conflicting_fields:
            status = "conflicting"
        elif name in data_quality.stale_fields:
            status = "stale"
        elif name in data_quality.missing_fields:
            status = "missing"
        else:
            status = "received"
        fields.append({
            "field_id": name,
            "label": _FIELD_LABELS.get(name, name.replace("_", " ").title()),
            "status": status,
            "client_must_provide": "Already recorded as a display copy." if status == "received" else f"Provide {_FIELD_LABELS.get(name, name)} as a client-safe record.",
        })
    return fields


def _capacity_signal(economics: ServiceEconomics | None) -> dict[str, Any]:
    if economics is None or economics.capacity_utilization is None:
        return {"state": "unavailable", "message": "Capacity signal unavailable.", "concurrent_label": None}
    utilization = economics.capacity_utilization
    if utilization >= 1:
        state = "blocked"
    elif utilization >= Decimal("0.8"):
        state = "warning"
    else:
        state = "ok"
    label = None
    if economics.maximum_simultaneous_clients is not None:
        label = f"Up to {economics.maximum_simultaneous_clients} concurrent clients at this delivery-hours rate."
    return {"state": state, "message": f"Delivery-hours utilization at {utilization:.0%}.", "concurrent_label": label}


def build_service_engagement_row(
    engagement: ClientEngagement,
    package: ClientFacingServicePackage,
    data_quality: ClientDataQualityAssessment,
    economics: ServiceEconomics | None,
    artifact: ServiceDeliveryArtifact | None = None,
    *,
    display_name: str | None = None,
    contact_channel: str = "not_collected",
    evidence_titles: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build one enriched ``service-delivery-plane-v1`` engagement row.

    Starts from ``engagement.to_dict()`` (the existing, tested canonical
    shape) and only adds keys the frontend adapter already knows how to
    read -- it never invents a new field the adapter does not consume.
    """
    row = engagement.to_dict()
    evidence_titles = evidence_titles or {}

    row["service_id"] = package.package_id
    # engagement.data_quality_state only updates when a caller threads it
    # through transition_engagement(..., data_quality_state=...); a caller
    # that (like this module's own tests originally did) computes a fresh
    # ClientDataQualityAssessment but forgets that step would otherwise emit
    # a stale value here. This function receives the authoritative
    # data_quality object directly, so it always reflects it rather than
    # trusting the engagement's own possibly-stale copy.
    row["data_quality_state"] = data_quality.status
    row["intake"] = {
        "client_id": engagement.client_id,
        "display_name": display_name or engagement.client_id,
        "workspace_id": engagement.workspace_id,
        "contact_channel": contact_channel,
        "fields": _intake_fields(data_quality),
    }
    row["eligibility"] = {
        "eligible": not data_quality.data_inadequate and engagement.lifecycle_state not in {"rejected", "cancelled"},
        "data_inadequate": data_quality.data_inadequate,
        "reasons": list(data_quality.reasons),
        "required_from_client": [
            {
                "field": name,
                "why": f"{_FIELD_LABELS.get(name, name)} is required before analysis can proceed.",
                "how_to_provide": f"Provide {_FIELD_LABELS.get(name, name)} as a client-safe export.",
            }
            for name in data_quality.missing_fields
        ],
    }
    row["evidence_set"] = [
        {
            **ref.to_dict(),
            "evidence_class": _frontend_evidence_class(classify_evidence_ref(ref)),
            "title": evidence_titles.get(ref.evidence_id, ref.source_type or "Evidence item"),
            "summary": ref.document_ref or "",
            "collected_at": ref.captured_at or None,
        }
        for ref in engagement.evidence_set
    ]
    fee_class = _frontend_evidence_class("planning_assumption")
    contribution_class = _frontend_evidence_class_for_kernel_state(economics.evidence_state) if economics is not None else "unavailable"
    # economics.service_fee (when available), not engagement.fee: the
    # engagement's own fee is the package's default-currency quote fixed at
    # intake time and is never updated afterward, while service_fee is the
    # exact value actually passed into calculate_service_economics -- using
    # engagement.fee here would silently show the wrong currency for any
    # engagement whose actual computed fee uses a different currency than
    # the package default (e.g. an MXN client on a USD-default package).
    fee_for_display = economics.service_fee if economics is not None else engagement.fee
    row["economics"] = {
        "authority": "backend_service_economics",
        "frontend_calculates": False,
        "fee": _display_money(fee_for_display, fee_class),
        "contribution": _display_money(economics.contribution if economics else None, contribution_class),
        "contribution_unavailable_reason": None if economics and economics.contribution else "No sanitized contribution copy was supplied.",
        "planning_assumption_note": "Price, CAC, ROAS, and contribution labels are planning assumptions unless marked live_validated by the backend.",
    }
    row["financial_readiness"] = {
        "ready": economics is not None and not data_quality.data_inadequate,
        "missing": list(data_quality.missing_fields),
        "note": "Financial figures are display copies only. The frontend does not calculate contribution.",
    }
    # Same class of fix as data_quality_state above: engagement.missing_information
    # only updates via an explicit transition_engagement(..., missing_information=...)
    # call, so it is frequently stale/empty. The adapter reads "missing_data"
    # in preference to "missing_information" (falling back to the latter only
    # when the former is absent) -- set it directly from the authoritative
    # ClientDataQualityAssessment instead of trusting the engagement's own copy.
    row["missing_data"] = list(dict.fromkeys((*data_quality.missing_fields, *engagement.missing_information)))
    row["capacity"] = _capacity_signal(economics)
    row["next_best_action"] = {
        "action": artifact.next_human_action if artifact else "Review intake and data quality before proceeding.",
        "owner": "client" if data_quality.data_inadequate else ("blocked" if engagement.lifecycle_state in {"rejected", "cancelled", "paused"} else "operator"),
        "executes_live_action": False,
        "rationale": "This workbench is read-only and does not execute CompanyOS transitions.",
    }
    row["deliverable_ids"] = row["deliverable_ids"] or [item.deliverable_id for item in package.deliverables]
    row["private_operator_notes"] = None
    # internal_prompt / internal_formula are intentionally never set here,
    # not even to None: check_workspace_leakage rejects any key merely
    # *named* like internal content regardless of its value, and the
    # frontend adapter already treats an absent key the same as an
    # explicit null (`record.internal_prompt == null ? null : ...`), so
    # omitting them is both safe and behaviorally identical on the other
    # side of this boundary.
    row["stale"] = bool(data_quality.stale_fields)
    return row


def build_service_engagement_projection(
    rows: list[Mapping[str, Any]],
    *,
    availability: str = "manual_import",
    generated_at: str = "offline-deterministic",
    diagnostics: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Wrap engagement rows in the canonical ``service-delivery-plane-v1``
    envelope and apply the TrustOS export boundary before returning it.

    Raises ``ValueError`` if the assembled envelope fails
    ``check_workspace_leakage`` -- this producer fails closed rather than
    emitting a payload the API route would have to reject anyway.
    """
    from evaluation.trustos.client_workspace_isolation import check_workspace_leakage

    payload: dict[str, Any] = {
        "report_version": PROJECTION_REPORT_VERSION,
        "schema_version": PROJECTION_REPORT_VERSION,
        "availability": availability,
        "generated_at": generated_at,
        "engagements": [dict(row) for row in rows],
        "diagnostics": list(diagnostics),
        "read_only": True,
        "network_calls": False,
        "mutated": False,
    }
    leakage_findings = check_workspace_leakage(payload, client_safe=True)
    if leakage_findings:
        raise ValueError(f"projection failed workspace isolation: {[item.field_path for item in leakage_findings]}")
    return payload


__all__ = [
    "PROJECTION_REPORT_VERSION",
    "build_service_engagement_row",
    "build_service_engagement_projection",
]
