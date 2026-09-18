"""Static Higgsfield-inspired capability catalog. No network, no SDK."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SUPPORTED_LOCALES = frozenset({"en", "es", "en-US", "es-MX"})


@dataclass(frozen=True)
class Capability:
    capability_id: str
    creative_type: str
    source_skill: str
    estimated_credits: str
    live_available: bool = False
    notes: str = "dry-run catalog only"


CAPABILITIES: tuple[Capability, ...] = (
    Capability("product_photo", "product_photo", "higgsfield-product-photoshoot", "1-4"),
    Capability("marketplace_card", "marketplace_card", "higgsfield-marketplace-cards", "1-6"),
    Capability("ugc_video", "ugc_video", "higgsfield-generate", "4-12"),
    Capability("explainer_video", "explainer_video", "higgsfield-video-explainer", "8-20"),
    Capability("brand_kit", "brand_kit", "higgsfield-brandkit", "2-8"),
    Capability("virality_metadata", "virality_metadata", "higgsfield-generate", "1-2"),
)


def capability_catalog() -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "capability_id": item.capability_id,
            "creative_type": item.creative_type,
            "source_skill": item.source_skill,
            "estimated_credits": item.estimated_credits,
            "live_available": False,
            "notes": item.notes,
        }
        for item in CAPABILITIES
    )


def lookup(creative_type: str) -> Capability | None:
    for item in CAPABILITIES:
        if item.creative_type == creative_type:
            return item
    return None


def locale_supported(locale: str) -> bool:
    return locale in SUPPORTED_LOCALES


__all__ = ["Capability", "CAPABILITIES", "capability_catalog", "lookup", "locale_supported", "SUPPORTED_LOCALES"]
