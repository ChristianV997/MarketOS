"""backend.runtime.state — ONE canonical runtime state model.

Architecture
------------
RuntimeState  — the canonical aggregate: typed domain collections + metrics.
               Populated once per cycle via build_runtime_state().
               Everything (orchestrator, workers, WS, simulation) reads this.

RuntimeSnapshot — the backward-compat WebSocket payload produced by
               RuntimeState.to_snapshot().  Frontend unchanged.

build_runtime_state(system_state) → RuntimeState   ← preferred new entry point
build_snapshot(system_state)      → RuntimeSnapshot ← kept for backward compat
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from backend.runtime.models import (
    AlertRecord,
    DecisionRecord,
    MetricsRecord,
    OrchestratorRecord,
    PlaybookRecord,
    SignalRecord,
    SimulationRecord,
    WorkerRecord,
)


# ── Backward-compat WebSocket payload ────────────────────────────────────────

@dataclass
class RuntimeSnapshot:
    ts:                 float                = field(default_factory=time.time)
    type:               str                  = "snapshot"
    cycle:              int                  = 0
    phase:              str                  = "RESEARCH"
    capital:            float                = 0.0
    avg_roas:           float                = 0.0
    win_rate:           float                = 0.0
    regime:             str                  = "unknown"
    signal_count:       int                  = 0
    top_signals:        list[dict[str, Any]] = field(default_factory=list)
    top_playbooks:      list[dict[str, Any]] = field(default_factory=list)
    patterns:           dict[str, Any]       = field(default_factory=dict)
    recent_decisions:   list[dict[str, Any]] = field(default_factory=list)
    worker_status:      dict[str, Any]       = field(default_factory=dict)
    simulation_scores:  list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


# ── Canonical runtime state ───────────────────────────────────────────────────

@dataclass
class RuntimeState:
    """ONE canonical view of the full operational runtime.

    Produced once per cycle by ``build_runtime_state()``.  All components that
    need a read-only consistent view of runtime state consume this object.

    Domains
    -------
    signals      — fresh signal candidates from signal engine
    simulations  — ranked simulation results from most recent score_signals()
    playbooks    — current playbook memory per (product, phase)
    workers      — live task health from task registry
    decisions    — recent decision outcomes from event log
    alerts       — runtime alerts (anomalies, warnings)
    metrics      — scalar KPIs (capital, ROAS, win rate, phase, regime)
    orchestrator — orchestrator heartbeat record
    """
    ts:           float                = field(default_factory=time.time)
    type:         str                  = "runtime_state"

    # collections
    signals:      list[SignalRecord]     = field(default_factory=list)
    simulations:  list[SimulationRecord] = field(default_factory=list)
    playbooks:    list[PlaybookRecord]   = field(default_factory=list)
    workers:      list[WorkerRecord]     = field(default_factory=list)
    decisions:    list[DecisionRecord]   = field(default_factory=list)
    alerts:       list[AlertRecord]      = field(default_factory=list)

    # scalars
    metrics:      MetricsRecord      = field(default_factory=MetricsRecord)
    orchestrator: OrchestratorRecord = field(default_factory=OrchestratorRecord)

    # raw pattern data (not yet modelled as a typed record)
    patterns: dict[str, Any] = field(default_factory=dict)

    def to_snapshot(self) -> RuntimeSnapshot:
        """Produce the backward-compat RuntimeSnapshot for WebSocket delivery."""
        return RuntimeSnapshot(
            ts=self.ts,
            cycle=self.metrics.cycle,
            phase=self.metrics.phase,
            capital=self.metrics.capital,
            avg_roas=self.metrics.avg_roas,
            win_rate=self.metrics.win_rate,
            regime=self.metrics.regime,
            signal_count=len(self.signals),
            top_signals=[s.to_dict() for s in self.signals[:5]],
            top_playbooks=[p.to_dict() for p in self.playbooks[:5]],
            patterns=self.patterns,
            recent_decisions=[d.to_dict() for d in self.decisions[-10:]],
            simulation_scores=[s.to_dict() for s in self.simulations[:8]],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


# ── Factory ───────────────────────────────────────────────────────────────────

def build_runtime_state(state: Any) -> RuntimeState:
    """Build the canonical RuntimeState from SystemState + all singletons.

    All reads are guarded — a singleton import failure degrades gracefully
    (empty collection) rather than crashing the cycle.
    """
    # ── metrics from event log ────────────────────────────────────────────────
    rows = state.event_log.rows[-20:] if state.event_log.rows else []
    avg_roas = sum(r.get("roas", 0.0) for r in rows) / max(len(rows), 1)
    winners  = sum(1 for r in rows if r.get("roas", 0.0) >= 1.5)
    win_rate = winners / max(len(rows), 1)

    phase = "RESEARCH"
    signal_count = 0
    try:
        from core.system.phase_controller import phase_controller
        signal_count = phase_controller.status().get("signal_count", 0)
        phase = phase_controller.current.value
    except Exception:
        pass

    metrics = MetricsRecord(
        capital=round(state.capital, 2),
        avg_roas=round(avg_roas, 4),
        win_rate=round(win_rate, 4),
        cycle=state.total_cycles,
        phase=phase,
        regime=state.detected_regime or "unknown",
        signal_count=signal_count,
    )

    # ── signals ───────────────────────────────────────────────────────────────
    signals: list[SignalRecord] = []
    raw_signals: list[dict] = []
    try:
        from core.signals import signal_engine
        raw_signals = signal_engine.get()

        # Phase 7: urgency-weighted ranking (velocity * (1-saturation)),
        # gated by PHASE7_URGENCY_SCORING_LIVE. Both rankings are always
        # computed and journaled so shadow-mode validation can compare
        # them before the flag flips.
        urgency_live = os.getenv("PHASE7_URGENCY_SCORING_LIVE", "false").lower() == "true"
        legacy_opps = signal_engine.top_opportunities(raw_signals, n=8, use_urgency=False)
        urgency_opps = signal_engine.top_opportunities(raw_signals, n=8, use_urgency=True)
        try:
            from backend.orchestration.event_store import event_store, new_workflow_id
            event_store.append(
                new_workflow_id("urgency"), "shadow_urgency_scoring",
                workflow="runtime_state", step="top_opportunities",
                data={
                    "legacy_products": [s.get("product", "") for s in legacy_opps],
                    "urgency_products": [s.get("product", "") for s in urgency_opps],
                    "live": urgency_live,
                },
            )
        except Exception:
            pass

        opps = urgency_opps if urgency_live else legacy_opps
        signals = [SignalRecord.from_dict(s) for s in opps]
    except Exception:
        pass

    # ── playbooks ─────────────────────────────────────────────────────────────
    playbooks: list[PlaybookRecord] = []
    raw_playbooks: list[dict] = []
    try:
        from core.content.playbook import playbook_memory
        all_pbs = playbook_memory.all()[:8]
        raw_playbooks = [vars(p) for p in all_pbs]
        playbooks = [PlaybookRecord.from_dict(d) for d in raw_playbooks]
    except Exception:
        pass

    # ── patterns ──────────────────────────────────────────────────────────────
    patterns: dict = {}
    try:
        from core.content.patterns import pattern_store
        patterns = pattern_store.get_patterns()
    except Exception:
        pass

    # ── simulations ───────────────────────────────────────────────────────────
    simulations: list[SimulationRecord] = []
    try:
        from simulation.engine import simulation_engine
        pb_map = {p["product"]: p for p in raw_playbooks}
        ranked = simulation_engine.score_signals(
            [s.to_dict() for s in signals[:10]],
            patterns=patterns,
            playbooks=pb_map,
        )
        simulations = [SimulationRecord.from_dict(r.to_dict()) for r in ranked[:8]]
    except Exception:
        pass

    # ── workers ───────────────────────────────────────────────────────────────
    workers: list[WorkerRecord] = []
    try:
        from backend.runtime.task_inventory import task_registry
        workers = [WorkerRecord.from_dict(t) for t in task_registry.all()]
    except Exception:
        pass

    # ── decisions ─────────────────────────────────────────────────────────────
    decisions = [DecisionRecord.from_dict(r) for r in rows[-15:]]

    # ── orchestrator record ───────────────────────────────────────────────────
    orch = OrchestratorRecord(
        phase=phase,
        tick=state.total_cycles,
        last_tick_ts=state.event_log.rows[-1].get("ts") if rows else None,
        worker_count=len([w for w in workers if w.active]),
        is_running=True,
    )

    return RuntimeState(
        ts=time.time(),
        metrics=metrics,
        signals=signals,
        simulations=simulations,
        playbooks=playbooks,
        workers=workers,
        decisions=decisions,
        patterns=patterns,
        orchestrator=orch,
    )


def build_snapshot(state: Any, phase: str = "RESEARCH") -> RuntimeSnapshot:
    """Backward-compat entry point — delegates to build_runtime_state()."""
    return build_runtime_state(state).to_snapshot()
