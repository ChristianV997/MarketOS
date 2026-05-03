"""topology_diff — compute structural diff between two topology snapshots."""
from __future__ import annotations

from typing import Any


def diff_snapshots(
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    """Return added/removed node_ids and type count deltas between two snapshot dicts."""
    before_ids = {n["node_id"] for n in before.get("nodes", [])}
    after_ids  = {n["node_id"] for n in after.get("nodes", [])}

    before_types: dict[str, int] = {}
    for n in before.get("nodes", []):
        before_types[n["node_type"]] = before_types.get(n["node_type"], 0) + 1

    after_types: dict[str, int] = {}
    for n in after.get("nodes", []):
        after_types[n["node_type"]] = after_types.get(n["node_type"], 0) + 1

    all_types = set(before_types) | set(after_types)
    type_deltas = {t: after_types.get(t, 0) - before_types.get(t, 0) for t in all_types}

    return {
        "added_count": len(after_ids - before_ids),
        "removed_count": len(before_ids - after_ids),
        "added_ids": sorted(after_ids - before_ids)[:50],
        "removed_ids": sorted(before_ids - after_ids)[:50],
        "type_deltas": type_deltas,
    }
