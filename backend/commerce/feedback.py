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
    _prom_feedback_failures = Counter(
        "marketos_feedback_failures",
        "Commerce feedback observations that failed to persist",
    )
except ImportError:
    _prom_feedback_records = None
    _prom_feedback_duplicates = None
    _prom_feedback_failures = None


_PROCESSED_OBSERVATIONS: set[str] = set()
_OBSERVATION_LOCK = threading.Lock()


def _release_observation(observation_id: str) -> None:
    with _OBSERVATION_LOCK:
        _PROCESSED_OBSERVATIONS.discard(observation_id)


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
    if source == "medusa":
        return _medusa_observation_from_webhook(payload)
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


def observation_from_metrics(
    *,
    observation_id: str,
    source: str,
    campaign_id: str,
    product_id: str = "",
    creative_id: str = "",
    spend: float = 0.0,
    revenue: float = 0.0,
    conversions: int = 0,
    clicks: int = 0,
    impressions: int = 0,
    currency: str = "USD",
    metadata: dict[str, Any] | None = None,
) -> CampaignObservation | None:
    """Build one live, attributed observation from a polling result.

    Polling APIs do not provide webhook-shaped envelopes, so they use this
    small shared boundary instead of teaching each provider how to construct
    evaluation records.  Callers must provide a stable observation ID (for
    example, a provider/campaign/time bucket); this is what makes retries and
    overlapping polling windows safe for ``FeedbackRecorder``.
    """
    campaign_id = str(campaign_id or "").strip()
    observation_id = str(observation_id or "").strip()
    if not campaign_id or not observation_id:
        return None
    try:
        spend_value = max(0.0, float(spend or 0.0))
        revenue_value = max(0.0, float(revenue or 0.0))
        conversions_value = max(0, int(conversions or 0))
        clicks_value = max(0, int(clicks or 0))
        impressions_value = max(0, int(impressions or 0))
    except (TypeError, ValueError):
        return None
    if spend_value <= 0.0 or (revenue_value <= 0.0 and conversions_value <= 0):
        # A spend-only polling row is useful for profitability dashboards but
        # is not enough evidence to train campaign ranking.
        return None
    return CampaignObservation(
        observation_id=observation_id,
        campaign_id=campaign_id,
        product_id=str(product_id or ""),
        creative_id=str(creative_id or ""),
        spend=spend_value,
        revenue=revenue_value,
        conversions=conversions_value,
        clicks=clicks_value,
        impressions=impressions_value,
        currency=str(currency or "USD").upper(),
        quality=DataQuality(
            provenance="live",
            attribution="attributed",
            completeness="partial",
            source_ref=f"{source}:{observation_id}",
        ),
        metadata={"source": source, **(metadata or {})},
    )


def _medusa_observation_from_webhook(payload: dict[str, Any]) -> CampaignObservation | None:
    """Map Medusa revenue only when order metadata proves MarketOS lineage."""
    event_id = str(payload.get("id") or payload.get("event_id") or payload.get("webhook_id") or "").strip()
    event_type = str(payload.get("type") or payload.get("event_type") or "").strip().lower()
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    order = payload.get("order") if isinstance(payload.get("order"), dict) else data.get("order")
    order = order if isinstance(order, dict) else data
    metadata = order.get("metadata") if isinstance(order.get("metadata"), dict) else {}
    campaign_id = str(metadata.get("marketos_campaign_id") or "").strip()
    if not event_id or not campaign_id:
        return None
    product_id = str(metadata.get("marketos_product_id") or "").strip()
    creative_id = str(metadata.get("marketos_creative_id") or "").strip()
    if not product_id:
        items = order.get("items") if isinstance(order.get("items"), list) else []
        first = items[0] if items and isinstance(items[0], dict) else {}
        product_id = str(first.get("variant_id") or first.get("product_id") or "").strip()
    refund = order.get("refund") if isinstance(order.get("refund"), dict) else data.get("refund")
    refund = refund if isinstance(refund, dict) else {}
    is_refund = "refund" in event_type
    raw_amount = refund.get("amount") if is_refund else order.get("total", order.get("subtotal", 0.0))
    try:
        amount = max(0.0, float(raw_amount or 0.0))
    except (TypeError, ValueError):
        return None
    return CampaignObservation(
        observation_id=event_id,
        campaign_id=campaign_id,
        product_id=product_id,
        creative_id=creative_id,
        revenue=0.0 if is_refund else amount,
        conversions=0 if is_refund else 1,
        refunds=amount if is_refund else 0.0,
        currency=str(order.get("currency_code") or order.get("currency") or "USD").upper(),
        quality=DataQuality(provenance="live", attribution="attributed", source_ref=f"medusa:{event_id}"),
        metadata={"source": "medusa", "event_type": event_type, "order_id": str(order.get("id") or data.get("id") or ""), "lineage": "order_metadata"},
    )


@dataclass
class FeedbackRecorder:
    """Persist outcomes into semantic and reinforcement memory."""

    campaign_memory: CampaignMemory = field(default_factory=CampaignMemory)
    reinforcement_memory: ReinforcementMemory = field(default_factory=ReinforcementMemory)
    signal_memory: SignalMemory = field(default_factory=SignalMemory)

    def record_observation(self, observation: CampaignObservation) -> dict[str, Any]:
        """Persist an attributed provider observation without a launch bundle.

        Webhook events often arrive after the original process has ended, so
        they cannot reliably reconstruct the full creative/launch objects.
        Store only the evidence available in the observation and never infer
        missing creative metadata.
        """
        with _OBSERVATION_LOCK:
            if observation.observation_id in _PROCESSED_OBSERVATIONS:
                if _prom_feedback_duplicates is not None:
                    _prom_feedback_duplicates.inc()
                return {"observation_id": observation.observation_id, "deduplicated": True}
            _PROCESSED_OBSERVATIONS.add(observation.observation_id)
        metadata = dict(observation.metadata)
        product = observation.product_id or observation.campaign_id
        roas = observation.revenue / observation.spend if observation.spend > 0 else 0.0
        hook = str(metadata.get("hook", ""))
        angle = str(metadata.get("angle", ""))
        try:
            self.campaign_memory.index_campaign(
                campaign_id=observation.campaign_id,
                product=product,
                hook=hook,
                angle=angle,
                roas=roas,
                phase="webhook_feedback",
                spend=observation.spend,
                revenue=observation.revenue,
                creative_id=observation.creative_id,
            )
            self.reinforcement_memory.record_outcome(
                hook=hook,
                angle=angle,
                product=product,
                roas=roas,
                phase="webhook_feedback",
                campaign_id=observation.campaign_id,
                creative_id=observation.creative_id,
            )
            self.signal_memory.index_keyword(product, source="commerce_webhook_feedback", campaign_id=observation.campaign_id, roas=roas)
        except Exception as exc:
            _release_observation(observation.observation_id)
            if _prom_feedback_failures is not None:
                _prom_feedback_failures.inc()
            return {"observation_id": observation.observation_id, "deduplicated": False, "recorded": False, "error": str(exc)}
        if _prom_feedback_records is not None:
            _prom_feedback_records.inc()
        return {"observation_id": observation.observation_id, "deduplicated": False, "recorded": True}


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
        try:
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
        except Exception:
            _release_observation(observation.observation_id)
            if _prom_feedback_failures is not None:
                _prom_feedback_failures.inc()
            raise

        if _prom_feedback_records is not None:
            _prom_feedback_records.inc()

        return {
            "observation": _observation_dict(observation),
            "readiness": readiness.to_dict(),
            "deduplicated": False,
        }


webhook_feedback_recorder = FeedbackRecorder()
