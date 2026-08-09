"""simulation.engine — SimulationEngine orchestrator.

Main entry point for the simulation layer.  Sits between discovery and
execution: given a list of signal candidates it scores them, corrects for
calibration bias, ranks them, and returns ordered SimulationResults.

Lifecycle
---------
1. ``warm_up(rows)`` — train the scoring model on existing event history
2. ``score_signals(signals, ...)`` — score + rank candidates pre-execution
3. ``record_outcome(...)`` — feed actual outcomes back to the calibrator

All state is held in process-local singletons (scoring_model, replay_store,
simulation_calibrator) — no external dependencies required at import time.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

_log = logging.getLogger(__name__)

# Phase 7: cap Monte Carlo interval computation per cycle — each call
# bootstraps 1000 samples, so scoring is limited to the top-K candidates
# by engagement rather than the full signal batch.
_MONTE_CARLO_TOP_K = 20


class SimulationEngine:
    """Orchestrates feature extraction, scoring, ranking, and calibration.

    Thread-safe: all public methods acquire ``_lock`` where needed.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._warmed_up = False
        self._last_train_ts: float | None = None
        self._score_count = 0
        self._outcome_count = 0

    # ------------------------------------------------------------------
    # Warm-up
    # ------------------------------------------------------------------

    def warm_up(
        self,
        rows: list[dict],
        patterns: dict | None = None,
        playbooks: dict | None = None,
        force: bool = False,
    ) -> bool:
        """Train the scoring model on historical event rows.

        Called at startup and periodically when new data arrives.
        Returns True if training succeeded.
        """
        from simulation.model import scoring_model
        from simulation.replay import replay_store

        # Ingest into replay store
        replay_store.ingest(rows)

        # Retrain scoring model
        ok = scoring_model.fit(rows, patterns=patterns, playbooks=playbooks)
        if ok:
            with self._lock:
                self._warmed_up = True
                self._last_train_ts = time.time()
            _log.info("simulation_warmed_up rows=%d", len(rows))
        return ok

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score_signals(
        self,
        signals: list[dict],
        patterns: dict | None = None,
        playbooks: dict | None = None,
        history_map: dict[str, list[dict]] | None = None,
    ) -> list[Any]:  # list[SimulationResult]
        """Score and rank a list of signal candidates.

        Returns an ordered list of SimulationResult (rank 1 = best).
        """
        from simulation.calibrator import simulation_calibrator
        from simulation.model import scoring_model
        from simulation.ranking import build_result, rank_results
        from simulation.replay import replay_store

        if not signals:
            return []

        # Fill history from replay store if not provided
        if history_map is None:
            products = {s.get("product", "") for s in signals}
            history_map = {
                p: replay_store.product_history(p, limit=50)
                for p in products if p
            }

        scores = scoring_model.predict(
            signals,
            patterns=patterns,
            playbooks=playbooks,
            history_map=history_map,
        )

        results = []
        for sig, eng in zip(signals, scores):
            product = sig.get("product", "")
            hist = (history_map or {}).get(product, [])
            r = build_result(
                sig, eng,
                history=hist,
                patterns=patterns,
                calibrator=simulation_calibrator,
            )
            results.append(r)

        self._apply_monte_carlo_intervals(signals, results, patterns, playbooks, history_map)

        ranked = rank_results(results)

        with self._lock:
            self._score_count += len(ranked)

        return ranked

    def _apply_monte_carlo_intervals(
        self,
        signals: list[dict],
        results: list[Any],
        patterns: dict | None,
        playbooks: dict | None,
        history_map: dict[str, list[dict]] | None,
    ) -> None:
        """Phase 7: attach bootstrap prediction intervals to top-K results.

        Gated by PHASE7_MONTE_CARLO_LIVE: always computed and journaled for
        shadow-mode validation; only widens risk_score (changing the final
        rank_score) once the flag is live.
        """
        from simulation.model import scoring_model

        monte_carlo_live = os.getenv("PHASE7_MONTE_CARLO_LIVE", "false").lower() == "true"

        # Bound cost: only the top-K by pre-MC engagement get bootstrapped.
        by_engagement = sorted(
            zip(signals, results), key=lambda p: p[1].predicted_engagement, reverse=True
        )[:_MONTE_CARLO_TOP_K]

        journal_rows = []
        for sig, r in by_engagement:
            product = r.product
            playbook = (playbooks or {}).get(product)
            history = (history_map or {}).get(product)
            try:
                interval = scoring_model.predict_with_intervals(
                    sig, patterns=patterns, playbook=playbook, history=history,
                )
            except Exception:
                continue

            r.mc_interval_width = interval["mean_interval_width"]
            r.mc_ci_lower = interval["confidence_interval_lower"]
            r.mc_ci_upper = interval["confidence_interval_upper"]

            legacy_risk = r.risk_score
            mc_risk = max(r.risk_score, r.mc_interval_width)
            journal_rows.append({
                "product": product,
                "legacy_risk_score": round(legacy_risk, 4),
                "mc_risk_score": round(mc_risk, 4),
                "mc_interval_width": round(r.mc_interval_width, 4),
            })

            if monte_carlo_live:
                r.risk_score = mc_risk

        try:
            from backend.orchestration.event_store import event_store, new_workflow_id
            event_store.append(
                new_workflow_id("montecarlo"), "shadow_monte_carlo_risk",
                workflow="simulation_engine", step="score_signals",
                data={"rows": journal_rows, "live": monte_carlo_live},
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Outcome recording
    # ------------------------------------------------------------------

    def record_outcome(
        self,
        product: str,
        predicted_roas: float,
        actual_roas: float,
        event: dict | None = None,
    ) -> None:
        """Feed one (predicted, actual) pair into the calibration loop.

        Also ingests the full event dict into the replay store.
        """
        from simulation.calibrator import simulation_calibrator
        from simulation.replay import replay_store

        simulation_calibrator.record(product, predicted_roas, actual_roas)

        if event:
            replay_store.ingest([event])

        with self._lock:
            self._outcome_count += 1

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def report(self) -> dict:
        """Return a snapshot of simulation layer health and stats."""
        from simulation.calibrator import simulation_calibrator
        from simulation.model import scoring_model
        from simulation.replay import replay_store

        with self._lock:
            warmed = self._warmed_up
            score_count = self._score_count
            outcome_count = self._outcome_count
            last_train = self._last_train_ts

        return {
            "warmed_up": warmed,
            "score_count": score_count,
            "outcome_count": outcome_count,
            "last_train_ts": last_train,
            "model": scoring_model.info(),
            "calibration": simulation_calibrator.report(),
            "replay_rows": replay_store.row_count(),
            "ts": time.time(),
        }

    def top_hooks(self, n: int = 5) -> list[dict]:
        from simulation.replay import replay_store
        return replay_store.hook_stats(top_n=n)

    def top_angles(self, n: int = 5) -> list[dict]:
        from simulation.replay import replay_store
        return replay_store.angle_stats(top_n=n)


# module-level singleton
simulation_engine = SimulationEngine()
