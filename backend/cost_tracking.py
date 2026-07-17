"""backend.cost_tracking — real-time API cost tracking and optimization insights.

Tracks costs per API call so we can profile the economics of each pipeline stage
and identify optimization opportunities.

Example:
  from backend.cost_tracking import track_api_call, cost_report

  with track_api_call("meta_ads", "create_campaign", cost_usd=0.0001):
      response = meta_ads_client.create_campaign(...)

  # Later:
  report = cost_report()
  print(f"Total spend this cycle: ${report['total_spend']:.2f}")
"""
import json
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Generator

from backend.core.persistence import state_path

_log = logging.getLogger(__name__)

# Cost state persisted to disk (respects MARKETOS_STATE_DIR for test isolation)
_COST_DB_PATH = Path(state_path("costs.jsonl"))


@dataclass
class CostEvent:
    """One API call cost event."""
    timestamp: float
    service: str
    operation: str
    cost_usd: float
    success: bool = True
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _ensure_cost_db() -> None:
    """Create cost database file if missing."""
    _COST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _COST_DB_PATH.touch(exist_ok=True)


@contextmanager
def track_api_call(
    service: str,
    operation: str,
    cost_usd: float = 0.0,
) -> Generator[None, None, None]:
    """Context manager to track API call cost.

    Args:
      service: e.g., "meta_ads", "shopify", "tiktok"
      operation: e.g., "create_campaign", "get_product"
      cost_usd: estimated cost of this call (if known)

    Usage:
      with track_api_call("meta_ads", "create_campaign", cost_usd=0.0001):
          response = client.create_campaign(...)
    """
    _ensure_cost_db()
    start = time.time()
    success = False
    error = ""

    try:
        yield
        success = True
    except Exception as exc:
        error = str(exc)
        raise
    finally:
        event = CostEvent(
            timestamp=start,
            service=service,
            operation=operation,
            cost_usd=cost_usd,
            success=success,
            error=error,
        )
        _log.debug(
            "api_cost service=%s op=%s cost=$%.4f success=%s",
            service, operation, cost_usd, success
        )
        _write_cost_event(event)


def _write_cost_event(event: CostEvent) -> None:
    """Append event to cost database."""
    try:
        with open(_COST_DB_PATH, "a") as f:
            f.write(json.dumps(event.to_dict()) + "\n")
    except Exception as exc:
        _log.error("Failed to write cost event: %s", exc)


def _read_cost_events(
    since: float = None,
    service: str = None,
) -> list[CostEvent]:
    """Read cost events from database, optionally filtered."""
    _ensure_cost_db()
    events = []

    try:
        with open(_COST_DB_PATH) as f:
            for line in f:
                if not line.strip():
                    continue
                data = json.loads(line)
                event = CostEvent(**data)

                if since and event.timestamp < since:
                    continue
                if service and event.service != service:
                    continue

                events.append(event)
    except Exception as exc:
        _log.error("Failed to read cost events: %s", exc)

    return events


def cost_report(
    lookback_minutes: int = 60,
    service: str = None,
) -> dict[str, Any]:
    """Generate cost report for the last N minutes.

    Args:
      lookback_minutes: Window to analyze
      service: Filter to specific service, or None for all

    Returns:
      {
        "total_spend": float,
        "num_calls": int,
        "num_successes": int,
        "num_errors": int,
        "by_operation": {operation: {count, spend}},
        "by_service": {service: {count, spend}},
        "avg_cost_per_call": float,
      }
    """
    since = time.time() - (lookback_minutes * 60)
    events = _read_cost_events(since=since, service=service)

    if not events:
        return {
            "total_spend": 0.0,
            "num_calls": 0,
            "num_successes": 0,
            "num_errors": 0,
            "by_operation": {},
            "by_service": {},
            "avg_cost_per_call": 0.0,
            "period_minutes": lookback_minutes,
        }

    by_op = {}
    by_svc = {}
    total_spend = 0.0
    num_success = 0
    num_error = 0

    for evt in events:
        total_spend += evt.cost_usd
        if evt.success:
            num_success += 1
        else:
            num_error += 1

        # By operation
        key = evt.operation
        if key not in by_op:
            by_op[key] = {"count": 0, "spend": 0.0}
        by_op[key]["count"] += 1
        by_op[key]["spend"] += evt.cost_usd

        # By service
        key = evt.service
        if key not in by_svc:
            by_svc[key] = {"count": 0, "spend": 0.0}
        by_svc[key]["count"] += 1
        by_svc[key]["spend"] += evt.cost_usd

    return {
        "total_spend": round(total_spend, 4),
        "num_calls": len(events),
        "num_successes": num_success,
        "num_errors": num_error,
        "error_rate": round(num_error / len(events) if events else 0, 3),
        "by_operation": by_op,
        "by_service": by_svc,
        "avg_cost_per_call": round(total_spend / len(events) if events else 0, 5),
        "period_minutes": lookback_minutes,
    }


def cost_timeline(
    lookback_minutes: int = 60,
    bucket_minutes: int = 5,
) -> list[dict]:
    """Cost timeline bucketed by time.

    Returns list of {timestamp, bucket_start, bucket_end, spend, num_calls}
    """
    since = time.time() - (lookback_minutes * 60)
    events = _read_cost_events(since=since)

    if not events:
        return []

    # Bucket events by time
    buckets = {}
    bucket_size_s = bucket_minutes * 60

    for evt in events:
        bucket_idx = int(evt.timestamp / bucket_size_s)
        bucket_start = bucket_idx * bucket_size_s
        bucket_end = bucket_start + bucket_size_s

        key = (bucket_start, bucket_end)
        if key not in buckets:
            buckets[key] = {"spend": 0.0, "calls": 0}

        buckets[key]["spend"] += evt.cost_usd
        buckets[key]["calls"] += 1

    # Convert to list, sorted by time
    result = [
        {
            "bucket_start": k[0],
            "bucket_end": k[1],
            "timestamp": (k[0] + k[1]) / 2,  # Midpoint
            "spend": round(v["spend"], 4),
            "num_calls": v["calls"],
        }
        for k, v in sorted(buckets.items())
    ]

    return result


__all__ = [
    "track_api_call",
    "cost_report",
    "cost_timeline",
    "CostEvent",
]
