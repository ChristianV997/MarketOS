"""Launch orchestration for commerce bundles."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Callable

from evaluation.contracts import DataQuality

from .contracts import CampaignOutcome, CreativeBundle, LaunchPlan

LaunchProvider = Callable[..., dict[str, Any]]
MetricsProvider = Callable[[list[str]], dict[str, Any] | tuple[dict[str, Any], DataQuality]]


def _default_launch_backend() -> tuple[LaunchProvider, LaunchProvider, LaunchProvider, MetricsProvider]:
    """Build the canonical TikTok-backed launch providers.

    The wrappers preserve LaunchExecutor's dictionary contract while keeping
    all TikTok HTTP behavior in ``backend.integrations.tiktok_ads``.
    """
    from backend.integrations import tiktok_ads

    def _campaign(*, name: str, budget: float) -> dict[str, Any]:
        return {"campaign_id": tiktok_ads.create_campaign(name=name, budget=budget)}

    def _ad_group(*, campaign_id: str, name: str, budget: float) -> dict[str, Any]:
        return {"adgroup_id": tiktok_ads.create_ad_group(campaign_id, name=name, daily_budget=budget)}

    def _ad(*, adgroup_id: str, creative: dict[str, Any]) -> dict[str, Any]:
        canonical = json.dumps(creative, sort_keys=True, separators=(",", ":"))
        creative_id = f"creative_{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:16]}"
        return {"ad_id": tiktok_ads.create_ad(
            adgroup_id=adgroup_id,
            creative_id=creative_id,
            name=str(creative.get("headline") or "MarketOS Ad"),
            hook=str(creative.get("body") or ""),
            angle=str(creative.get("cta") or ""),
        )}

    def _metrics(campaign_ids: list[str]) -> dict[str, Any]:
        return tiktok_ads.get_metrics(campaign_ids)

    return _campaign, _ad_group, _ad, _metrics


def _normalise_metrics(result: dict[str, Any] | tuple[dict[str, Any], DataQuality], *, dry_run: bool) -> tuple[dict[str, Any], DataQuality]:
    if isinstance(result, tuple):
        metrics, quality = result
        return metrics, quality
    provenance = "simulated" if dry_run else "unknown"
    attribution = "unattributed" if dry_run else "unknown"
    return result, DataQuality(provenance=provenance, attribution=attribution)


def _register_campaign_lineage(bundle: CreativeBundle, plan: LaunchPlan) -> None:
    """Persist the launch lineage so delayed platform metrics can be reconciled.

    The shared artifact registry emits to the replay/event store.  Keeping the
    key deterministic by campaign id means a later outcome updates this exact
    record rather than creating an unrelated analytics row.
    """
    if plan.dry_run or not plan.campaign_id:
        return
    try:
        from backend.contracts.campaign import CampaignAsset
        from backend.contracts.registry import get_registry

        asset = CampaignAsset(
            artifact_id=f"commerce-campaign:{plan.campaign_id}",
            workspace=plan.workspace,
            parent_ids=[bundle.artifact_id, plan.artifact_id],
            campaign_id=plan.campaign_id,
            adgroup_id=plan.adgroup_id,
            ad_ids=list(plan.ad_ids),
            product=plan.product_name,
            hook=bundle.hook,
            angle=bundle.angle,
            phase="commerce",
            budget=plan.budget,
            launched_at=plan.created_at,
            dry_run=False,
            metadata={
                "product_id": plan.product_id,
                "creative_id": plan.creative_id,
                "platform": plan.platform,
                "currency": plan.currency,
            },
        )
        get_registry().register(asset)
    except Exception:
        # A platform launch must not be rolled back because optional replay
        # infrastructure is unavailable; the caller still has its plan/outcome.
        return


def _launch_state_id(plan: LaunchPlan) -> str:
    return f"commerce-launch:{plan.artifact_id}"


def _get_launch_state(plan: LaunchPlan):
    try:
        from backend.contracts.registry import get_registry
        return get_registry().get(_launch_state_id(plan))
    except Exception:
        return None


def _save_launch_state(
    bundle: CreativeBundle,
    plan: LaunchPlan,
    *,
    status: str,
    campaign_id: str = "",
    adgroup_id: str = "",
    ad_ids: list[str] | None = None,
    error: str | None = None,
) -> None:
    """Checkpoint launch progress in the existing artifact registry."""
    try:
        from backend.contracts.campaign import CampaignAsset
        from backend.contracts.registry import get_registry

        current = _get_launch_state(plan)
        if current is not None and hasattr(current, "with_launch_state"):
            get_registry().register(current.with_launch_state(
                status=status,
                campaign_id=campaign_id or current.campaign_id,
                adgroup_id=adgroup_id or current.adgroup_id,
                ad_ids=ad_ids if ad_ids is not None else list(current.ad_ids),
                error=error,
            ))
            return
        get_registry().register(CampaignAsset(
            artifact_id=_launch_state_id(plan),
            workspace=plan.workspace,
            parent_ids=[bundle.artifact_id, plan.artifact_id],
            campaign_id=campaign_id,
            adgroup_id=adgroup_id,
            ad_ids=list(ad_ids or ()),
            product=plan.product_name,
            phase="commerce",
            budget=plan.budget,
            launched_at=plan.created_at,
            dry_run=False,
            launch_status=status,
            metadata={"launch_key": plan.artifact_id, "product_id": plan.product_id, "creative_id": plan.creative_id},
        ))
    except Exception:
        # The platform operation remains authoritative if optional persistence
        # is unavailable; the next retry will still be protected in-process.
        return
@dataclass
class LaunchExecutor:
    """Create campaigns, ad groups, ads, and outcome snapshots."""

    create_campaign: LaunchProvider | None = None
    create_ad_group: LaunchProvider | None = None
    create_ad: LaunchProvider | None = None
    metrics_provider: MetricsProvider | None = None

    def __post_init__(self) -> None:
        if not (self.create_campaign and self.create_ad_group and self.create_ad and self.metrics_provider):
            campaign, ad_group, ad, metrics = _default_launch_backend()
            self.create_campaign = self.create_campaign or campaign
            self.create_ad_group = self.create_ad_group or ad_group
            self.create_ad = self.create_ad or ad
            self.metrics_provider = self.metrics_provider or metrics

    def execute(self, bundle: CreativeBundle, *, budget: float = 20.0, dry_run: bool = True) -> tuple[LaunchPlan, CampaignOutcome]:
        plan = LaunchPlan.from_bundle(bundle, budget=budget, dry_run=dry_run)

        if dry_run:
            outcome = CampaignOutcome.from_metrics(
                plan,
                {"spend": 0.0, "revenue": 0.0, "impressions": 0, "clicks": 0, "conversions": 0, "metadata": {"dry_run": True}},
                quality=DataQuality(provenance="simulated", attribution="unattributed"),
            )
            return plan, outcome

        state = _get_launch_state(plan)
        campaign_id = str(getattr(state, "campaign_id", "") or "")
        adgroup_id = str(getattr(state, "adgroup_id", "") or "")
        ad_ids = list(getattr(state, "ad_ids", ()) or ())
        _save_launch_state(bundle, plan, status=getattr(state, "launch_status", "planned"))

        if not campaign_id:
            campaign_response = self.create_campaign(name=plan.campaign_name, budget=plan.budget)
            campaign_id = str(campaign_response.get("campaign_id", "") or "")
            if not campaign_id:
                _save_launch_state(bundle, plan, status="campaign_failed", error="campaign provider returned no campaign_id")
                raise RuntimeError("campaign provider returned no campaign_id")
            _save_launch_state(bundle, plan, status="campaign_created", campaign_id=campaign_id)

        if not adgroup_id:
            adgroup_response = self.create_ad_group(
                campaign_id=campaign_id,
                name=f"{bundle.product_name[:32]}::{bundle.creative_id[:8]}",
                budget=plan.budget,
            )
            adgroup_id = str(adgroup_response.get("adgroup_id", "") or "")
            if not adgroup_id:
                _save_launch_state(bundle, plan, status="adgroup_failed", campaign_id=campaign_id, error="ad group provider returned no adgroup_id")
                raise RuntimeError("ad group provider returned no adgroup_id")
            _save_launch_state(bundle, plan, status="adgroup_created", campaign_id=campaign_id, adgroup_id=adgroup_id)

        if not ad_ids:
            ad_response = self.create_ad(
                adgroup_id=adgroup_id,
                creative={"headline": bundle.headline, "body": bundle.primary_text, "cta": bundle.cta},
            )
            ad_id = str(ad_response.get("ad_id", "") or "")
            if not ad_id:
                _save_launch_state(bundle, plan, status="ad_failed", campaign_id=campaign_id, adgroup_id=adgroup_id, error="ad provider returned no ad_id")
                raise RuntimeError("ad provider returned no ad_id")
            ad_ids = [ad_id]
            _save_launch_state(bundle, plan, status="ad_created", campaign_id=campaign_id, adgroup_id=adgroup_id, ad_ids=ad_ids)
        ad_id = ad_ids[0] if ad_ids else ""

        plan = LaunchPlan(
            artifact_id=plan.artifact_id,
            workspace=plan.workspace,
            parent_ids=plan.parent_ids,
            product_id=plan.product_id,
            product_name=plan.product_name,
            creative_id=plan.creative_id,
            platform=plan.platform,
            budget=plan.budget,
            currency=plan.currency,
            campaign_name=plan.campaign_name,
            dry_run=False,
            status="launched",
            campaign_id=campaign_id,
            adgroup_id=adgroup_id,
            ad_ids=tuple(ad_ids),
            quality=DataQuality(provenance="unknown", attribution="unknown"),
            reasons=plan.reasons,
        )
        _register_campaign_lineage(bundle, plan)

        metrics_raw = self.metrics_provider([campaign_id]) if campaign_id else {}
        metrics, quality = _normalise_metrics(metrics_raw, dry_run=False)
        metrics = dict(metrics)
        metrics.setdefault("metadata", {})
        metrics["metadata"] = {**metrics["metadata"], "campaign_id": campaign_id, "adgroup_id": adgroup_id, "ad_id": ad_id}

        outcome = CampaignOutcome.from_metrics(plan, metrics, quality=quality)
        _save_launch_state(bundle, plan, status="completed", campaign_id=campaign_id, adgroup_id=adgroup_id, ad_ids=ad_ids)
        return plan, outcome
