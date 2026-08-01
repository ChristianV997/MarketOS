"""End-to-end commerce execution loop."""
from __future__ import annotations

import time
import asyncio
import os
from dataclasses import replace
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from evaluation.contracts import ProductCandidate, SupplierOffer

from core.signals import signal_engine

from .contracts import (
    CampaignOutcome,
    CommerceCycleReport,
    CommerceSignal,
    CreativeBundle,
    LaunchPlan,
    RankedOpportunity,
    _quality_from_dict,
)
from .creative import CreativeComposer
from .feedback import FeedbackRecorder
from .launch import LaunchExecutor
from .scoring import OpportunityScorer
from . import metrics as commerce_metrics


def _key_lookup(*keys: str):
    def _resolver(items: Mapping[str, Any] | None, fallback: str) -> Any:
        if not items:
            return None
        for key in keys:
            if key in items:
                return items[key]
        return items.get(fallback)
    return _resolver


def _normalize_product_map(products: Mapping[str, ProductCandidate | dict[str, Any]] | None) -> dict[str, ProductCandidate]:
    resolved: dict[str, ProductCandidate] = {}
    if not products:
        return resolved
    for key, value in products.items():
        if isinstance(value, ProductCandidate):
            resolved[key] = value
            continue
        resolved[key] = ProductCandidate(
            product_id=str(value.get("product_id") or key),
            name=str(value.get("name") or value.get("product_name") or key),
            currency=str(value.get("currency") or "USD"),
            selling_price=float(value.get("selling_price", value.get("price", 0.0)) or 0.0),
            source_signal_ids=tuple(value.get("source_signal_ids") or ()),
            quality=_quality_from_dict(value.get("quality")),
        )
    return resolved


def _normalize_offer_map(offers: Mapping[str, SupplierOffer | dict[str, Any]] | None) -> dict[str, SupplierOffer]:
    resolved: dict[str, SupplierOffer] = {}
    if not offers:
        return resolved
    for key, value in offers.items():
        if isinstance(value, SupplierOffer):
            resolved[key] = value
            continue
        resolved[key] = SupplierOffer(
            supplier_id=str(value.get("supplier_id") or key),
            product_id=str(value.get("product_id") or key),
            unit_cost=float(value.get("unit_cost", 0.0) or 0.0),
            shipping_cost=float(value.get("shipping_cost", 0.0) or 0.0),
            fulfillment_days=value.get("fulfillment_days"),
            inventory_units=value.get("inventory_units"),
            currency=str(value.get("currency") or "USD"),
            quality=_quality_from_dict(value.get("quality")),
        )
    return resolved


@dataclass
class CommerceLoop:
    """Coordinate the commerce truth loop from signal to feedback."""

    scorer: OpportunityScorer = field(default_factory=OpportunityScorer)
    composer: CreativeComposer = field(default_factory=CreativeComposer)
    launcher: LaunchExecutor = field(default_factory=LaunchExecutor)
    feedback: FeedbackRecorder = field(default_factory=FeedbackRecorder)
    signal_source: Any = field(default_factory=lambda: signal_engine)

    def collect_signals(self, signals: Iterable[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        if signals is not None:
            return [dict(item) for item in signals]
        return list(self.signal_source.get())

    def rank(
        self,
        signals: Iterable[dict[str, Any] | CommerceSignal],
        *,
        products: Mapping[str, ProductCandidate | dict[str, Any]] | None = None,
        offers: Mapping[str, SupplierOffer | dict[str, Any]] | None = None,
        top_k: int = 10,
    ) -> list[RankedOpportunity]:
        return self.scorer.rank(
            signals,
            product_overrides=_normalize_product_map(products),
            offer_overrides=_normalize_offer_map(offers),
            top_k=top_k,
        )

    def compose(self, opportunities: Iterable[RankedOpportunity]) -> list[CreativeBundle]:
        return self.composer.compose_batch(opportunities)

    def quality_gate(self, creatives: Iterable[CreativeBundle]) -> tuple[list[CreativeBundle], list[str]]:
        """Optionally run typed campaign QA before launch, failing closed."""
        bundles = list(creatives)
        if os.getenv("MARKETOS_AGENT_QA_ENABLED", "false").lower() != "true":
            return bundles, []
        from backend.agents.domain_agents import CampaignQARequest, run_campaign_qa
        failures: list[str] = []
        checked: list[CreativeBundle] = []
        for bundle in bundles:
            try:
                result = asyncio.run(run_campaign_qa(CampaignQARequest(
                    product_id=bundle.product_id,
                    creative_id=bundle.creative_id,
                    platform=os.getenv("MARKETOS_DEFAULT_AD_PLATFORM", "tiktok"),
                    copy_text=bundle.primary_text or bundle.script,
                    dry_run=True,
                )))
                if not result.approved:
                    checked.append(replace(bundle, reasons=tuple(sorted(set((*bundle.reasons, "agent_qa_rejected", "not_launchable"))))))
                    failures.append(f"{bundle.creative_id}:rejected")
                else:
                    checked.append(bundle)
            except Exception as exc:
                checked.append(replace(bundle, reasons=tuple(sorted(set((*bundle.reasons, "agent_qa_unavailable", "not_launchable"))))))
                failures.append(f"{bundle.creative_id}:unavailable:{exc}")
        return checked, failures

    def launch(
        self,
        creatives: Iterable[CreativeBundle],
        *,
        budget: float = 20.0,
        dry_run: bool = True,
    ) -> tuple[list[LaunchPlan], list[CampaignOutcome]]:
        plans: list[LaunchPlan] = []
        outcomes: list[CampaignOutcome] = []
        for bundle in creatives:
            if bundle.reasons and "not_launchable" in bundle.reasons:
                continue
            try:
                plan, outcome = self.launcher.execute(bundle, budget=budget, dry_run=dry_run)
            except Exception as exc:
                commerce_metrics.launches_total.labels(status="failed", dry_run=str(dry_run).lower()).inc()
                # Keep the batch alive; the caller records the bounded failure
                # in the cycle summary without exposing product content as a
                # metric label.
                plans.append(LaunchPlan.from_bundle(bundle, budget=budget, dry_run=dry_run))
                outcomes.append(CampaignOutcome.from_metrics(
                    plans[-1],
                    {"metadata": {"launch_error": type(exc).__name__}},
                    quality=_quality_from_dict({"provenance": "unknown", "attribution": "unknown"}),
                ))
                continue
            plans.append(plan)
            outcomes.append(outcome)
            commerce_metrics.launches_total.labels(status="success", dry_run=str(dry_run).lower()).inc()
        return plans, outcomes

    def publish_creatives(
        self,
        creatives: Iterable[CreativeBundle],
        *,
        publisher: Any | None = None,
        dry_run: bool = True,
        approval_state: str = "not_required",
    ) -> list[dict[str, Any]]:
        """Publish approved creative bundles through the configured adapter."""
        from backend.integrations.postiz import publisher as default_publisher
        from backend.contracts.adapters import SidecarContext
        target = publisher or default_publisher
        records: list[dict[str, Any]] = []
        for bundle in creatives:
            if "not_launchable" in bundle.reasons:
                continue
            context = SidecarContext(
                workspace_id=bundle.workspace,
                run_id=bundle.artifact_id,
                artifact_id=bundle.artifact_id,
                parent_ids=tuple(bundle.parent_ids),
                idempotency_key=f"publish:{bundle.creative_id}",
                dry_run=dry_run,
                approval_state=approval_state,
            )
            result = target.publish_bundle(bundle, context=context)
            records.append(dict(result))
        return records

    def reconcile(
        self,
        creatives: Iterable[CreativeBundle],
        plans: Iterable[LaunchPlan],
        outcomes: Iterable[CampaignOutcome],
    ) -> list[dict[str, Any]]:
        creative_map = {bundle.creative_id: bundle for bundle in creatives}
        plan_map = {plan.artifact_id: plan for plan in plans}
        records: list[dict[str, Any]] = []
        for outcome in outcomes:
            if (outcome.metadata or {}).get("launch_error"):
                commerce_metrics.feedback_total.labels(status="skipped_launch_failure").inc()
                continue
            plan = next((plan for plan in plans if plan.campaign_id == outcome.campaign_id or plan.creative_id == outcome.creative_id), None)
            if plan is None:
                plan = plan_map.get(outcome.parent_ids[0] if outcome.parent_ids else "")
            bundle = creative_map.get(outcome.creative_id)
            if plan is None or bundle is None:
                continue
            records.append(self.feedback.record(bundle, plan, outcome))
        return records

    def run_cycle(
        self,
        signals: Iterable[dict[str, Any]] | None = None,
        *,
        products: Mapping[str, ProductCandidate | dict[str, Any]] | None = None,
        offers: Mapping[str, SupplierOffer | dict[str, Any]] | None = None,
        top_k: int = 5,
        budget: float = 20.0,
        dry_run: bool = True,
    ) -> CommerceCycleReport:
        started_at = time.time()
        timings: dict[str, float] = {}

        def timed(phase: str, operation):
            phase_started = time.perf_counter()
            try:
                return operation()
            finally:
                duration = time.perf_counter() - phase_started
                timings[phase] = round(duration, 6)
                commerce_metrics.phase_duration_seconds.labels(phase=phase).observe(duration)

        raw_signals = timed("signal_collection", lambda: self.collect_signals(signals))
        normalized_signals = timed("normalization", lambda: [CommerceSignal.from_signal(signal) for signal in raw_signals])
        ranked = timed("ranking", lambda: self.rank(normalized_signals, products=products, offers=offers, top_k=top_k))
        creatives = timed("creative_generation", lambda: self.compose(ranked[:top_k]))
        creatives, qa_failures = timed("quality_gate", lambda: self.quality_gate(creatives))
        plans, outcomes = timed("launch", lambda: self.launch(creatives, budget=budget, dry_run=dry_run))
        feedback = timed("feedback", lambda: self.reconcile(creatives, plans, outcomes))
        finished_at = time.time()

        summary = {
            "signals_collected": len(normalized_signals),
            "ranked": len(ranked),
            "creatives": len(creatives),
            "launches": len(plans),
            "outcomes": len(outcomes),
            "feedback_records": len(feedback),
            "launchable": sum(1 for item in ranked if item.readiness and item.readiness.launchable),
        }
        launch_failures = sum(1 for outcome in outcomes if (outcome.metadata or {}).get("launch_error"))
        if launch_failures:
            summary["launch_failures"] = launch_failures
        if qa_failures:
            summary["qa_failures"] = len(qa_failures)

        status = "ok" if launch_failures == 0 else "partial_failure"
        commerce_metrics.cycles_total.labels(status=status, dry_run=str(dry_run).lower()).inc()
        commerce_metrics.feedback_total.labels(status="recorded").inc(len(feedback))
        return CommerceCycleReport(
            artifact_id=f"commerce-cycle-{int(started_at * 1000)}",
            workspace="commerce",
            started_at=started_at,
            finished_at=finished_at,
            dry_run=dry_run,
            total_signals=len(normalized_signals),
            ranked_opportunities=tuple(ranked),
            creative_bundles=tuple(creatives),
            launch_plans=tuple(plans),
            outcomes=tuple(outcomes),
            summary=summary,
            phase_timings=timings,
        )

    def run_provider_cycle(
        self,
        urls: Iterable[str],
        *,
        research_provider: Any | None = None,
        commerce_provider: Any | None = None,
        context: Any | None = None,
        top_k: int = 5,
        budget: float = 20.0,
        dry_run: bool = True,
    ) -> CommerceCycleReport:
        """Run the canonical loop using optional OSS provider inputs."""
        from .oss_bridge import collect_oss_inputs
        signals, products, metadata = collect_oss_inputs(
            tuple(urls), research=research_provider, commerce=commerce_provider, context=context,
        )
        report = self.run_cycle(
            signals=signals,
            products=products,
            offers=metadata.get("offers", {}),
            top_k=top_k,
            budget=budget,
            dry_run=dry_run,
        )
        if metadata.get("failures"):
            report.summary["provider_failures"] = metadata["failures"]
        report.summary["provider_signals"] = len(signals)
        return report


def run_commerce_cycle(
    signals: Iterable[dict[str, Any]] | None = None,
    *,
    products: Mapping[str, ProductCandidate | dict[str, Any]] | None = None,
    offers: Mapping[str, SupplierOffer | dict[str, Any]] | None = None,
    top_k: int = 5,
    budget: float = 20.0,
    dry_run: bool = True,
) -> CommerceCycleReport:
    return CommerceLoop().run_cycle(
        signals,
        products=products,
        offers=offers,
        top_k=top_k,
        budget=budget,
        dry_run=dry_run,
    )


def run_provider_cycle(
    urls: Iterable[str],
    *,
    research_provider: Any | None = None,
    commerce_provider: Any | None = None,
    context: Any | None = None,
    top_k: int = 5,
    budget: float = 20.0,
    dry_run: bool = True,
) -> CommerceCycleReport:
    return CommerceLoop().run_provider_cycle(
        urls, research_provider=research_provider, commerce_provider=commerce_provider,
        context=context, top_k=top_k, budget=budget, dry_run=dry_run,
    )
