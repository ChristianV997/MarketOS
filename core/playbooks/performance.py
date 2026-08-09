"""core.playbooks.performance — track per-playbook performance by geo/platform."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

PLAYBOOK_PERF: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)


def record(playbook_id: str, geo: str, platform: str, metrics: dict[str, Any]) -> None:
    """Append *metrics* for *playbook_id* in *geo*/*platform* context."""
    PLAYBOOK_PERF[(playbook_id, geo, platform)].append(metrics)


def get_avg(playbook_id: str, geo: str, platform: str) -> dict[str, float] | None:
    """Return averaged CTR/ROAS for the given context, or ``None`` if no data."""
    data = PLAYBOOK_PERF.get((playbook_id, geo, platform), [])
    if not data:
        return None
    return {
        "ctr": sum(d.get("ctr", 0.0) for d in data) / len(data),
        "roas": sum(d.get("roas", 0.0) for d in data) / len(data),
    }


def clear() -> None:
    """Reset all recorded performance data (useful in tests)."""
    PLAYBOOK_PERF.clear()
