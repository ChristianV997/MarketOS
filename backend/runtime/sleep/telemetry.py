"""backend.runtime.sleep.telemetry — sleep cycle event emission."""
from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)

_CONSOLIDATION_COMPLETED = "sleep.consolidation.completed"
_DECAY_APPLIED           = "sleep.decay.applied"
_CHECKPOINT_CREATED      = "sleep.semantic.checkpoint"
_LINEAGE_SUMMARIZED      = "sleep.lineage.summarized"
_SCHEDULER_TICK          = "sleep.scheduler.tick"
_COMPACTION_COMPLETED    = "sleep.compaction.completed"


def _broker():
    try:
        from backend.pubsub.broker import get_broker
        return get_broker()
    except Exception:
        return None


def _safe_publish(event_type: str, payload: dict[str, Any]) -> None:
    b = _broker()
    if b is None:
        return
    try:
        b.publish(
            event_type,
            {"type": event_type, "ts": time.time(), **payload},
            source="sleep_runtime",
        )
    except Exception as exc:
        log.debug("sleep.telemetry publish failed (%s): %s", event_type, exc)


def emit_consolidation_completed(result: Any) -> None:
    _safe_publish(_CONSOLIDATION_COMPLETED, {
        "cycle_id":              getattr(result, "cycle_id", ""),
        "workspace":             getattr(result, "workspace", ""),
        "episodes_read":         getattr(result, "episodes_read", 0),
        "semantic_units_created": getattr(result, "semantic_units_created", 0),
        "procedures_reinforced": getattr(result, "procedures_reinforced", 0),
        "compression_ratio":     getattr(result, "compression_ratio", 0.0),
        "duration_s":            getattr(result, "duration_s", 0.0),
        "ok":                    getattr(result, "ok", False),
    })


def emit_decay_applied(semantic_pruned: dict, deprecated: int) -> None:
    _safe_publish(_DECAY_APPLIED, {
        "semantic_pruned":    semantic_pruned,
        "procedures_deprecated": deprecated,
    })


def emit_checkpoint_created(checkpoint_id: str, generation: int, unit_count: int) -> None:
    _safe_publish(_CHECKPOINT_CREATED, {
        "checkpoint_id": checkpoint_id,
        "generation":    generation,
        "unit_count":    unit_count,
    })


def emit_lineage_summarized(summary_count: int, collapsed_count: int, workspace: str) -> None:
    _safe_publish(_LINEAGE_SUMMARIZED, {
        "summary_count":  summary_count,
        "collapsed_count": collapsed_count,
        "workspace":      workspace,
    })


def emit_compaction_completed(counts: dict[str, int], cycle_id: str) -> None:
    _safe_publish(_COMPACTION_COMPLETED, {
        "domain_counts": counts,
        "cycle_id":      cycle_id,
        "total":         sum(counts.values()),
    })
