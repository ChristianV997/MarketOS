"""Feedback reconciliation for the commerce loop."""
from __future__ import annotations

from dataclasses import dataclass, field
import threading
from typing import Any, Iterable

from evaluation import CampaignCandidate, CampaignObservation, DataQuality, evaluate_campaign

from backend.vector.memory.campaign_memory import CampaignMemory
from backend.vector.memory.reinforcement_memory import ReinforcementMemory
from backend.vector.memory.signal_memory import SignalMemory

from .contracts import CampaignOutcome, CreativeBundle, LaunchPlan

try:
    from prometheus_client import Counter

    _prom_feedback_records = Counter(
        "marketos_feedback_records",
        "Commerce feedback observations processed",
    )
    _prom_feedback_duplicates = Counter(
        "marketos_feedback_duplicates",
        "Commerce feedback observations ignored as duplicates",
    )
except ImportError:
    _prom_feedback_records = None
    _prom_feedback_duplicates = None


_PROCESSED_OBSERVATIONS: set[str] = set()
_OBSERVATION_LOCK = threading.Lock()


def _record_campaign_lineage_outcome(plan: LaunchPlan, outcome: CampaignOutcome) -> None:
    """Update the durable launch artifact with an attributed outcome."""
    # An initial platform response is often incomplete or unattributed. Do not
    # mark the campaign final until an actually attributable observation arrives.
    if plan.dry_run or not outcome.campaign_id or not outcome.quality.is_live_attributed:
        return
    try:
        from backend.contracts.registry import get_registry

        registry = get_registry()
        artifact_id = f"commerce-campaign:{outcome.campaign_id}"
        asset = registry.get(artifact_id)
        if asset is None or not hasattr(asset, "with_outcome"):
            return
        registry.register(asset.with_outcome(outcome.roas))
    except Exception:
        return


def _quality_dict(quality: DataQuality) -> dict[str, Any]:
    return {
        "provenance": quality.provenance,
        "attribution": quality.attribution,
        "completeness": quality.completeness,
        "observed_at": quality.observed_at.isoformat(),
        "source_ref": quality.source_ref,
    }


def _observation_dict(observation: CampaignObservation) -> dict[str, Any]:
    return {
        "observation_id": observation.observation_id,
        "campaign_id": observation.campaign_id,
        "product_id": observation.product_id,
        "creative_id": observation.creative_id,
        "spend": observation.spend,
        "revenue": observation.revenue,
        "impressions": observation.impressions,
        "clicks": observation.clicks,
        "conversions": observation.conversions,
        "refunds": observation.refunds,
        "currency": observation.currency,
        "quality": _quality_dict(observation.quality),
        "metadata": observation.metadata,
    }


def _observation_from_outcome(outcome: CampaignOutcome) -> CampaignObservation:
    return CampaignObservation(
        observation_id=outcome.artifact_id,
        campaign_id=outcome.campaign_id or outcome.artifact_id,
        product_id=outcome.product_id,
        creative_id=outcome.creative_id,
        spend=outcome.spend,
        revenue=outcome.revenue,
        impressions=outcome.impressions,
        clicks=outcome.clicks,
        conversions=outcome.conversions,
        refunds=outcome.refunds,
        currency=outcome.currency,
        quality=outcome.quality,
        metadata=dict(outcome.metadata),
    )


def observation_from_webhook(payload: dict[str, Any], *, source: str) -> CampaignObservation | None:
    """Normalize a provider metrics event without inventing missing values."""
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else payload
    campaign_id = str(payload.get("campaign_id") or metrics.get("campaign_id") or "").strip()
    observation_id = str(payload.get("id") or payload.get("event_id") or "").strip()
    if not campaign_id or not observation_id:
        return None
    try:
        return CampaignObservation(
            observation_id=observation_id,
            campaign_id=campaign_id,
            product_id=str(payload.get("product_id") or metrics.get("product_id") or ""),
            creative_id=str(payload.get("creative_id") or metrics.get("creative_id") or ""),
            spend=float(metrics.get("spend", 0.0) or 0.0),
            revenue=float(metrics.get("revenue", 0.0) or 0.0),
            impressions=int(metrics.get("impressions", 0) or 0),
            clicks=int(metrics.get("clicks", 0) or 0),
            conversions=int(metrics.get("conversions", metrics.get("conversion", 0)) or 0),
            refunds=float(metrics.get("refunds", 0.0) or 0.0),
            currency=str(metrics.get("currency", "USD")),
            quality=DataQuality(provenance="live", attribution="attributed", source_ref=f"{source}:{observation_id}"),
            metadata={"source": source, "event_type": payload.get("type", "")},
        )
    except (TypeError, ValueError):
        return None


@dataclass
class FeedbackRecorder:
    """Persist outcomes into semantic and reinforcement memory."""

    campaign_memory: CampaignMemory = field(default_factory=CampaignMemory)
    reinforcement_memory: ReinforcementMemory = field(default_factory=ReinforcementMemory)
    signal_memory: SignalMemory = field(default_factory=SignalMemory)

    def record(self, bundle: CreativeBundle, plan: LaunchPlan, outcome: CampaignOutcome) -> dict[str, Any]:
        observation = _observation_from_outcome(outcome)
        with _OBSERVATION_LOCK:
            if observation.observation_id in _PROCESSED_OBSERVATIONS:
                if _prom_feedback_duplicates is not None:
                    _prom_feedback_duplicates.inc()
                return {
                    "observation": _observation_dict(observation),
                    "readiness": {},
                    "deduplicated": True,
                }
            _PROCESSED_OBSERVATIONS.add(observation.observation_id)
        readiness = evaluate_campaign(
            CampaignCandidate(
                campaign_id=plan.campaign_id or plan.artifact_id,
                product_id=plan.product_id,
                creative_id=plan.creative_id,
                platform=plan.platform,
                budget=plan.budget,
                currency=plan.currency,
                quality=outcome.quality,
            ),
            [observation],
        )

        if outcome.campaign_id:
            self.campaign_memory.index_campaign(
                campaign_id=outcome.campaign_id,
                product=outcome.product_name or plan.product_name,
                hook=bundle.hook,
                angle=bundle.angle,
                roas=outcome.roas,
                phase="commerce",
                spend=outcome.spend,
                revenue=outcome.revenue,
                creative_id=outcome.creative_id,
            )

        self.reinforcement_memory.record_outcome(
            hook=bundle.hook,
            angle=bundle.angle,
            product=outcome.product_name or plan.product_name,
            roas=outcome.roas,
            phase="commerce",
            campaign_id=outcome.campaign_id,
            creative_id=outcome.creative_id,
        )

        self.signal_memory.index_keyword(
            outcome.product_name or plan.product_name,
            source="commerce_feedback",
            campaign_id=outcome.campaign_id,
            roas=outcome.roas,
        )
        _record_campaign_lineage_outcome(plan, outcome)

        if _prom_feedback_records is not None:
            _prom_feedback_records.inc()

        return {
            "observation": _observation_dict(observation),
            "readiness": readiness.to_dict(),
            "deduplicated": False,
        }
