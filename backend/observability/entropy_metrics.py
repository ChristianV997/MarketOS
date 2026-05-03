"""entropy_metrics — compute and emit cognitive entropy reports."""
from __future__ import annotations

import time
import uuid
import logging
from typing import Any

from .schemas.entropy_report import EntropyReport

log = logging.getLogger(__name__)

_MAX_EPISODIC = int(__import__("os").getenv("EPISODIC_MAX_EPISODES", "10000"))
_LINEAGE_DEPTH_THRESHOLD = 100


def measure_entropy(
    workspace: str = "default",
    window_s: float = 3600.0,
) -> EntropyReport:
    """Measure current cognitive entropy across all subsystems."""
    report = EntropyReport(
        report_id=uuid.uuid4().hex[:12],
        workspace=workspace,
        window_s=window_s,
    )
    _measure_vector(report)
    _measure_semantic(report)
    _measure_lineage(report, window_s)
    _measure_memory(report)
    _measure_replay(report)
    report.compute_aggregate()

    # Push to Prometheus
    try:
        from .metrics import cognitive_entropy, vector_fragmentation, semantic_duplication
        cognitive_entropy.labels(workspace=workspace).set(report.overall_entropy)
        vector_fragmentation.set(report.vector_fragmentation)
        semantic_duplication.set(report.semantic_duplication)
    except Exception:
        pass

    # Emit to event log
    try:
        from backend.events.log import append
        append(
            "observability.entropy.measured",
            payload=report.to_dict(),
            source="entropy_metrics",
        )
    except Exception:
        pass

    return report


def _measure_vector(report: EntropyReport) -> None:
    try:
        from backend.vector.qdrant_client import get_store
        from backend.vector.collections   import ALL_COLLECTIONS
        store   = get_store()
        counts  = [store.count(c) for c in ALL_COLLECTIONS]
        total   = sum(counts)
        filled  = sum(1 for c in counts if c > 0)
        report.vector_coverage     = round(filled / len(ALL_COLLECTIONS), 3)
        # Fragmentation: std_dev / mean as proxy for uneven distribution
        if total > 0 and filled > 1:
            mean = total / filled
            variance = sum((c - mean) ** 2 for c in counts if c > 0) / filled
            report.vector_fragmentation = round(min(1.0, (variance ** 0.5) / max(mean, 1)), 3)
    except Exception:
        pass


def _measure_semantic(report: EntropyReport) -> None:
    try:
        from backend.memory.semantic import get_semantic_store
        store = get_semantic_store()
        gen   = max(store.generation(), 1)
        total = store.count()
        report.semantic_duplication     = round(min(1.0, total / (gen * 10 + 1)), 3)
        report.semantic_compression_ratio = round(total / gen, 3)
    except Exception:
        pass


def _measure_lineage(report: EntropyReport, window_s: float) -> None:
    try:
        from backend.lineage import get_tracker
        tracker = get_tracker()
        total   = tracker.node_count()
        nodes   = tracker.graph().all_nodes()
        now     = time.time()
        recent  = sum(1 for n in nodes if (now - n.ts) < window_s)
        report.lineage_growth_rate = round(recent / max(window_s / 3600, 1), 3)

        # Depth pressure: fraction of nodes with chain > threshold
        if nodes:
            graph = tracker.graph()
            deep = sum(
                1 for n in nodes[:100]
                if len(graph.lineage_chain(n.node_id)) > _LINEAGE_DEPTH_THRESHOLD
            )
            report.lineage_depth_pressure = round(deep / min(len(nodes), 100), 3)
    except Exception:
        pass


def _measure_memory(report: EntropyReport) -> None:
    try:
        from backend.memory.episodic import get_episodic_store
        store = get_episodic_store()
        report.episodic_pressure = round(store.count() / _MAX_EPISODIC, 3)
    except Exception:
        pass
    try:
        from backend.memory.procedural import get_procedural_store
        store = get_procedural_store()
        procs = store.snapshot()
        if procs:
            deprecated = sum(1 for p in procs if p.get("metadata", {}).get("deprecated"))
            report.procedural_drift = round(deprecated / len(procs), 3)
    except Exception:
        pass


def _measure_replay(report: EntropyReport) -> None:
    try:
        from backend.runtime.replay_store import get_replay_store
        store = get_replay_store()
        total = store.count()
        # Amplification: replay events / unique events (proxy)
        report.replay_amplification = round(min(1.0, total / max(total * 0.9, 1)), 3)
    except Exception:
        pass
