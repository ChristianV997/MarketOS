"""EntropyReport — cognitive entropy metrics for one measurement period."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EntropyReport:
    """Quantifies cognitive entropy across all memory and lineage systems.

    Entropy here means: disorder, fragmentation, redundancy, and drift
    that accumulates between sleep cycles.  High entropy → consolidation
    urgency.  Low entropy → system is well-consolidated.

    Ranges are all [0.0, 1.0] normalized unless noted.
    """
    report_id:   str
    measured_at: float = field(default_factory=time.time)
    workspace:   str   = "default"
    window_s:    float = 3600.0

    # Vector layer entropy
    vector_fragmentation:   float = 0.0  # duplicate centroids / total
    vector_coverage:        float = 0.0  # non-empty collections / total

    # Semantic entropy
    semantic_duplication:   float = 0.0  # near-duplicate unit ratio
    semantic_drift:         float = 0.0  # generation delta / time
    semantic_compression_ratio: float = 0.0  # units / episodes processed

    # Lineage entropy
    lineage_growth_rate:    float = 0.0  # new nodes / window_s
    lineage_depth_pressure: float = 0.0  # nodes > threshold / total
    lineage_orphan_rate:    float = 0.0  # nodes with no workspace match

    # Memory entropy
    episodic_pressure:      float = 0.0  # fill ratio of EpisodicStore
    procedural_drift:       float = 0.0  # deprecated / total procedures
    replay_amplification:   float = 0.0  # replay events / original events

    # Aggregate
    overall_entropy:        float = 0.0  # weighted average
    consolidation_urgency:  str   = "low"  # low / medium / high / critical

    def compute_aggregate(self) -> None:
        """Compute overall_entropy and consolidation_urgency from components."""
        components = [
            self.vector_fragmentation,
            self.semantic_duplication,
            self.lineage_depth_pressure,
            self.episodic_pressure,
            self.procedural_drift,
        ]
        valid = [c for c in components if 0.0 <= c <= 1.0]
        self.overall_entropy = round(sum(valid) / len(valid), 4) if valid else 0.0

        if self.overall_entropy >= 0.75:
            self.consolidation_urgency = "critical"
        elif self.overall_entropy >= 0.5:
            self.consolidation_urgency = "high"
        elif self.overall_entropy >= 0.25:
            self.consolidation_urgency = "medium"
        else:
            self.consolidation_urgency = "low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id":              self.report_id,
            "measured_at":            self.measured_at,
            "workspace":              self.workspace,
            "window_s":               self.window_s,
            "vector_fragmentation":   self.vector_fragmentation,
            "vector_coverage":        self.vector_coverage,
            "semantic_duplication":   self.semantic_duplication,
            "semantic_drift":         self.semantic_drift,
            "lineage_growth_rate":    self.lineage_growth_rate,
            "lineage_depth_pressure": self.lineage_depth_pressure,
            "episodic_pressure":      self.episodic_pressure,
            "procedural_drift":       self.procedural_drift,
            "replay_amplification":   self.replay_amplification,
            "overall_entropy":        self.overall_entropy,
            "consolidation_urgency":  self.consolidation_urgency,
        }
