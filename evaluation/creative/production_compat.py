"""Compatibility projection onto existing Launch Draft Pack seams.

Does not mutate launch-draft, site-draft, TrustOS, or Governor authorities.
Does not create a second marketing packet or media database.
"""
from __future__ import annotations

from typing import Any, Mapping

from .contracts import CreativeJob
from .workflow import CreativeCommercialDraft, SOURCE_GOVERNANCE_REF

BRIEF_TYPES = frozenset({
    "creative_brief",
    "content_angle",
    "product_demonstration",
    "marketplace_card",
    "product_photoshoot_brief",
    "video_explainer_brief",
    "ugc_brief",
    "thumbnail_asset_brief",
})

LAUNCH_DRAFT_SEAM = "evaluation.commerce.launch_draft_pack"
SITE_DRAFT_SEAM = "evaluation.commerce.site_draft_builder"


def _brief_type_for(creative_type: str, content_angle: str) -> str:
    mapping = {
        "marketplace_card": "marketplace_card",
        "product_photo": "product_photoshoot_brief",
        "explainer_video": "video_explainer_brief",
        "ugc_video": "ugc_brief",
        "brand_kit": "creative_brief",
        "virality_metadata": "thumbnail_asset_brief",
    }
    if content_angle in {"product_demonstration", "content_angle"}:
        return content_angle
    return mapping.get(creative_type, "creative_brief")


def project_launch_draft_compat(draft: CreativeCommercialDraft | Mapping[str, Any]) -> dict[str, Any]:
    """Map a commercial creative draft onto existing launch-draft field names.

    Never authorizes Shopify/Medusa publish. Status remains draft.
    """
    if isinstance(draft, CreativeCommercialDraft):
        payload = draft.to_dict()
        job = draft.job
        request = job.request
        export_allowed = draft.client_export_allowed
    else:
        payload = dict(draft)
        job = None
        request = None
        export_allowed = bool(payload.get("client_export_allowed"))

    creative_type = payload.get("creative_type") or (request.creative_type if request else "")
    content_angle = payload.get("content_angle") or (getattr(request, "content_angle", "") if request else "")
    brief_type = _brief_type_for(str(creative_type), str(content_angle))
    if brief_type not in BRIEF_TYPES:
        brief_type = "creative_brief"

    launch_version = "unavailable"
    try:
        from evaluation.commerce.launch_draft_pack import VERSION  # type: ignore

        launch_version = str(VERSION)
    except Exception:
        launch_version = "pending-import"

    return {
        "schema": "MarketOS.CreativeLaunchDraftCompat.v1",
        "seam": LAUNCH_DRAFT_SEAM,
        "site_draft_seam": SITE_DRAFT_SEAM,
        "launch_draft_authority": launch_version,
        "launch_authorized": False,
        "shopify_status": "draft",
        "medusa_status": "draft",
        "published": False,
        "generated": False,
        "observed": False,
        "live_validated": False,
        "brief_type": brief_type,
        "ugc_brief_compatible": brief_type == "ugc_brief",
        "ad_creative_draft_compatible": brief_type in {"creative_brief", "content_angle", "marketplace_card"},
        "product_listing_compatible": brief_type == "marketplace_card",
        "client_export_allowed": export_allowed,
        "source_governance_ref": payload.get("source_governance_ref") or SOURCE_GOVERNANCE_REF,
        "governor_spend_authority": False,
        "governor_budget_reference_only": True,
        "trustos_export_required": True,
        "approval_ledger_required": True,
        "job_id": payload.get("job_id") or (job.job_id if job else ""),
        "replay": payload.get("replay") or (job.replay if job else ""),
        "creative_quality": "draft_only",
        "commercial_validation": "not_commercially_validated",
    }


def project_job_compat(job: CreativeJob) -> dict[str, Any]:
    from .workflow import CreativeCommercialDraft

    draft = CreativeCommercialDraft(
        job=job,
        commercial_validation="not_commercially_validated",
        creative_quality="draft_only",
        asset_lineage=("compat://launch-draft",),
        source_governance_ref=SOURCE_GOVERNANCE_REF,
    )
    return project_launch_draft_compat(draft)


__all__ = [
    "BRIEF_TYPES",
    "LAUNCH_DRAFT_SEAM",
    "SITE_DRAFT_SEAM",
    "project_launch_draft_compat",
    "project_job_compat",
]
