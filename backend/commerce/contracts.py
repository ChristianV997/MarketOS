"""Typed commerce loop records with lineage and quality metadata."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from backend.contracts import BaseArtifact
from backend.vector.normalization import deterministic_id
from evaluation.contracts import DataQuality, ProductCandidate, SupplierOffer
from evaluation.readiness import LaunchReadiness


def _quality_dict(quality: DataQuality) -> dict[str, Any]:
    return {
        "provenance": quality.provenance,
        "attribution": quality.attribution,
        "completeness": quality.completeness,
        "observed_at": quality.observed_at.isoformat(),
        "source_ref": quality.source_ref,
        "is_synthetic": quality.is_synthetic,
        "is_live_attributed": quality.is_live_attributed,
    }


def _quality_from_dict(data: dict[str, Any] | None) -> DataQuality:
    if not data:
        return DataQuality()
    if isinstance(data, DataQuality):
        return data
    observed_at = data.get("observed_at")
    if isinstance(observed_at, str):
        try:
            from datetime import datetime
            observed_at = datetime.fromisoformat(observed_at)
        except ValueError:
            observed_at = None
    kwargs = {
        "provenance": data.get("provenance", "unknown"),
        "attribution": data.get("attribution", "unknown"),
        "completeness": data.get("completeness", "complete"),
        "source_ref": data.get("source_ref", ""),
    }
    if observed_at is not None:
        kwargs["observed_at"] = observed_at
    return DataQuality(**kwargs)


def _stable_id(prefix: str, *parts: object) -> str:
    return deterministic_id(prefix, "::".join(str(part) for part in parts))


@dataclass
class CommerceSignal(BaseArtifact):
    artifact_type: str = field(default="commerce_signal")
    signal_id: str = ""
    product_id: str = ""
    product_name: str = ""
    raw_text: str = ""
    source: str = ""
    platform: str = ""
    score: float = 0.0
    engagement: float = 0.0
    velocity: float = 0.0
    quality: DataQuality = field(default_factory=DataQuality)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_signal(cls, signal: dict[str, Any], *, workspace: str = "commerce") -> "CommerceSignal":
        product_name = str(signal.get("product") or signal.get("product_name") or signal.get("name") or "")
        signal_id = str(signal.get("id") or signal.get("signal_id") or _stable_id("commerce_signal", product_name, signal.get("source", ""), signal.get("platform", "")))
        quality = _quality_from_dict(signal.get("quality"))
        return cls(
            artifact_id=signal_id,
            workspace=workspace,
            parent_ids=list(signal.get("parent_ids") or []),
            signal_id=signal_id,
            product_id=str(signal.get("product_id") or product_name or signal_id),
            product_name=product_name or str(signal.get("product_id") or signal_id),
            raw_text=str(signal.get("raw_text") or signal.get("text") or signal.get("description") or product_name),
            source=str(signal.get("source") or ""),
            platform=str(signal.get("platform") or ""),
            score=float(signal.get("score", 0.0) or 0.0),
            engagement=float(signal.get("engagement", 0.0) or 0.0),
            velocity=float(signal.get("velocity", 0.0) or 0.0),
            quality=quality,
            metadata=dict(signal.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "signal_id": self.signal_id,
                "product_id": self.product_id,
                "product_name": self.product_name,
                "raw_text": self.raw_text,
                "source": self.source,
                "platform": self.platform,
                "score": self.score,
                "engagement": self.engagement,
                "velocity": self.velocity,
                "quality": _quality_dict(self.quality),
                "metadata": self.metadata,
            }
        )
        return data


@dataclass
class RankedOpportunity(BaseArtifact):
    artifact_type: str = field(default="ranked_opportunity")
    signal_id: str = ""
    product_id: str = ""
    product_name: str = ""
    source_signal_ids: tuple[str, ...] = ()
    score: float = 0.0
    signal_score: float = 0.0
    semantic_score: float = 0.0
    economics_score: float = 0.0
    quality_score: float = 0.0
    competition_penalty: float = 0.0
    reasons: tuple[str, ...] = ()
    quality: DataQuality = field(default_factory=DataQuality)
    readiness: LaunchReadiness | None = None
    economics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "signal_id": self.signal_id,
                "product_id": self.product_id,
                "product_name": self.product_name,
                "source_signal_ids": list(self.source_signal_ids),
                "score": self.score,
                "signal_score": self.signal_score,
                "semantic_score": self.semantic_score,
                "economics_score": self.economics_score,
                "quality_score": self.quality_score,
                "competition_penalty": self.competition_penalty,
                "reasons": list(self.reasons),
                "quality": _quality_dict(self.quality),
                "readiness": self.readiness.to_dict() if self.readiness else None,
                "economics": self.economics,
            }
        )
        return data


@dataclass
class CreativeBundle(BaseArtifact):
    artifact_type: str = field(default="creative_bundle")
    product_id: str = ""
    product_name: str = ""
    signal_id: str = ""
    creative_id: str = ""
    hook: str = ""
    angle: str = ""
    script: str = ""
    headline: str = ""
    primary_text: str = ""
    cta: str = "Learn More"
    source_refs: tuple[str, ...] = ()
    quality: DataQuality = field(default_factory=DataQuality)
    reasons: tuple[str, ...] = ()

    @classmethod
    def from_opportunity(
        cls,
        opportunity: RankedOpportunity,
        *,
        script: str,
        hook: str,
        angle: str,
        headline: str,
        primary_text: str,
        cta: str,
        source_refs: tuple[str, ...] = (),
        quality: DataQuality | None = None,
        workspace: str = "commerce",
    ) -> "CreativeBundle":
        creative_id = _stable_id("creative_bundle", opportunity.product_id, hook, angle, opportunity.signal_id)
        return cls(
            artifact_id=creative_id,
            workspace=workspace,
            parent_ids=[opportunity.artifact_id],
            product_id=opportunity.product_id,
            product_name=opportunity.product_name,
            signal_id=opportunity.signal_id,
            creative_id=creative_id,
            hook=hook,
            angle=angle,
            script=script,
            headline=headline,
            primary_text=primary_text,
            cta=cta,
            source_refs=source_refs,
            quality=quality or opportunity.quality,
            reasons=opportunity.reasons,
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "product_id": self.product_id,
                "product_name": self.product_name,
                "signal_id": self.signal_id,
                "creative_id": self.creative_id,
                "hook": self.hook,
                "angle": self.angle,
                "script": self.script,
                "headline": self.headline,
                "primary_text": self.primary_text,
                "cta": self.cta,
                "source_refs": list(self.source_refs),
                "quality": _quality_dict(self.quality),
                "reasons": list(self.reasons),
            }
        )
        return data


@dataclass
class LaunchPlan(BaseArtifact):
    artifact_type: str = field(default="launch_plan")
    product_id: str = ""
    product_name: str = ""
    creative_id: str = ""
    platform: str = "tiktok"
    budget: float = 0.0
    currency: str = "USD"
    campaign_name: str = ""
    dry_run: bool = True
    status: str = "planned"
    campaign_id: str = ""
    adgroup_id: str = ""
    ad_ids: tuple[str, ...] = ()
    quality: DataQuality = field(default_factory=DataQuality)
    reasons: tuple[str, ...] = ()

    @classmethod
    def from_bundle(
        cls,
        bundle: CreativeBundle,
        *,
        budget: float,
        platform: str = "tiktok",
        dry_run: bool = True,
        workspace: str = "commerce",
    ) -> "LaunchPlan":
        campaign_name = f"{bundle.product_name[:48]}::{bundle.creative_id[:8]}"
        launch_id = _stable_id("launch_plan", bundle.creative_id, platform, round(float(budget), 2), dry_run)
        return cls(
            artifact_id=launch_id,
            workspace=workspace,
            parent_ids=[bundle.artifact_id],
            product_id=bundle.product_id,
            product_name=bundle.product_name,
            creative_id=bundle.creative_id,
            platform=platform,
            budget=round(float(budget), 2),
            currency="USD",
            campaign_name=campaign_name,
            dry_run=dry_run,
            status="dry_run" if dry_run else "planned",
            quality=bundle.quality,
            reasons=bundle.reasons,
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "product_id": self.product_id,
                "product_name": self.product_name,
                "creative_id": self.creative_id,
                "platform": self.platform,
                "budget": self.budget,
                "currency": self.currency,
                "campaign_name": self.campaign_name,
                "dry_run": self.dry_run,
                "status": self.status,
                "campaign_id": self.campaign_id,
                "adgroup_id": self.adgroup_id,
                "ad_ids": list(self.ad_ids),
                "quality": _quality_dict(self.quality),
                "reasons": list(self.reasons),
            }
        )
        return data


@dataclass
class CampaignOutcome(BaseArtifact):
    artifact_type: str = field(default="campaign_outcome")
    product_id: str = ""
    product_name: str = ""
    creative_id: str = ""
    campaign_id: str = ""
    adgroup_id: str = ""
    ad_ids: tuple[str, ...] = ()
    spend: float = 0.0
    revenue: float = 0.0
    impressions: int = 0
    clicks: int = 0
    conversions: int = 0
    refunds: float = 0.0
    currency: str = "USD"
    roas: float = 0.0
    quality: DataQuality = field(default_factory=DataQuality)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_metrics(
        cls,
        plan: LaunchPlan,
        metrics: dict[str, Any],
        *,
        quality: DataQuality | None = None,
        workspace: str = "commerce",
    ) -> "CampaignOutcome":
        spend = float(metrics.get("spend", 0.0) or 0.0)
        revenue = float(metrics.get("revenue", 0.0) or 0.0)
        impressions = int(metrics.get("impressions", 0) or 0)
        clicks = int(metrics.get("clicks", 0) or 0)
        conversions = int(metrics.get("conversions", metrics.get("conversion", 0)) or 0)
        refunds = float(metrics.get("refunds", 0.0) or 0.0)
        adjusted_revenue = max(revenue - refunds, 0.0)
        roas = round(adjusted_revenue / spend, 6) if spend else 0.0
        outcome_id = _stable_id("campaign_outcome", plan.campaign_id or plan.artifact_id, plan.creative_id, impressions, clicks, conversions)
        return cls(
            artifact_id=outcome_id,
            workspace=workspace,
            parent_ids=[plan.artifact_id],
            product_id=plan.product_id,
            product_name=plan.product_name,
            creative_id=plan.creative_id,
            campaign_id=plan.campaign_id,
            adgroup_id=plan.adgroup_id,
            ad_ids=plan.ad_ids,
            spend=spend,
            revenue=revenue,
            impressions=impressions,
            clicks=clicks,
            conversions=conversions,
            refunds=refunds,
            currency=str(metrics.get("currency", plan.currency)),
            roas=roas,
            quality=quality or plan.quality,
            metadata=dict(metrics.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "product_id": self.product_id,
                "product_name": self.product_name,
                "creative_id": self.creative_id,
                "campaign_id": self.campaign_id,
                "adgroup_id": self.adgroup_id,
                "ad_ids": list(self.ad_ids),
                "spend": self.spend,
                "revenue": self.revenue,
                "impressions": self.impressions,
                "clicks": self.clicks,
                "conversions": self.conversions,
                "refunds": self.refunds,
                "currency": self.currency,
                "roas": self.roas,
                "quality": _quality_dict(self.quality),
                "metadata": self.metadata,
            }
        )
        return data


@dataclass
class CommerceCycleReport(BaseArtifact):
    artifact_type: str = field(default="commerce_cycle_report")
    started_at: float = field(default_factory=time.time)
    finished_at: float = field(default_factory=time.time)
    dry_run: bool = True
    total_signals: int = 0
    ranked_opportunities: tuple[RankedOpportunity, ...] = ()
    creative_bundles: tuple[CreativeBundle, ...] = ()
    launch_plans: tuple[LaunchPlan, ...] = ()
    outcomes: tuple[CampaignOutcome, ...] = ()
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "dry_run": self.dry_run,
                "total_signals": self.total_signals,
                "ranked_opportunities": [item.to_dict() for item in self.ranked_opportunities],
                "creative_bundles": [item.to_dict() for item in self.creative_bundles],
                "launch_plans": [item.to_dict() for item in self.launch_plans],
                "outcomes": [item.to_dict() for item in self.outcomes],
                "summary": self.summary,
            }
        )
        return data


def build_product_candidate(signal: CommerceSignal, *, selling_price: float = 0.0) -> ProductCandidate:
    return ProductCandidate(
        product_id=signal.product_id or signal.product_name or signal.signal_id,
        name=signal.product_name or signal.product_id or signal.signal_id,
        currency=str(signal.metadata.get("currency") or "USD").upper(),
        selling_price=float(selling_price),
        source_signal_ids=(signal.signal_id,),
        quality=signal.quality,
    )


def build_supplier_offer(
    signal: CommerceSignal,
    *,
    unit_cost: float = 0.0,
    shipping_cost: float = 0.0,
    inventory_units: int | None = None,
    fulfillment_days: int | None = None,
    source_ref: str = "",
) -> SupplierOffer:
    return SupplierOffer(
        supplier_id=_stable_id("supplier_offer", signal.product_id or signal.product_name, source_ref or signal.signal_id)[:24],
        product_id=signal.product_id or signal.product_name or signal.signal_id,
        unit_cost=float(unit_cost),
        shipping_cost=float(shipping_cost),
        fulfillment_days=fulfillment_days,
        inventory_units=inventory_units,
        currency="USD",
        quality=signal.quality,
    )
