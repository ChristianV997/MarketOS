"""Draft briefs mapped onto existing launch-draft creative surfaces."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .adapter import plan_creative_job
from .contracts import CreativeJob, CreativeJobRequest
from .fixtures import FIXTURES


@dataclass(frozen=True)
class CreativeBrief:
    brief_type: str
    title: str
    shots: tuple[str, ...]
    do_not_claim: tuple[str, ...]
    job: CreativeJob

    def to_dict(self) -> dict[str, Any]:
        return {
            "brief_type": self.brief_type,
            "title": self.title,
            "shots": list(self.shots),
            "do_not_claim": list(self.do_not_claim),
            "job": self.job.to_dict(),
            "live_actions_taken": False,
        }


def _brief(kind: str, title: str, shots: tuple[str, ...], request: CreativeJobRequest) -> CreativeBrief:
    job = plan_creative_job(request)
    return CreativeBrief(kind, title, shots, ("no medical claims", "no guaranteed results", "no live publication"), job)


def product_photo_brief(name: str = "hydroponics") -> CreativeBrief:
    return _brief(
        "product_photo",
        f"{name} product photography draft",
        ("hero on seamless", "hands using the product", "detail texture"),
        FIXTURES[name],
    )


def marketplace_card_brief() -> CreativeBrief:
    return _brief(
        "marketplace_card",
        "marketplace card draft",
        ("main image", "secondary angle", "A+ lifestyle"),
        FIXTURES["marketplace_card"],
    )


def ugc_video_brief() -> CreativeBrief:
    return _brief(
        "ugc_video",
        "UGC creative brief draft",
        ("hook 3s", "demo 8s", "objection 4s", "cta 3s"),
        FIXTURES["ugc"],
    )


def explainer_brief() -> CreativeBrief:
    req = FIXTURES["hydroponics"]
    request = CreativeJobRequest(
        request_id="req-explainer-hydro",
        workspace_id=req.workspace_id,
        lane=req.lane,
        offer_id=req.offer_id,
        product_id=req.product_id,
        market_lane=req.market_lane,
        channel="owned_site",
        creative_type="explainer_video",
        mode="dry_run",
        locale=req.locale,
        claims=req.claims,
        evidence_ids=req.evidence_ids,
        prompt_metadata="explainer storyboard only",
        reference_asset_ids=req.reference_asset_ids,
    )
    return _brief("explainer_video", "explainer video draft", ("problem", "workflow", "close"), request)


def brand_kit_brief() -> CreativeBrief:
    req = FIXTURES["hydroponics"]
    request = CreativeJobRequest(
        request_id="req-brandkit-hydro",
        workspace_id=req.workspace_id,
        lane="client",
        offer_id=req.offer_id,
        product_id=req.product_id,
        market_lane=req.market_lane,
        channel="brand",
        creative_type="brand_kit",
        mode="dry_run",
        locale=req.locale,
        claims=req.claims,
        evidence_ids=req.evidence_ids,
        prompt_metadata="palette and type metadata only",
        reference_asset_ids=(),
    )
    return _brief("brand_kit", "brand-kit metadata draft", ("palette", "type", "do-not-use"), request)


__all__ = [
    "CreativeBrief",
    "product_photo_brief",
    "marketplace_card_brief",
    "ugc_video_brief",
    "explainer_brief",
    "brand_kit_brief",
]
