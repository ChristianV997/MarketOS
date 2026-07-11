"""backend.runtime.task_inventory — live registry of every runtime component.

Tracks all active loops, schedulers, Celery workers, background threads,
polling intervals, queues, WebSocket emitters, and state writers in one place.

Usage:
    from backend.runtime.task_inventory import task_registry

    # In any runtime component — call at each tick/run:
    task_registry.heartbeat("background_runner", status="ok")

    # Inspect:
    task_registry.all()          # list[dict]  — for /runtime/tasks endpoint
    task_registry.to_stream()    # dict         — ready for stream.publish()
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any


# ── data model ────────────────────────────────────────────────────────────────

@dataclass
class TaskRecord:
    name: str
    kind: str           # thread | celery | scheduler | ws | state_writer | queue | loop
    description: str
    module: str = ""
    interval_s: float | None = None   # None = event-driven / on-demand
    env_required: str = ""            # env var that must be set for this task to be active
    # runtime fields (updated by heartbeat)
    last_run_ts: float | None = None
    last_status: str = "unknown"      # ok | error | idle | paused | skipped
    run_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    # ── computed ──────────────────────────────────────────────────────────────
    @property
    def active(self) -> bool:
        """True when the task is considered alive (ran within 3× its interval)."""
        if self.last_run_ts is None:
            return False
        if self.interval_s is None:
            return True
        return (time.time() - self.last_run_ts) < self.interval_s * 3

    @property
    def next_run_ts(self) -> float | None:
        if self.interval_s and self.last_run_ts:
            return self.last_run_ts + self.interval_s
        return None

    @property
    def age_s(self) -> float | None:
        return round(time.time() - self.last_run_ts, 1) if self.last_run_ts else None

    @property
    def configured(self) -> bool:
        """False when an env var is required but not set."""
        if not self.env_required:
            return True
        return bool(os.getenv(self.env_required))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["active"] = self.active
        d["configured"] = self.configured
        d["next_run_ts"] = self.next_run_ts
        d["age_s"] = self.age_s
        return d


# ── registry ──────────────────────────────────────────────────────────────────

class TaskRegistry:
    """Thread-safe singleton registry of all runtime tasks."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, TaskRecord] = {}

    def register(
        self,
        name: str,
        kind: str,
        description: str,
        module: str = "",
        interval_s: float | None = None,
        env_required: str = "",
        **metadata: Any,
    ) -> None:
        with self._lock:
            self._tasks[name] = TaskRecord(
                name=name,
                kind=kind,
                description=description,
                module=module,
                interval_s=interval_s,
                env_required=env_required,
                metadata=metadata,
            )

    def heartbeat(self, name: str, status: str = "ok") -> None:
        """Record a successful run for *name*. Creates a stub if not yet registered."""
        with self._lock:
            if name not in self._tasks:
                self._tasks[name] = TaskRecord(name=name, kind="unknown", description="auto-discovered")
            rec = self._tasks[name]
            rec.last_run_ts = time.time()
            rec.last_status = status
            rec.run_count += 1

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [t.to_dict() for t in sorted(self._tasks.values(), key=lambda t: t.kind)]

    def summary(self) -> dict[str, Any]:
        tasks = self.all()
        return {
            "total": len(tasks),
            "active": sum(1 for t in tasks if t["active"]),
            "idle": sum(1 for t in tasks if not t["active"] and t["last_run_ts"]),
            "unconfigured": sum(1 for t in tasks if not t["configured"]),
            "by_kind": _count_by(tasks, "kind"),
        }

    def to_stream(self) -> dict[str, Any]:
        return {
            "type": "task_inventory",
            "ts": time.time(),
            "summary": self.summary(),
            "tasks": self.all(),
        }

    def live_threads(self) -> list[str]:
        """Names of live Python daemon threads (from threading.enumerate)."""
        return [t.name for t in threading.enumerate() if t.daemon]


def _count_by(records: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in records:
        out[r.get(key, "unknown")] = out.get(r.get(key, "unknown"), 0) + 1
    return out


# ── singleton ─────────────────────────────────────────────────────────────────

task_registry = TaskRegistry()


# ── static registration of all known tasks ────────────────────────────────────

def _register_all() -> None:
    _TICK = float(os.getenv("ORCHESTRATOR_TICK_S", "10"))
    _CPM  = max(1, int(os.getenv("CYCLES_PER_MINUTE", "10")))

    # ── active loops / threads ─────────────────────────────────────────────
    task_registry.register(
        "background_runner",
        kind="thread",
        description="Main execution loop: run_cycle() → event_log → Prometheus → stream.publish",
        module="backend.api",
        interval_s=60.0 / _CPM,
    )
    task_registry.register(
        "research_runner",
        kind="thread",
        description="Trend ingestion: IngestionScheduler.tick() → TrendRecordStore → run_intelligence()",
        module="backend.api",
        interval_s=300,
        env_required="FF_PILLAR_A_INGESTION",
    )
    task_registry.register(
        "orchestrator_tick",
        kind="loop",
        description="Phase-aware worker dispatch (signal/execution/feedback/scaling) via PhaseController",
        module="orchestrator.main",
        interval_s=_TICK,
    )
    task_registry.register(
        "signal_ingestion_worker",
        kind="loop",
        description="_run_signal_ingestion(): Amazon/TikTok/Trends → phase_controller.record_signal()",
        module="orchestrator.main",
        interval_s=_TICK,
    )
    task_registry.register(
        "execution_cycle_worker",
        kind="loop",
        description="_run_execution_cycle(): decide→execute→learn→causal update via run_cycle()",
        module="orchestrator.main",
        interval_s=_TICK,
    )
    task_registry.register(
        "feedback_collection_worker",
        kind="loop",
        description="_run_feedback_collection(): batch_classify→extract_patterns→playbook_memory.upsert",
        module="orchestrator.main",
        interval_s=_TICK,
    )
    task_registry.register(
        "scaling_worker",
        kind="loop",
        description="_run_scaling(): portfolio.top_products → AJO scale_campaign (SCALE phase only)",
        module="orchestrator.main",
        interval_s=_TICK,
        env_required="ADOBE_AJO_TOKEN",
    )
    task_registry.register(
        "legacy_run_forever",
        kind="loop",
        description="run.py::run_forever(): legacy 300s polling loop (superseded by orchestrator)",
        module="run",
        interval_s=300,
    )

    # ── schedulers ────────────────────────────────────────────────────────
    task_registry.register(
        "ingestion_scheduler",
        kind="scheduler",
        description="IngestionScheduler: hourly cron gate for Google Trends adapter batch ingestion",
        module="backend.jobs.scheduler",
        interval_s=3600,
        env_required="FF_PILLAR_A_INGESTION",
        cron=os.getenv("INGESTION_CRON", "0 * * * *"),
    )

    # ── Celery tasks ──────────────────────────────────────────────────────
    task_registry.register(
        "celery_run_real_cycle",
        kind="celery",
        description="Celery task: execute one paid campaign cycle from a product signal dict",
        module="tasks.pipeline",
        broker=os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0"),
    )
    task_registry.register(
        "celery_run_discovery",
        kind="celery",
        description="Celery task: keyword discovery via core.bridge.Bridge (Bridge pattern)",
        module="tasks.discovery",
        broker=os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0"),
    )

    # ── queues ────────────────────────────────────────────────────────────
    task_registry.register(
        "redis_stream_upos_events",
        kind="queue",
        description="Redis stream 'upos_events': publish()/consume() — falls back to in-memory queue",
        module="core.stream",
        stream_name="upos_events",
        read_count=int(os.getenv("UPOS_STREAM_READ_COUNT", "10")),
        block_ms=int(os.getenv("UPOS_STREAM_READ_BLOCK_MS", "1000")),
    )

    # ── WebSocket emitters ────────────────────────────────────────────────
    task_registry.register(
        "ws_event_stream",
        kind="ws",
        description="api.ws::event_stream(): consumes upos_events → pushes JSON frames to /ws clients",
        module="api.ws",
        endpoint="/ws",
    )

    # ── state writers ─────────────────────────────────────────────────────
    task_registry.register(
        "sw_event_log",
        kind="state_writer",
        description="EventLog.log_batch(): appends execution results to SystemState.event_log (cap 10k)",
        module="backend.data.event_log",
        max_rows=10_000,
    )
    task_registry.register(
        "sw_serializer_duckdb",
        kind="state_writer",
        description="serializer.save(): persists SystemState to DuckDB on shutdown & every 100 cycles",
        module="backend.core.serializer",
        path=os.getenv("STATE_PATH", "state/state.db"),
    )
    task_registry.register(
        "sw_supabase",
        kind="state_writer",
        description="supabase_connector.save_cycle_summary(): upserts cycle KPIs to Supabase (optional)",
        module="connectors.supabase_connector",
        env_required="SUPABASE_URL",
    )
    task_registry.register(
        "sw_decision_trace",
        kind="state_writer",
        description="decision_trace.log_decision_trace(): JSONL append at monitoring/decision_trace.jsonl",
        module="backend.monitoring.decision_trace",
        path="backend/monitoring/decision_trace.jsonl",
    )
    task_registry.register(
        "sw_creative_memory",
        kind="state_writer",
        description="CreativeMemory.add(): 128-dim embedding store for winner ad scripts",
        module="core.memory.creative_memory",
    )
    task_registry.register(
        "sw_pattern_store",
        kind="state_writer",
        description="PatternStore.update(): thread-safe hook/angle/regime engagement score accumulator",
        module="core.content.patterns",
    )
    task_registry.register(
        "sw_playbook_memory",
        kind="state_writer",
        description="PlaybookMemory.upsert(): per-(product, phase) playbook strategy persistence",
        module="core.content.playbook",
    )
    task_registry.register(
        "sw_calibration_log",
        kind="state_writer",
        description="CalibrationLog.log(): records prediction accuracy stats each cycle",
        module="backend.learning.calibration_log",
    )
    task_registry.register(
        "sw_replay_buffer",
        kind="state_writer",
        description="ReplayBuffer: RL experience store (s, a, r, s') for offline training",
        module="backend.learning.replay_buffer",
    )
    task_registry.register(
        "sw_agent_metrics",
        kind="state_writer",
        description="AgentMetricsRegistry.record_pnl(): per-agent PnL, win/loss, drift tracking",
        module="backend.agents.agent_metrics",
    )
    task_registry.register(
        "sw_hyperparam_meta",
        kind="state_writer",
        description="hp_meta.save_hp_meta(): hyperparameter meta-learning state → backend/ci/",
        module="backend.ci.hyperparam_meta",
        path="backend/ci/hyperparams_meta.json",
    )
    task_registry.register(
        "sw_runtime_snapshot",
        kind="state_writer",
        description="build_snapshot() → stream.publish(): full RuntimeSnapshot pushed every cycle",
        module="backend.runtime.state",
    )
    task_registry.register(
        "simulation_worker",
        kind="loop",
        description="SimulationEngine.score_signals(): pre-execution scoring+ranking of signal candidates",
        module="simulation.integration",
        interval_s=10,
    )
    task_registry.register(
        "content_generation_worker",
        kind="loop",
        description="generate_creative(): PatternStore-guided hook/script generation for top sim candidates",
        module="orchestrator.main",
        interval_s=30,
    )
    task_registry.register(
        "metrics_ingestion_worker",
        kind="loop",
        description="Shopify+Meta+TikTok real metric ingestion → CalibrationStore outcome recording",
        module="orchestrator.main",
        interval_s=30,
    )


_register_all()


# ── heartbeat broadcaster ─────────────────────────────────────────────────────

_hb_thread: threading.Thread | None = None
_hb_running = False


def start_heartbeat_broadcaster(interval_s: float = 30.0) -> None:
    """Launch a background thread that publishes task inventory to the event stream."""
    global _hb_thread, _hb_running
    if _hb_thread and _hb_thread.is_alive():
        return
    _hb_running = True

    def _loop() -> None:
        while _hb_running:
            try:
                from backend.events.emitter import emit_task_inventory
                emit_task_inventory(task_registry.to_stream())
            except Exception:
                try:
                    from core.stream import publish
                    publish(task_registry.to_stream())
                except Exception:
                    pass
            time.sleep(interval_s)

    _hb_thread = threading.Thread(target=_loop, name="task_inventory_hb", daemon=True)
    _hb_thread.start()


def stop_heartbeat_broadcaster() -> None:
    global _hb_running
    _hb_running = False
