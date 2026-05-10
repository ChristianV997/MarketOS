"""backend.events.schemas — canonical event type constants and payload shapes.

ONE place to define every event ``type`` string used across the runtime:
  - orchestrator (orchestrator/main.py)
  - background workers (backend/api.py)
  - simulation layer (simulation/)
  - WebSocket stream (api/ws.py, core/stream.py)
  - frontend (frontend/src/types/index.ts)

Consumers must switch on these constants, not raw strings.
Publishers must set ``event["type"] = <CONSTANT>`` before calling stream.publish().

Backward-compatible aliases are provided for the legacy short-form names
("tick", "worker", "snapshot", "task_inventory") so the existing frontend
continues to work without changes.
"""
from __future__ import annotations

# ── schema version — increment on breaking payload changes ───────────────────

EVENT_VERSION = 1

# ── canonical dotted event types ─────────────────────────────────────────────

ORCHESTRATOR_TICK    = "orchestrator.tick"
SIGNALS_UPDATED      = "signals.updated"
SIMULATION_COMPLETED = "simulation.completed"
PLAYBOOK_UPDATED     = "playbook.updated"
CAMPAIGN_UPDATED     = "campaign.updated"
ANOMALY_DETECTED     = "anomaly.detected"
WORKER_HEALTH        = "worker.health"
RUNTIME_SNAPSHOT     = "runtime.snapshot"
TASK_INVENTORY       = "task_inventory"      # kept as-is — frontend matches this
DECISION_LOGGED      = "decision.logged"
METRICS_INGESTED     = "metrics.ingested"    # engagement/retention/campaign metrics
HEARTBEAT            = "heartbeat"           # periodic runtime liveness signal
RUNTIME_CONSISTENCY  = "runtime.consistency" # validation failures / drift warnings
CAMPAIGN_LAUNCHED    = "campaign.launched"   # campaign created; carries full attribution lineage
SKILL_EXECUTED       = "skill.executed"
SKILL_FAILED         = "skill.failed"

# ── inference kernel events ───────────────────────────────────────────────────

INFERENCE_COMPLETED        = "inference.completed"          # successful model call (all providers)
INFERENCE_FAILED           = "inference.failed"             # provider call failed (before fallback)
INFERENCE_FALLBACK         = "inference.fallback"           # fallback provider activated
EMBEDDING_COMPLETED        = "inference.embedding.completed" # embedding batch completed

# ── legacy aliases (frontend still uses these; keep until frontend migrated) ──

# "tick"     → ORCHESTRATOR_TICK (frontend reads phase/avg_roas/capital)
# "worker"   → WORKER_HEALTH     (frontend reads worker name + status)
# "snapshot" → RUNTIME_SNAPSHOT  (frontend reads full RuntimeSnapshot)

# The frontend type discriminator checks ev.type — to maintain backward compat
# we keep publishing "snapshot"/"tick"/"worker" strings. Introduce dotted types
# in parallel; migrate frontend in a subsequent PR.

LEGACY_TICK     = "tick"      # existing frontend handles this
LEGACY_WORKER   = "worker"    # existing frontend handles this
LEGACY_SNAPSHOT = "snapshot"  # existing frontend handles this


# ── payload shape documentation (TypedDict-style, no runtime overhead) ────────
#
# ORCHESTRATOR_TICK / LEGACY_TICK:
#   {"type": str, "phase": str, "avg_roas": float, "capital": float,
#    "win_rate": float, "signal_count": int, "ts": float}
#
# WORKER_HEALTH / LEGACY_WORKER:
#   {"type": str, "worker": str, "phase": str, "status": str, "ts": float,
#    **extra: str|int|float}  # worker-specific metrics
#
# RUNTIME_SNAPSHOT / LEGACY_SNAPSHOT:
#   Full RuntimeSnapshot.to_dict() — see backend/runtime/state.py
#
# SIGNALS_UPDATED:
#   {"type": str, "signals": list[dict], "count": int, "ts": float}
#
# SIMULATION_COMPLETED:
#   {"type": str, "scores": list[dict], "top_product": str|None,
#    "signals_scored": int, "ts": float}
#
# TASK_INVENTORY:
#   {"type": "task_inventory", "ts": float, "summary": dict, "tasks": list}
#
# DECISION_LOGGED:
#   {"type": str, "product": str, "label": str, "roas": float,
#    "hook": str, "angle": str, "ts": float}
#
# METRICS_INGESTED:
#   {"type": str, "source": str, "metrics": dict, "ts": float}
#   metrics dict may include: engagement_rate, retention_rate, ctr, cvr,
#   spend, revenue, roas, views, likes, shares, comments, impressions
#
# HEARTBEAT:
#   {"type": "heartbeat", "source": str, "ts": float}
#
# RUNTIME_CONSISTENCY:
#   {"type": str, "issues": list[str], "source": str, "ts": float}
