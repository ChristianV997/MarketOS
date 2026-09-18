"""Compatibility projection onto existing Launch Draft Pack seams.

Does not mutate launch-draft, site-draft, TrustOS, or Governor authorities.
Does not create a second marketing packet or media database.
"""
from __future__ import annotations

from typing import Any, Mapping

from .contracts import CreativeJob
from .workflow import SOURCE_GOVERNANCE_REF

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


def _brief_type_for(creative_type: str, content_angle: str, existing: str = "") -> str:
    if existing in BRIEF_TYPES:
        return existing
    mapping = {
        "marketplace_card": "marketplace_card",
        "product_photo": "product_photoshoot_brief",
        "explainer_video": "video_explainer_brief",
        "ugc_video": "ugc_brief",
        "brand_kit": "creative_brief",
        "virality_metadata": "thumbnail_asset_brief",
    }
    if content_angle in BRIEF_TYPES:
        return content_angle
    return mapping.get(creative_type, "creative_brief")


def _payload_of(draft: Any) -> dict[str, Any]:
    if hasattr(draft, "to_dict"):
        return dict(draft.to_dict())
    if isinstance(draft, Mapping):
        return dict(draft)
    raise TypeError("unsupported draft payload")


def project_launch_draft_compat(draft: Any) -> dict[str, Any]:
    """Map a commercial creative draft onto existing launch-draft field names.

    Never authorizes Shopify/Medusa publish. Status remains draft.
    """
    payload = _payload_of(draft)
    job_payload = payload.get("job") if isinstance(payload.get("job"), Mapping) else {}
    request_like = {}
    if hasattr(draft, "job"):
        request_like = {
            "creative_type": getattr(draft.job.request, "creative_type", ""),
            "content_angle": getattr(draft.job.request, "content_angle", ""),
            "job_id": draft.job.job_id,
            "replay": draft.job.replay,
        }
    creative_type = str(
        payload.get("creative_type")
        or job_payload.get("creative_type")
        or request_like.get("creative_type")
        or ""
    )
    content_angle = str(
        payload.get("content_angle")
        or request_like.get("content_angle")
        or ""
    )
    brief_type = _brief_type_for(creative_type, content_angle, str(payload.get("brief_type") or ""))
    export_allowed = bool(payload.get("client_export_allowed"))

    launch_version = "pending-import"
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
        "job_id": payload.get("job_id") or request_like.get("job_id") or job_payload.get("job_id") or "",
        "replay": payload.get("replay") or request_like.get("replay") or job_payload.get("replay") or "",
        "creative_quality": payload.get("creative_quality") or "draft_only",
        "commercial_validation": payload.get("commercial_validation") or "not_commercially_validated",
    }


def project_job_compat(job: CreativeJob) -> dict[str, Any]:
    payload = {
        "schema": "MarketOS.CreativeCommercialDraft.v1",
        "brief_type": "",
        "content_angle": job.request.content_angle,
        "creative_type": job.request.creative_type,
        "client_export_allowed": False,
        "source_governance_ref": SOURCE_GOVERNANCE_REF,
        "job_id": job.job_id,
        "replay": job.replay,
        "job": job.to_dict(),
        "creative_quality": "draft_only",
        "commercial_validation": "not_commercially_validated",
    }
    return project_launch_draft_compat(payload)


__all__ = [
    "BRIEF_TYPES",
    "LAUNCH_DRAFT_SEAM",
    "SITE_DRAFT_SEAM",
    "project_launch_draft_compat",
    "project_job_compat",
]
