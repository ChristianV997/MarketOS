"""backend.error_telemetry — centralized error tracking for observability.

Captures all errors, their context, and frequency to help identify patterns
and prioritize fixes.

Usage:
  from backend.error_telemetry import record_error, error_summary

  try:
      result = risky_operation()
  except Exception as e:
      record_error("shopify_sync", "create_product", str(e), context={
          "product_id": product_id,
          "attempt": attempt_num,
      })

  # Later:
  summary = error_summary()
  for err in summary["by_stage"]:
      print(f"{err['stage']}: {err['count']} errors")
"""
import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from backend.core.persistence import state_path

_log = logging.getLogger(__name__)

# Error state persisted to disk (respects MARKETOS_STATE_DIR for test isolation)
_ERROR_DB_PATH = Path(state_path("errors.jsonl"))


@dataclass
class ErrorEvent:
    """One error event."""
    timestamp: float
    stage: str
    operation: str
    error_type: str
    error_msg: str
    context: dict = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["context"] = self.context or {}
        return data


def _ensure_error_db() -> None:
    """Create error database file if missing."""
    _ERROR_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _ERROR_DB_PATH.touch(exist_ok=True)


def record_error(
    stage: str,
    operation: str,
    error: str | Exception,
    context: dict = None,
) -> None:
    """Record an error event.

    Args:
      stage: Pipeline stage where error occurred (e.g., "discovery", "validation")
      operation: Specific operation (e.g., "discover_products", "quote_supplier")
      error: Error message or exception
      context: Additional context dict (e.g., product name, retries, etc.)
    """
    _ensure_error_db()

    error_str = str(error)
    error_type = type(error).__name__ if isinstance(error, Exception) else "Error"

    event = ErrorEvent(
        timestamp=time.time(),
        stage=stage,
        operation=operation,
        error_type=error_type,
        error_msg=error_str,
        context=context or {},
    )

    _log.warning(
        "error_recorded stage=%s op=%s type=%s msg=%s",
        stage, operation, error_type, error_str[:100]
    )

    try:
        with open(_ERROR_DB_PATH, "a") as f:
            f.write(json.dumps(event.to_dict()) + "\n")
    except Exception as exc:
        _log.error("Failed to write error event: %s", exc)


def _read_error_events(
    since: float = None,
    stage: str = None,
) -> list[ErrorEvent]:
    """Read error events from database, optionally filtered."""
    _ensure_error_db()
    events = []

    try:
        with open(_ERROR_DB_PATH) as f:
            for line in f:
                if not line.strip():
                    continue
                data = json.loads(line)
                event = ErrorEvent(
                    timestamp=data["timestamp"],
                    stage=data["stage"],
                    operation=data["operation"],
                    error_type=data["error_type"],
                    error_msg=data["error_msg"],
                    context=data.get("context", {}),
                )

                if since and event.timestamp < since:
                    continue
                if stage and event.stage != stage:
                    continue

                events.append(event)
    except Exception as exc:
        _log.error("Failed to read error events: %s", exc)

    return events


def error_summary(
    lookback_minutes: int = 1440,  # 24 hours
    top_n: int = 10,
) -> dict[str, Any]:
    """Summarize errors over a time window.

    Args:
      lookback_minutes: How far back to look
      top_n: Show top N errors

    Returns:
      {
        "total_errors": int,
        "by_stage": [{stage, count, operations}],
        "by_operation": [{operation, count, errors}],
        "top_errors": [{error_type, error_msg, count}],
        "affected_products": [...],
        "period_hours": float,
      }
    """
    since = time.time() - (lookback_minutes * 60)
    events = _read_error_events(since=since)

    if not events:
        return {
            "total_errors": 0,
            "by_stage": [],
            "by_operation": [],
            "top_errors": [],
            "affected_products": [],
            "period_hours": lookback_minutes / 60,
        }

    # Aggregate by stage
    by_stage = {}
    by_op = {}
    error_counts = {}
    affected_products = set()

    for evt in events:
        # By stage
        if evt.stage not in by_stage:
            by_stage[evt.stage] = {"count": 0, "operations": set()}
        by_stage[evt.stage]["count"] += 1
        by_stage[evt.stage]["operations"].add(evt.operation)

        # By operation
        if evt.operation not in by_op:
            by_op[evt.operation] = {"count": 0, "errors": []}
        by_op[evt.operation]["count"] += 1

        # Aggregate similar errors
        error_key = f"{evt.error_type}:{evt.error_msg[:80]}"
        if error_key not in error_counts:
            error_counts[error_key] = 0
        error_counts[error_key] += 1

        # Track affected products from context
        if "product" in evt.context:
            affected_products.add(evt.context["product"])

    # Build response
    by_stage_sorted = sorted(
        [
            {"stage": s, "count": d["count"], "operations": len(d["operations"])}
            for s, d in by_stage.items()
        ],
        key=lambda x: x["count"],
        reverse=True,
    )

    by_op_sorted = sorted(
        [
            {"operation": o, "count": d["count"]}
            for o, d in by_op.items()
        ],
        key=lambda x: x["count"],
        reverse=True,
    )[:top_n]

    top_errors = sorted(
        [
            {
                "error": k.split(":")[0],
                "message": k.split(":")[1] if ":" in k else "",
                "count": v,
            }
            for k, v in error_counts.items()
        ],
        key=lambda x: x["count"],
        reverse=True,
    )[:top_n]

    return {
        "total_errors": len(events),
        "by_stage": by_stage_sorted,
        "by_operation": by_op_sorted,
        "top_errors": top_errors,
        "affected_products": sorted(list(affected_products))[:20],
        "period_hours": round(lookback_minutes / 60, 1),
    }


def error_details(
    stage: str = None,
    operation: str = None,
    limit: int = 10,
) -> list[dict]:
    """Get detailed error records (most recent first).

    Returns list of {timestamp, stage, operation, error_type, error_msg, context}
    """
    events = _read_error_events(stage=stage)
    if operation:
        events = [e for e in events if e.operation == operation]

    # Sort by timestamp descending, take limit
    events = sorted(events, key=lambda e: e.timestamp, reverse=True)[:limit]

    return [
        {
            "timestamp": e.timestamp,
            "stage": e.stage,
            "operation": e.operation,
            "error_type": e.error_type,
            "error_msg": e.error_msg,
            "context": e.context,
        }
        for e in events
    ]


__all__ = [
    "record_error",
    "error_summary",
    "error_details",
    "ErrorEvent",
]
