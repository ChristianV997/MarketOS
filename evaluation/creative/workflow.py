"""Offline commercial creative-draft workflow.

Links creative jobs to product/offer/lane/workspace identities without
becoming a media-generation runtime or a second marketing packet.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .adapter import attach_launch_draft_context, governance_gate, plan_creative_job
from .contracts import CreativeAdapterError, CreativeJob, CreativeJobRequest
from .fixtures import WORKFLOW_FIXTURES

SCHEMA = "MarketOS.CreativeCommercialDraft.v1"
SOURCE_GOVERNANCE_REF = "MarketOS.SourceGovernance.Higgsfield.v1-pending"
SOURCE_GOVERNANCE_OWNER = "PR #257 (pending consume-by-reference; not forked)"
SUPPORTED_MODELS = frozenset({"higgsfield.catalog.static"})
BLOCKED_CLAIM_MARKERS = (
    "medical",
    "cura",
    "health benefit",
    "beneficio de salud",
    "certified compliance",
    "warranty forever",
    "garantia total",
    "performance guaranteed",
    "resultado garantizado",
)
PROHIBITED_DEFAULT = (
    "no medical claims",
    "no health-cure claims",
    "no compliance certification without evidence",
    "no warranty or performance guarantees",
    "no live publication",
)


@dataclass(frozen=True)
class CreativeCommercialDraft:
    schema: str
    workflow_id: str
    package_alias: str
    brief_type: str
    language: str
    locale: str
    content_angle: str
    sku_variant: str
    product_id: str
    offer_id: str
    supplier_offer_id: str
    market_lane: str
    business_model: str
    workspace_id: str
    client_workspace_id: str
    required_claims: tuple[str, ...]
    prohibited_claims: tuple[str, ...]
    assumptions: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    approval_state: str
    draft_status: str
    creative_quality: str
    commercial_validation: str
    source_governance_ref: str
    asset_lineage: tuple[str, ...]
    job: CreativeJob
    client_export_allowed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "workflow_id": self.workflow_id,
            "package_alias": self.package_alias,
            "brief_type": self.brief_type,
            "language": self.language,
            "locale": self.locale,
            "content_angle": self.content_angle,
            "sku_variant": self.sku_variant,
            "product_id": self.product_id,
            "offer_id": self.offer_id,
            "supplier_offer_id": self.supplier_offer_id,
            "market_lane": self.market_lane,
            "business_model": self.business_model,
            "workspace_id": self.workspace_id,
            "client_workspace_id": self.client_workspace_id,
            "required_claims": list(self.required_claims),
            "prohibited_claims": list(self.prohibited_claims),
            "assumptions": list(self.assumptions),
            "missing_evidence": list(self.missing_evidence),
            "approval_state": self.approval_state,
            "draft_status": self.draft_status,
            "creative_quality": self.creative_quality,
            "commercial_validation": self.commercial_validation,
            "source_governance_ref": self.source_governance_ref,
            "asset_lineage": list(self.asset_lineage),
            "job": self.job.to_dict(),
            "client_export_allowed": self.client_export_allowed,
            "live_actions_taken": False,
            "published": False,
            "generated": False,
            "observed": False,
            "record_kind": "planning_record",
        }

    def client_projection(self) -> dict[str, Any]:
        if not self.client_export_allowed:
            raise CreativeAdapterError("client export requires evidence and approval metadata")
        body = self.to_dict()
        job = dict(body["job"])
        job.pop("prompt_metadata", None)
        body["job"] = job
        body["schema"] = "MarketOS.ClientCreativeProjection.v1"
        body["confidence"] = "planning_only"
        return body


def _blocked_claims(claims: tuple[str, ...]) -> tuple[str, ...]:
    hits = []
    for claim in claims:
        lower = claim.lower()
        if any(marker in lower for marker in BLOCKED_CLAIM_MARKERS):
            hits.append(claim)
    return tuple(hits)


def compose_draft(request: CreativeJobRequest, *, workflow_id: str, package_alias: str, brief_type: str) -> CreativeCommercialDraft:
    if request.model_id not in SUPPORTED_MODELS:
        raise CreativeAdapterError("unsupported model")
    identity = request.workspace_id + request.product_id + request.offer_id + request.sku_variant
    if ".." in identity or "/" in request.workspace_id or "\\" in request.workspace_id:
        raise CreativeAdapterError("path traversal rejected")
    blocked = _blocked_claims(request.claims)
    job = plan_creative_job(request)
    missing = list(request.missing_evidence)
    if request.creative_type == "marketplace_card" and not request.sku_variant:
        missing.append("exact_sku_variant")
        job = CreativeJob(
            schema=job.schema,
            job_id=job.job_id,
            request=request,
            provider=job.provider,
            status="missing_evidence",
            evidence_state="missing",
            result_refs=(),
            cost_estimate_credits=job.cost_estimate_credits,
            approval_required=job.approval_required,
            live_attestation=False,
            replay=job.replay,
            errors=job.errors + ("missing exact SKU/variant",),
            client_safe=True,
        )
        draft_status, export_ok = "blocked", False
    elif request.evidence_freshness == "stale":
        job = CreativeJob(
            schema=job.schema,
            job_id=job.job_id,
            request=request,
            provider=job.provider,
            status="blocked",
            evidence_state="rejected",
            result_refs=(),
            cost_estimate_credits=job.cost_estimate_credits,
            approval_required=job.approval_required,
            live_attestation=False,
            replay=job.replay,
            errors=job.errors + ("stale evidence cannot promote a draft",),
            client_safe=True,
        )
        draft_status, export_ok = "blocked", False
    elif blocked:
        job = CreativeJob(
            schema=job.schema,
            job_id=job.job_id,
            request=request,
            provider=job.provider,
            status="blocked",
            evidence_state="rejected",
            result_refs=(),
            cost_estimate_credits=job.cost_estimate_credits,
            approval_required=job.approval_required,
            live_attestation=False,
            replay=job.replay,
            errors=job.errors + ("unsupported product claim without evidence",),
            client_safe=True,
        )
        draft_status, export_ok = "blocked", False
    elif job.status != "dry_run_complete":
        draft_status, export_ok = job.status, False
    else:
        draft_status = "draft_ready"
        export_ok = request.approval_state == "approved" and bool(request.evidence_ids) and not missing
    if request.client_workspace_id and request.client_workspace_id != request.workspace_id:
        job = CreativeJob(
            schema=job.schema,
            job_id=job.job_id,
            request=request,
            provider=job.provider,
            status="blocked",
            evidence_state="rejected",
            result_refs=(),
            cost_estimate_credits=job.cost_estimate_credits,
            approval_required=job.approval_required,
            live_attestation=False,
            replay=job.replay,
            errors=job.errors + ("client/workspace mismatch",),
            client_safe=True,
        )
        draft_status, export_ok = "blocked", False
    return CreativeCommercialDraft(
        schema=SCHEMA,
        workflow_id=workflow_id,
        package_alias=package_alias,
        brief_type=brief_type,
        language=request.language or request.locale,
        locale=request.locale,
        content_angle=request.content_angle,
        sku_variant=request.sku_variant,
        product_id=request.product_id,
        offer_id=request.offer_id,
        supplier_offer_id=request.supplier_offer_id or request.offer_id,
        market_lane=request.market_lane,
        business_model=request.business_model,
        workspace_id=request.workspace_id,
        client_workspace_id=request.client_workspace_id or request.workspace_id,
        required_claims=request.claims,
        prohibited_claims=request.prohibited_claims or PROHIBITED_DEFAULT,
        assumptions=request.assumptions,
        missing_evidence=tuple(missing),
        approval_state=request.approval_state,
        draft_status=draft_status,
        creative_quality="draft_only",
        commercial_validation="not_commercially_validated",
        source_governance_ref=request.source_governance_ref or SOURCE_GOVERNANCE_REF,
        asset_lineage=request.reference_asset_ids,
        job=job,
        client_export_allowed=export_ok,
    )


def hydroponics_spanish_education() -> CreativeCommercialDraft:
    return compose_draft(
        WORKFLOW_FIXTURES["hydroponics_es"],
        workflow_id="wf-hydro-es-education",
        package_alias="Launch Draft Pack",
        brief_type="product_demonstration",
    )


def smart_pet_support_risk() -> CreativeCommercialDraft:
    return compose_draft(
        WORKFLOW_FIXTURES["smart_pet_support"],
        workflow_id="wf-pet-support-risk",
        package_alias="Launch Draft Pack",
        brief_type="ugc_brief",
    )


def solar_security_blocked() -> CreativeCommercialDraft:
    return compose_draft(
        WORKFLOW_FIXTURES["solar_security"],
        workflow_id="wf-solar-security-blocked",
        package_alias="Product Validation Sprint",
        brief_type="video_explainer_brief",
    )


def marketplace_card_exact_sku() -> CreativeCommercialDraft:
    return compose_draft(
        WORKFLOW_FIXTURES["marketplace_sku"],
        workflow_id="wf-marketplace-sku",
        package_alias="Launch Draft Pack",
        brief_type="marketplace_card",
    )


def product_validation_appendix() -> CreativeCommercialDraft:
    return compose_draft(
        WORKFLOW_FIXTURES["validation_appendix"],
        workflow_id="wf-validation-appendix",
        package_alias="Product Validation Sprint",
        brief_type="thumbnail_asset_brief",
    )


def managed_acquisition_variants() -> tuple[CreativeCommercialDraft, ...]:
    first = compose_draft(
        WORKFLOW_FIXTURES["acquisition_a"],
        workflow_id="wf-acq-variant-a",
        package_alias="Managed Acquisition and CRO",
        brief_type="content_angle",
    )
    second = compose_draft(
        WORKFLOW_FIXTURES["acquisition_b"],
        workflow_id="wf-acq-variant-b",
        package_alias="Managed Acquisition and CRO",
        brief_type="content_angle",
    )
    return (first, second)


def launch_draft_compat(draft: CreativeCommercialDraft) -> dict[str, Any]:
    attached = attach_launch_draft_context(draft.job)
    attached["creative_workflow"] = draft.workflow_id
    attached["commercial_validation"] = draft.commercial_validation
    attached["source_governance_ref"] = draft.source_governance_ref
    attached["governance"] = governance_gate(draft.job)
    attached["governor_role"] = "planning_budget_reference_only"
    return attached


def run_named_workflow(name: str) -> CreativeCommercialDraft | tuple[CreativeCommercialDraft, ...]:
    runners: Mapping[str, Any] = {
        "hydroponics_spanish_education": hydroponics_spanish_education,
        "smart_pet_support_risk": smart_pet_support_risk,
        "solar_security_blocked": solar_security_blocked,
        "marketplace_card_exact_sku": marketplace_card_exact_sku,
        "product_validation_appendix": product_validation_appendix,
        "managed_acquisition_variants": managed_acquisition_variants,
    }
    if name not in runners:
        raise CreativeAdapterError(f"unknown workflow: {name}")
    return runners[name]()


__all__ = [
    "SCHEMA",
    "SOURCE_GOVERNANCE_REF",
    "SOURCE_GOVERNANCE_OWNER",
    "CreativeCommercialDraft",
    "compose_draft",
    "hydroponics_spanish_education",
    "smart_pet_support_risk",
    "solar_security_blocked",
    "marketplace_card_exact_sku",
    "product_validation_appendix",
    "managed_acquisition_variants",
    "launch_draft_compat",
    "run_named_workflow",
]
