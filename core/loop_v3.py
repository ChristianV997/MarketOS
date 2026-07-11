"""Phase 2 enhanced execution loop (v3).

Full pipeline::

    signals → create pods → launch ads → collect metrics
    → optimize creatives → scale budgets → kill losers

This module is deliberately self-contained so it can be imported without
side-effects from the rest of the OS.  It delegates all heavy lifting to
the dedicated sub-systems and connectors.
"""

from __future__ import annotations

import logging

from agents.creative_optimizer import CreativeOptimizer
from agents.execution.ads_agent import AdsAgent
from agents.execution.creative_agent import CreativeAgent
from core.capital_engine import CapitalEngineV2
from core.memory import store_event, store_pod_performance, store_product_result
from core.pods import PodManager
from core.signals import SignalEngine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default tunables — override by passing a config dict to run_cycle_v3
# ---------------------------------------------------------------------------
_DEFAULTS = {
    "max_concurrent_pods": 10,
    "min_score": 0.5,
    "daily_cap": 500.0,
    "scale_roas": 2.0,
    "kill_roas": 1.0,
    "creatives_per_pod": 3,
    "ctr_threshold": 0.015,
    "cvr_threshold": 0.010,
}


def run_cycle_v3(signals: list | None = None, config: dict | None = None) -> list[dict]:
    """Execute one full Phase-2 loop cycle and return per-pod decision records.

    Parameters
    ----------
    signals:
        Pre-fetched signal list.  When *None*, the global ``SignalEngine``
        mock is used so the loop can run offline during tests.
    config:
        Optional overrides for ``_DEFAULTS`` (e.g. ``{"max_concurrent_pods": 5}``).

    Returns
    -------
    list[dict]
        One record per pod containing ``pod_id``, ``decision``, ``roas``,
        ``spend``, ``revenue``, and ``creative_variants`` generated.
    """
    cfg = {**_DEFAULTS, **(config or {})}

    # ------------------------------------------------------------------ setup
    signal_engine = SignalEngine()
    pod_manager = PodManager(max_concurrent_pods=cfg["max_concurrent_pods"])
    capital_engine = CapitalEngineV2(
        scale_threshold=cfg["scale_roas"],
        kill_threshold=cfg["kill_roas"],
        daily_cap=cfg["daily_cap"],
        max_concurrent_pods=cfg["max_concurrent_pods"],
    )
    creative_agent = CreativeAgent()
    ads_agent = AdsAgent()
    optimizer = CreativeOptimizer(
        ctr_threshold=cfg["ctr_threshold"],
        cvr_threshold=cfg["cvr_threshold"],
    )

    # ---------------------------------------------------------------- signals
    if signals is None:
        raw = signal_engine.get()
    else:
        raw = signals

    opportunities = signal_engine.filter_opportunities(raw, min_score=cfg["min_score"])
    opportunities = signal_engine.top_opportunities(opportunities, n=cfg["max_concurrent_pods"])

    results: list[dict] = []

    for signal in opportunities:
        # --------------------------------------------------------- create pod
        try:
            pod = pod_manager.create(
                product=signal.get("product", "unknown"),
                market=signal.get("market", "global"),
                platform=signal.get("platform", "tiktok"),
                budget=float(signal.get("budget", 50.0)),
            )
        except RuntimeError as exc:
            logger.warning("Pod creation blocked: %s", exc)
            continue

        # --------------------------------------------------- generate creatives
        creatives = creative_agent.batch_generate([pod], count=cfg["creatives_per_pod"])
        pod.creatives = creatives.get(pod.id, [])

        # Register creatives with the optimizer so they can be mutated later
        for i, c in enumerate(pod.creatives):
            cid = f"{pod.id}_creative_{i}"
            c["id"] = cid
            optimizer.register(c)

        # ------------------------------------------------------ launch ads
        ads_agent.launch(pod)
        logger.info("[%s] Ads launched — product=%s platform=%s", pod.id, pod.product, pod.platform)

        # --------------------------------------------------- collect metrics
        # In production these come from backend.integrations.tiktok_ads metrics.
        # Here we use values embedded in the signal so integration tests and
        # the live loop can both use this function without branching.
        roas = float(signal.get("roas", 0.0))
        spend = float(signal.get("spend", pod.budget))
        revenue = roas * spend
        clicks = int(signal.get("clicks", 0))
        impressions = int(signal.get("impressions", 0))
        conversions = int(signal.get("conversions", 0))
        ctr = clicks / impressions if impressions else 0.0
        cvr = conversions / clicks if clicks else 0.0

        pod_manager.update_metrics(pod.id, roas=roas, spend=spend, revenue=revenue)

        # Feed creative-level metrics into the optimizer only when we have
        # enough data to make a reliable CTR/CVR judgement.  Recording zeros
        # from a brand-new creative would incorrectly classify it as a loser.
        _MIN_IMPRESSIONS = 100
        _MIN_CLICKS = 10
        if impressions >= _MIN_IMPRESSIONS and clicks >= _MIN_CLICKS:
            for i, c in enumerate(pod.creatives):
                cid = c.get("id", f"{pod.id}_creative_{i}")
                optimizer.record(cid, {"ctr": ctr, "cvr": cvr, "clicks": clicks, "conversions": conversions})

        # ------------------------------------------- optimize creatives
        new_variants = optimizer.generate_variants(count=1)
        discarded = optimizer.discard_losers()
        logger.info("[%s] Creative variants: %d new, %d discarded", pod.id, len(new_variants), len(discarded))

        # ------------------------------------------- scale / kill decision
        decision = capital_engine.apply(pod)
        logger.info("[%s] ROAS=%.2f DECISION=%s budget=%.2f", pod.id, roas, decision, pod.budget)

        # Daily-cap enforcement
        capital_engine.enforce_daily_cap(pod)

        # ---------------------------------------------- persist
        store_pod_performance(pod.id, pod.metrics)
        store_product_result(
            pod.product,
            {"roas": roas, "spend": spend, "revenue": revenue, "status": pod.status},
        )
        store_event(
            {
                "pod_id": pod.id,
                "signal": signal,
                "decision": decision,
                "roas": roas,
                "spend": spend,
                "revenue": revenue,
            }
        )

        results.append(
            {
                "pod_id": pod.id,
                "decision": decision,
                "roas": roas,
                "spend": spend,
                "revenue": revenue,
                "creative_variants": len(new_variants),
            }
        )

    return results
