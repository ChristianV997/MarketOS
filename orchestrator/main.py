"""orchestrator.main — unified runtime spine.

This is the single entry-point that drives the entire OS loop:

  PhaseController
    → ResourceAllocator   (budget/worker fractions per phase)
    → SignalWorker         (ingest trends → core/signals)
    → ExecutionWorker      (run backend decision/execute/learn cycle)
    → FeedbackWorker       (content metrics → playbook memory)
    → ScalingWorker        (AJO scale/kill based on validated winners)

Each worker runs as a Celery task (or synchronously via the fallback when
Redis is unavailable). The orchestrator ticks every N seconds, picks the
active phase, and dispatches work proportional to the resource allocation.

Run standalone:
  python -m orchestrator.main

Or inside Docker Compose:
  docker compose up orchestrator
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

try:
    import structlog
    _log = structlog.get_logger(__name__)
except ImportError:
    import logging as _logging_fallback
    _log = _logging_fallback.getLogger(__name__)  # type: ignore[assignment]

from core.system.phase_controller import Phase, phase_controller
from core.system.resource_allocator import resource_allocator
from core.signals import signal_engine
from backend.contracts.adapters import SidecarContext

TICK_INTERVAL   = float(os.getenv("ORCHESTRATOR_TICK_S", "10"))
TOTAL_BUDGET    = float(os.getenv("ORCHESTRATOR_BUDGET", "500"))
TOTAL_WORKERS   = int(os.getenv("ORCHESTRATOR_WORKERS", "4"))

# The canonical commerce loop is deliberately safe-by-default.  It is part of
# the normal orchestrator path, but only a deliberate environment change can
# turn a scheduler tick into a paid-platform launch.
_COMMERCE_LOOP_ENABLED = os.getenv("COMMERCE_LOOP_ENABLED", "true").lower() == "true"
_COMMERCE_LOOP_LIVE = os.getenv("COMMERCE_LOOP_LIVE", "false").lower() == "true"
_COMMERCE_LOOP_TOP_K = max(1, int(os.getenv("COMMERCE_LOOP_TOP_K", "3")))
_COMMERCE_LOOP_BUDGET = max(0.0, float(os.getenv("COMMERCE_LOOP_BUDGET", "20")))

# Full attribution lineage for every launched campaign (survives within process lifetime)
# campaign_id → CampaignArtifact (product + hook + angle + phase + budget)
from core.content.schemas import CampaignArtifact as _CampaignArtifact
_campaign_artifacts: dict[str, _CampaignArtifact] = {}

# Signal ingestion precedes the commerce worker in each phase dispatch.  Keep
# the most recent batch so ranking consumes the exact evidence that advanced
# the phase controller instead of issuing a second, potentially divergent pull.
_latest_signal_batch: list[dict[str, Any]] = []


# ── worker dispatchers ────────────────────────────────────────────────────────

def _run_signal_ingestion() -> dict[str, Any]:
    """Pull fresh signals and feed them to the intelligence loop."""
    try:
        signals = signal_engine.get(force_refresh=True)
        global _latest_signal_batch
        _latest_signal_batch = [dict(signal) for signal in signals]
        for _ in signals:
            phase_controller.record_signal()
        # Feed top keywords to core/intelligence_loop if available
        try:
            from core.intelligence_loop import run_intelligence
            keywords = [s.get("product", "") for s in signals if s.get("product")][:20]
            if keywords:
                run_intelligence(keywords)
        except Exception:
            pass
        return {"status": "ok", "signals": len(signals)}
    except Exception as exc:
        _log.exception("signal_ingestion_failed error=%s", exc)
        return {"status": "error", "error": str(exc)}


def _run_commerce_cycle() -> dict[str, Any]:
    """Run the canonical signal → rank → creative → launch → feedback path.

    The worker consumes the signal batch just ingested by this tick.  In a
    standalone invocation it falls back to the commerce loop's signal source.
    Live execution is opt-in through ``COMMERCE_LOOP_LIVE=true``; scheduler
    deployments remain dry-run by default.
    """
    if not _COMMERCE_LOOP_ENABLED:
        return {"status": "skipped", "reason": "commerce_loop_disabled"}
    try:
        from backend.commerce import collect_oss_inputs, run_commerce_cycle

        signal_batch = list(_latest_signal_batch)
        if not signal_batch and os.getenv("MARKETOS_OSS_DISCOVERY", "false").lower() == "true":
            urls = tuple(filter(None, os.getenv("MARKETOS_RESEARCH_URLS", "").split(",")))
            oss_signals, oss_products, oss_meta = collect_oss_inputs(urls, context=SidecarContext(dry_run=not _COMMERCE_LOOP_LIVE))
            signal_batch = oss_signals
            if oss_meta.get("failures"):
                _log.warning("oss_provider_degradation failures=%s", oss_meta["failures"])
        else:
            oss_products = {}
            oss_meta = {"offers": {}}

        report = run_commerce_cycle(
            signals=signal_batch or None,
            products=oss_products,
            offers=oss_meta.get("offers", {}),
            top_k=_COMMERCE_LOOP_TOP_K,
            budget=_COMMERCE_LOOP_BUDGET,
            dry_run=not _COMMERCE_LOOP_LIVE,
        )
        summary = report.summary
        return {
            "status": "ok",
            "cycle_id": report.artifact_id,
            "dry_run": report.dry_run,
            "signals": report.total_signals,
            "ranked": int(summary.get("ranked", 0)),
            "creatives": int(summary.get("creatives", 0)),
            "launches": int(summary.get("launches", 0)),
            "feedback_records": int(summary.get("feedback_records", 0)),
        }
    except Exception as exc:
        _log.exception("commerce_cycle_failed error=%s", exc)
        return {"status": "error", "error": str(exc)}


def _run_execution_cycle() -> dict[str, Any]:
    """Run one backend decision→execute→learn cycle."""
    try:
        from backend.execution.loop import run_cycle
        from backend.core.state import SystemState
        # Import shared state from api if running together; else use fresh state
        try:
            from backend.api import _state  # type: ignore[attr-defined]
            state = _state
        except Exception:
            state = SystemState()
        updated = run_cycle(state)
        return {
            "status":  "ok",
            "cycles":  updated.total_cycles,
            "capital": round(updated.capital, 2),
            "regime":  updated.detected_regime,
        }
    except Exception as exc:
        _log.exception("execution_cycle_failed error=%s", exc)
        return {"status": "error", "error": str(exc)}


def _run_feedback_collection() -> dict[str, Any]:
    """Classify recent content events, extract patterns, and update playbooks."""
    try:
        from core.content.feedback import batch_classify
        from core.content.patterns import extract_patterns, pattern_store
        from core.content.playbook import generate_playbook, playbook_memory
        try:
            from backend.api import _state  # type: ignore[attr-defined]
            rows = list(_state.event_log.rows[-50:])
        except Exception:
            rows = []
        if not rows:
            return {"status": "skipped", "reason": "no_events"}
        classified = batch_classify(rows)
        winners = [e for e in classified if e.get("label") == "WINNER"]
        if winners:
            patterns = extract_patterns(winners)
            pattern_store.update(patterns)
            products = {e.get("product", "") for e in winners if e.get("product")}
            for product in products:
                product_events = [e for e in classified if e.get("product") == product]
                try:
                    from core.system.phase_controller import phase_controller
                    phase = phase_controller.current.value
                except Exception:
                    phase = "EXPLORE"
                playbook_memory.upsert(generate_playbook(product, product_events, phase))
        return {"status": "ok", "classified": len(classified), "winners": len(winners)}
    except Exception as exc:
        _log.exception("feedback_collection_failed error=%s", exc)
        return {"status": "error", "error": str(exc)}


def _run_scaling() -> dict[str, Any]:
    """Scale/kill campaigns and launch new ones from high-confidence playbooks.

    Two execution paths (both run independently):
    1. AJO scale — if Adobe AJO is configured, scale existing winners.
    2. Playbook launch — for products with confidence >= 0.6, launch a fresh
       TikTok campaign via launch_from_playbook() (dry-run safe).
    """
    scaled   = 0
    launched = 0
    try:
        from backend.decision.portfolio_engine import top_products

        # ── Path 1: AJO scale existing campaigns ─────────────────────────────
        try:
            from backend.integrations.adobe_ajo import scale_campaign, is_configured as ajo_ok
            if ajo_ok():
                winners = top_products(n=3)
                for p in winners:
                    if p.get("weight", 0) > 0.3:
                        scale_campaign(str(p.get("product_id", "")))
                        scaled += 1
        except Exception as exc:
            _log.debug("ajo_scale_failed error=%s", exc)

        # Canonical commerce owns live campaign creation to prevent duplicate spend.
        if _COMMERCE_LOOP_LIVE:
            if scaled == 0:
                return {
                    "status": "skipped",
                    "reason": "commerce_loop_owns_live_launches",
                    "scaled": 0,
                    "launched": 0,
                }
            return {"status": "ok", "scaled": scaled, "launched": 0}

        # ── Path 2: Launch new campaigns from high-confidence playbooks ───────
        try:
            from core.content.playbook import playbook_memory
            from backend.integrations.tiktok_ads import launch_from_playbook, _DRY_RUN
            from backend.events.emitter import emit_campaign_launched
            phase = "SCALE"
            try:
                phase = phase_controller.current.value
            except Exception:
                pass
            for pb in playbook_memory.all():
                confidence = getattr(pb, "confidence", 0.0)
                if confidence < 0.6:
                    continue
                result = launch_from_playbook(vars(pb), phase=phase)
                if result.get("status") != "error":
                    cid = result.get("campaign_id", "")
                    if cid:
                        hook  = (pb.top_hooks[0]  if pb.top_hooks  else "")
                        angle = (pb.top_angles[0] if pb.top_angles else "")
                        artifact = _CampaignArtifact(
                            campaign_id    = cid,
                            adgroup_id     = result.get("adgroup_id", ""),
                            ad_ids         = result.get("ad_ids", []),
                            product        = pb.product,
                            hook           = hook,
                            angle          = angle,
                            phase          = phase,
                            estimated_roas = pb.estimated_roas,
                            budget         = result.get("budget", 0.0),
                            dry_run        = result.get("dry_run", True),
                        )
                        _campaign_artifacts[cid] = artifact
                        emit_campaign_launched(
                            campaign_id=cid,
                            product=pb.product,
                            hook=hook,
                            angle=angle,
                            phase=phase,
                            budget=artifact.budget,
                            dry_run=artifact.dry_run,
                        )
                    launched += 1
                    _log.info("playbook_launched product=%s confidence=%s campaign=%s",
                              pb.product, confidence, cid)
                if launched >= 3:   # cap launches per tick to avoid runaway spend
                    break
        except Exception as exc:
            _log.debug("playbook_launch_failed error=%s", exc)

        if scaled == 0 and launched == 0:
            return {"status": "skipped", "reason": "no_qualified_campaigns"}
        return {"status": "ok", "scaled": scaled, "launched": launched}
    except Exception as exc:
        _log.exception("scaling_failed error=%s", exc)
        return {"status": "error", "error": str(exc)}


def _run_simulation() -> dict[str, Any]:
    """Score and rank signal candidates before execution (simulation layer)."""
    try:
        from simulation.integration import _run_simulation as _sim
        result = _sim()
        return result
    except Exception as exc:
        _log.exception("simulation_worker_failed error=%s", exc)
        return {"status": "error", "error": str(exc)}


def _run_content_generation() -> dict[str, Any]:
    """Generate hooks and scripts for the top-ranked trending products.

    Pulls real trending products from the signal engine, selects the best
    hooks/angles from PatternStore (falls back to the curated HOOKS list),
    generates a script per product, and upserts into playbook_memory so
    _run_scaling() can launch campaigns from the result.
    """
    try:
        from core.content.patterns import pattern_store
        from core.content.playbook import playbook_memory, generate_playbook, Playbook
        from core.creative.generator import generate_creative
        from core.signals import signal_engine

        # ── hooks / angles ────────────────────────────────────────────────────
        top_hooks  = pattern_store.get_top_hooks(n=3)
        top_angles = pattern_store.get_top_angles(n=3)
        if not top_hooks:
            from core.creative.hooks import HOOKS
            top_hooks = list(HOOKS)[:3]
        if not top_angles:
            top_angles = ["problem-solution", "social-proof", "urgency"]

        # ── real trending products ────────────────────────────────────────────
        try:
            signals  = signal_engine.get()
            products = list({s.get("product", "") for s in signals if s.get("product")})[:5]
        except Exception:
            products = []
        if not products:
            products = ["trending product"]

        generated = 0
        for product in products[:3]:
            angle  = top_angles[0]
            hook   = top_hooks[0]
            try:
                script = generate_creative(product, angle)
                # Upsert a playbook so _run_scaling() can launch it
                existing = playbook_memory.get(product)
                if existing is None:
                    pb = Playbook(
                        product=product,
                        phase="EXPLORE",
                        top_hooks=top_hooks,
                        top_angles=top_angles,
                        estimated_roas=1.2,
                        confidence=0.0,
                        evidence_count=0,
                    )
                    playbook_memory.upsert(pb)
                _log.info("content_generated product=%s hook=%r angle=%s len=%d",
                          product, hook, angle, len(script))
                generated += 1
            except Exception as gen_exc:
                _log.warning("content_generate_failed product=%s error=%s", product, gen_exc)

        return {"status": "ok", "generated": generated, "top_hooks": top_hooks}
    except Exception as exc:
        _log.exception("content_generation_failed error=%s", exc)
        return {"status": "error", "error": str(exc)}


def _reconcile_delayed_commerce_metrics(calibration_store: Any) -> int:
    """Apply later, attributable TikTok ROAS to commerce launch artifacts.

    TikTok's dry-run ROAS is useful for isolated tests but must never be
    accepted as production feedback. Only a configured live client can close a
    pending commerce campaign's durable attribution record.
    """
    try:
        from backend.contracts.registry import get_registry
        from backend.integrations.tiktok_ads import _DRY_RUN, fetch_roas, is_configured

        if _DRY_RUN or not is_configured():
            return 0
        registry = get_registry()
        assets_by_id = {
            asset.artifact_id: asset for asset in registry.by_type("campaign")
        }
        assets = [
            asset for asset in assets_by_id.values()
            if getattr(asset, "phase", "") == "commerce"
            and not getattr(asset, "dry_run", True)
            and not getattr(asset, "outcome_recorded", False)
            and getattr(asset, "campaign_id", "")
        ]
        campaign_ids = list(dict.fromkeys(asset.campaign_id for asset in assets))[:10]
        if not campaign_ids:
            return 0
        roas_map = fetch_roas(campaign_ids)
        reconciled = 0
        for asset in assets:
            roas = roas_map.get(asset.campaign_id)
            if roas is None:
                continue
            registry.register(asset.with_outcome(float(roas)))
            calibration_store.record_outcome(asset.product, actual_roas=float(roas))
            reconciled += 1
        return reconciled
    except Exception as exc:
        _log.debug("commerce_delayed_metrics_failed error=%s", exc)
        return 0


def _run_metrics_ingestion() -> dict[str, Any]:
    """Ingest real platform metrics and close the prediction→reality loop.

    Fetches:
      - Shopify order revenue (last 60 min)
      - Meta ad spend (last 60 min)
      - TikTok campaign ROAS (for any tracked campaign IDs)

    Then records real outcomes into CalibrationStore so future predictions
    are corrected by actual performance, not just simulated ROAS.
    Emits a metrics.ingested event for the dashboard.
    """
    try:
        from simulation.calibration import calibration_store
        from backend.events.emitter import emit_metrics_ingested

        metrics: dict[str, Any] = {}

        # Shopify revenue
        try:
            from backend.integrations.shopify_client import get_orders, compute_metrics
            orders  = get_orders(last_n_minutes=60)
            shopify = compute_metrics(orders)
            metrics["shopify_revenue"]    = shopify.get("revenue", 0.0)
            metrics["shopify_order_count"] = shopify.get("order_count", 0)
        except Exception as exc:
            _log.debug("metrics_shopify_failed error=%s", exc)

        # Meta ad spend
        try:
            from backend.integrations.meta_ads_client import get_ad_spend
            meta = get_ad_spend(last_n_minutes=60)
            metrics["meta_spend"]     = meta.get("total_spend", 0.0)
            metrics["meta_campaigns"] = len(meta.get("campaigns", []))
        except Exception as exc:
            _log.debug("metrics_meta_failed error=%s", exc)

        # Compute blended real ROAS and record into calibration store
        revenue = float(metrics.get("shopify_revenue", 0.0))
        spend   = float(metrics.get("meta_spend", 0.0))
        if spend > 0 and revenue > 0:
            real_roas = round(revenue / spend, 4)
            metrics["real_roas"] = real_roas
            # Record outcome against any pending predictions for "blended" product
            calibration_store.record_outcome("blended", actual_roas=real_roas)
            _log.info("metrics_real_roas_recorded roas=%s", real_roas)

        # TikTok ROAS for tracked campaigns — full lineage via _campaign_artifacts
        try:
            from backend.integrations.tiktok_ads import fetch_roas
            from core.content.patterns import extract_patterns, pattern_store
            from core.content.feedback import classify_video, engagement_score

            campaign_ids = list(_campaign_artifacts.keys())[:10]
            if campaign_ids:
                roas_map = fetch_roas(campaign_ids)
                metrics["tiktok_campaign_count"] = len(roas_map)
                for cid, roas in roas_map.items():
                    artifact = _campaign_artifacts.get(cid)
                    product  = artifact.product if artifact else cid
                    # ── CalibrationStore: record per-product outcome ───────────
                    calibration_store.record_outcome(product, actual_roas=roas)
                    # ── PatternStore: backfill from real TikTok ROAS ──────────
                    # Build a synthetic classified event so pattern learning sees
                    # real campaign performance, not just simulated outcomes.
                    if artifact:
                        synth = {
                            "product":   artifact.product,
                            "hook":      artifact.hook,
                            "angle":     artifact.angle,
                            "roas":      roas,
                            "ctr":       0.0,   # not available from ROAS endpoint
                            "cvr":       0.0,
                            "env_regime": artifact.phase,
                        }
                        synth["label"]     = classify_video(synth)
                        synth["eng_score"] = engagement_score(synth)
                        pattern_store.update(extract_patterns([synth]))
                    _log.debug("metrics_tiktok campaign=%s product=%s roas=%s", cid, product, roas)
        except Exception as exc:
            _log.debug("metrics_tiktok_failed error=%s", exc)

        commerce_reconciled = _reconcile_delayed_commerce_metrics(calibration_store)
        if commerce_reconciled:
            metrics["commerce_campaigns_reconciled"] = commerce_reconciled

        if not metrics:
            return {"status": "skipped", "reason": "no_metrics_available"}

        emit_metrics_ingested("orchestrator", metrics)
        return {"status": "ok", "metrics": {k: v for k, v in metrics.items()
                                             if isinstance(v, (int, float, str))}}
    except Exception as exc:
        _log.exception("metrics_ingestion_failed error=%s", exc)
        return {"status": "error", "error": str(exc)}


# ── worker retry + anomaly ────────────────────────────────────────────────────

# Track consecutive error counts per worker to gate anomaly emission
_worker_error_counts: dict[str, int] = {}
_ANOMALY_THRESHOLD = 2   # emit anomaly after this many consecutive errors


def _with_retry(fn: Any, attempts: int = 2) -> dict[str, Any]:
    """Run worker fn up to ``attempts`` times.

    - Returns first ``ok`` or ``skipped`` result immediately.
    - On repeated ``error`` status, emits an ``anomaly.detected`` event.
    - Never raises — always returns a status dict.
    """
    last_result: dict[str, Any] = {"status": "error", "error": "no_attempts"}
    for attempt in range(attempts):
        try:
            last_result = fn()
        except Exception as exc:
            last_result = {"status": "error", "error": str(exc)}
        if last_result.get("status") in ("ok", "skipped"):
            _worker_error_counts[fn.__name__] = 0
            return last_result
        # error path — wait a beat before retry (only if there are more attempts)
        if attempt < attempts - 1:
            time.sleep(0.5)

    # all attempts failed
    count = _worker_error_counts.get(fn.__name__, 0) + 1
    _worker_error_counts[fn.__name__] = count
    if count >= _ANOMALY_THRESHOLD:
        try:
            from backend.events.emitter import emit_anomaly
            emit_anomaly(
                level="error",
                message=f"worker_repeated_failure fn={fn.__name__} "
                        f"consecutive={count} error={last_result.get('error', '')}",
                source="orchestrator",
            )
        except Exception:
            pass
    return last_result


# ── phase dispatch table ───────────────────────────────────────────────────────

_PHASE_WORKERS: dict[Phase, list[Any]] = {
    # RESEARCH: discover signals + warm simulation; ingest first metrics
    Phase.RESEARCH:  [_run_simulation, _run_signal_ingestion, _run_signal_ingestion,
                      _run_execution_cycle, _run_metrics_ingestion],
    # EXPLORE: signal → simulate → execute × 2 → feedback → generate content
    Phase.EXPLORE:   [_run_simulation, _run_signal_ingestion, _run_commerce_cycle, _run_execution_cycle,
                      _run_execution_cycle, _run_feedback_collection,
                      _run_content_generation, _run_metrics_ingestion],
    # VALIDATE: execution + feedback × 2 + metrics ingestion to close loop
    Phase.VALIDATE:  [_run_signal_ingestion, _run_commerce_cycle, _run_execution_cycle,
                      _run_feedback_collection, _run_feedback_collection,
                      _run_content_generation, _run_metrics_ingestion],
    # SCALE: execute + feedback + launch playbooks + scale winners + ingest metrics
    Phase.SCALE:     [_run_signal_ingestion, _run_commerce_cycle, _run_execution_cycle, _run_feedback_collection,
                      _run_content_generation, _run_scaling, _run_scaling,
                      _run_metrics_ingestion],
}


# ── metrics collection ────────────────────────────────────────────────────────

def _collect_metrics() -> dict[str, Any]:
    """Read KPIs needed by PhaseController.tick()."""
    try:
        from backend.api import _state  # type: ignore[attr-defined]
        rows = _state.event_log.rows
        recent = rows[-20:] if rows else []
        avg_roas = sum(r.get("roas", 0) for r in recent) / max(len(recent), 1)
        winners  = sum(1 for r in recent if r.get("roas", 0) >= 1.5)
        win_rate = winners / max(len(recent), 1)
        return {
            "avg_roas":     round(avg_roas, 4),
            "win_rate":     round(win_rate, 4),
            "capital":      round(_state.capital, 2),
            "signal_count": phase_controller.status()["signal_count"],
        }
    except Exception:
        return {"avg_roas": 0.0, "win_rate": 0.0, "capital": 0.0, "signal_count": 0}


# ── Prometheus instrumentation ────────────────────────────────────────────────

try:
    from prometheus_client import Counter, Gauge, start_http_server

    _phase_gauge    = Gauge("orchestrator_phase", "Current lifecycle phase", ["phase"])
    _cycle_counter  = Counter("orchestrator_cycles_total", "Total orchestrator ticks")
    _worker_counter = Counter("orchestrator_worker_runs_total", "Worker dispatch count", ["worker"])
    _PROMETHEUS_PORT = int(os.getenv("ORCHESTRATOR_METRICS_PORT", "9200"))

    def _init_prometheus() -> None:
        try:
            start_http_server(_PROMETHEUS_PORT)
            _log.info("prometheus_started port=%s", _PROMETHEUS_PORT)
        except Exception as exc:
            _log.warning("prometheus_start_failed error=%s", exc)

    def _record_phase(phase: Phase) -> None:
        for p in Phase:
            _phase_gauge.labels(phase=p.value).set(1 if p == phase else 0)

    def _record_worker(name: str) -> None:
        _worker_counter.labels(worker=name).inc()

    def _record_tick() -> None:
        _cycle_counter.inc()

except ImportError:
    def _init_prometheus() -> None: pass
    def _record_phase(_: Phase) -> None: pass
    def _record_worker(_: str) -> None: pass
    def _record_tick() -> None: pass


# ── main loop ─────────────────────────────────────────────────────────────────

def run() -> None:
    """Run the orchestrator loop indefinitely."""
    _log.info("orchestrator_starting tick_interval=%s", TICK_INTERVAL)
    _init_prometheus()

    while True:
        try:
            metrics = _collect_metrics()
            phase   = phase_controller.tick(metrics)
            alloc   = resource_allocator.describe(phase, TOTAL_BUDGET)

            _record_phase(phase)
            _record_tick()

            _log.info(
                "orchestrator_tick phase=%s avg_roas=%s capital=%s",
                phase.value,
                metrics.get("avg_roas"),
                metrics.get("capital"),
            )
            try:
                from backend.events.emitter import emit_tick as _emit_tick
                _emit_tick(
                    phase=phase.value,
                    avg_roas=metrics.get("avg_roas", 0.0),
                    capital=metrics.get("capital", 0.0),
                    win_rate=metrics.get("win_rate", 0.0),
                    signal_count=metrics.get("signal_count", 0),
                )
            except Exception:
                pass
            try:
                from backend.runtime.task_inventory import task_registry as _tr
                _tr.heartbeat("orchestrator_tick", status="ok")
            except Exception:
                pass

            for worker_fn in _PHASE_WORKERS.get(phase, []):
                result = _with_retry(worker_fn)
                _record_worker(worker_fn.__name__)
                if result.get("status") not in ("ok", "skipped"):
                    _log.warning("worker_error worker=%s result=%s", worker_fn.__name__, result)
                # Publish worker event via canonical emitter
                try:
                    from backend.events.emitter import emit_worker_health as _emit_wh
                    extra = {k: v for k, v in result.items()
                             if k not in ("status", "error") and isinstance(v, (int, float, str))}
                    _emit_wh(
                        worker=worker_fn.__name__,
                        status=result.get("status", "ok"),
                        phase=phase.value,
                        **extra,
                    )
                except Exception:
                    pass
                # Heartbeat task inventory
                _worker_task = {
                    "_run_signal_ingestion":    "signal_ingestion_worker",
                    "_run_execution_cycle":     "execution_cycle_worker",
                    "_run_feedback_collection": "feedback_collection_worker",
                    "_run_scaling":             "scaling_worker",
                    "_run_simulation":          "simulation_worker",
                    "_run_content_generation":  "content_generation_worker",
                    "_run_metrics_ingestion":   "metrics_ingestion_worker",
                    "_run_commerce_cycle":      "commerce_cycle_worker",
                }.get(worker_fn.__name__, worker_fn.__name__)
                try:
                    from backend.runtime.task_inventory import task_registry as _tr
                    _tr.heartbeat(_worker_task, status=result.get("status", "ok"))
                except Exception:
                    pass

        except (KeyboardInterrupt, SystemExit):
            _log.info("orchestrator_stopping")
            break
        except Exception as exc:
            _log.exception("orchestrator_tick_error error=%s", exc)

        time.sleep(TICK_INTERVAL)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        import structlog as _sl
        _sl.configure(
            processors=[
                _sl.processors.TimeStamper(fmt="iso"),
                _sl.stdlib.add_log_level,
                _sl.processors.JSONRenderer(),
            ],
            wrapper_class=_sl.stdlib.BoundLogger,
            logger_factory=_sl.stdlib.LoggerFactory(),
        )
    except ImportError:
        pass
    run()
