"""Sanitized creative fixtures. No credentials, no live assets."""
from __future__ import annotations

from .contracts import CreativeJobRequest


def _req(**overrides: object) -> CreativeJobRequest:
    base: dict[str, object] = {
        "request_id": "req-hydro-photo",
        "workspace_id": "ws-internal-hydro",
        "lane": "internal",
        "offer_id": "offer-hydro-tower",
        "product_id": "hydroponics-tower",
        "market_lane": "US",
        "channel": "marketplace",
        "creative_type": "product_photo",
        "mode": "fixture",
        "locale": "en",
        "claims": ("countertop herb garden draft",),
        "evidence_ids": ("ev-hydro-listing",),
        "prompt_metadata": "studio hero, no badges, no medical claim",
        "reference_asset_ids": ("ref-hydro-packaging",),
    }
    base.update(overrides)
    return CreativeJobRequest(**base)  # type: ignore[arg-type]


FIXTURES = {
    "hydroponics": _req(),
    "smart_pet": _req(
        request_id="req-pet-photo",
        workspace_id="ws-internal-pet",
        offer_id="offer-smart-feeder",
        product_id="smart-pet-feeder",
        claims=("scheduled feeding draft",),
        evidence_ids=("ev-pet-manual",),
        mode="manual_import",
        prompt_metadata="lifestyle kitchen, no guaranteed health outcome",
    ),
    "solar_blocked": _req(
        request_id="req-solar-blocked",
        workspace_id="ws-internal-solar",
        offer_id="offer-solar-4g",
        product_id="solar-4g-cam",
        claims=("security camera draft",),
        evidence_ids=("ev-solar-compliance",),
        mode="blocked_live",
        channel="ads",
        prompt_metadata="do not imply certified surveillance performance",
    ),
    "marketplace_card": _req(
        request_id="req-hydro-card",
        creative_type="marketplace_card",
        mode="dry_run",
        prompt_metadata="main + secondary + A+ layout draft",
    ),
    "ugc": _req(
        request_id="req-pet-ugc",
        workspace_id="ws-internal-pet",
        product_id="smart-pet-feeder",
        creative_type="ugc_video",
        mode="dry_run",
        channel="short_video",
        prompt_metadata="hook demo cta, no live posting",
        evidence_ids=("ev-pet-manual",),
    ),
}


__all__ = ["FIXTURES"]
