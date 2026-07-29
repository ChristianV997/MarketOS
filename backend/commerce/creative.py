"""Creative generation and bundling for the commerce loop."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from backend.vector.semantic_search import find_creatives_by_hook, find_similar_campaigns
from core.creative.generator import generate_creative
from evaluation.contracts import DataQuality

from .contracts import CreativeBundle, RankedOpportunity


def _angle_from_opportunity(opportunity: RankedOpportunity, *, semantic_hint: str = "") -> str:
    if semantic_hint:
        return semantic_hint
    if opportunity.semantic_score >= 0.8:
        return "proven-winning-angle"
    if opportunity.signal_score >= 0.7:
        return "high-signal-angle"
    if opportunity.quality_score >= 0.8:
        return "trusted-proof-angle"
    return "problem-solution-angle"


def _hook_from_opportunity(opportunity: RankedOpportunity) -> str:
    if opportunity.product_name:
        return f"Why {opportunity.product_name} is getting attention"
    return "Why this product is getting attention"


def _semantic_hook_and_angle(product_name: str) -> tuple[str, str, tuple[str, ...]]:
    refs: list[str] = []
    hook = ""
    angle = ""

    try:
        for hit in find_similar_campaigns(product_name, top_k=3):
            payload = hit.payload or {}
            if not hook:
                hook = str(payload.get("hook") or "")
            if not angle:
                angle = str(payload.get("angle") or "")
            refs.append(hit.record_id)
            if hook and angle:
                break
        if not hook:
            for hit in find_creatives_by_hook(product_name, top_k=3):
                payload = hit.payload or {}
                hook = str(payload.get("hook") or hook)
                angle = str(payload.get("angle") or angle)
                refs.append(hit.record_id)
                if hook and angle:
                    break
    except Exception:
        pass

    return hook, angle, tuple(dict.fromkeys(refs))


@dataclass
class CreativeComposer:
    """Compose deterministic creative bundles from ranked opportunities."""

    default_cta: str = "Shop Now"

    def compose(self, opportunity: RankedOpportunity) -> CreativeBundle:
        semantic_hook, semantic_angle, refs = _semantic_hook_and_angle(opportunity.product_name)
        hook = semantic_hook or _hook_from_opportunity(opportunity)
        angle = _angle_from_opportunity(opportunity, semantic_hint=semantic_angle)
        script = generate_creative(opportunity.product_name or opportunity.product_id, angle)
        headline = hook[:80]
        primary_text = script[:200]
        cta = self.default_cta if opportunity.readiness and opportunity.readiness.launchable else "Learn More"
        return CreativeBundle.from_opportunity(
            opportunity,
            script=script,
            hook=hook,
            angle=angle,
            headline=headline,
            primary_text=primary_text,
            cta=cta,
            source_refs=refs,
            quality=opportunity.quality if opportunity.quality else DataQuality(),
        )

    def compose_batch(self, opportunities: Iterable[RankedOpportunity]) -> list[CreativeBundle]:
        return [self.compose(opportunity) for opportunity in opportunities]
