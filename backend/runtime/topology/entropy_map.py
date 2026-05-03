"""entropy_map — overlay entropy scores onto a topology graph."""
from __future__ import annotations

from typing import Any


def entropy_overlay(workspace: str = "default") -> dict[str, Any]:
    """Return per-node-type entropy scores for the workspace."""
    result: dict[str, Any] = {"workspace": workspace, "scores": {}}
    try:
        from backend.observability.entropy_metrics import measure_entropy
        report = measure_entropy(workspace=workspace)
        result["scores"] = {
            "semantic": report.semantic_duplication,
            "vector": report.vector_fragmentation,
            "lineage": report.lineage_depth_pressure,
            "episodic": report.episodic_pressure,
            "procedural": report.procedural_drift,
            "replay": report.replay_amplification,
        }
        result["overall"] = report.overall_entropy
        result["urgency"] = report.consolidation_urgency
    except Exception:
        pass
    return result
