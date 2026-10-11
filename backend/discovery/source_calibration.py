from __future__ import annotations

import json
import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

# Descriptive policy: calibration reports observed changes and may reorder import
# recommendations within a bound. It never proves causality and never changes
# evidence safety, record confidence, or live/fixture labels.
CALIBRATION_POLICY_VERSION = "source-calibration-policy-v1"
MIN_COMPARISONS_FOR_ADJUSTMENT = 2
MIN_ELIGIBLE_SIGNALS_FOR_ADJUSTMENT = 3
STALE_AFTER_SECONDS = 90 * 24 * 3600
MAX_ORDERING_EFFECT = 10.0
WILSON_Z_95 = 1.959963984540054

ELIGIBLE = ""
EXCLUSION_AMBIGUOUS = "ambiguous_multi_source"
EXCLUSION_UNMATCHED = "unmatched_import"
EXCLUSION_AMBIGUOUS_IMPORT = "ambiguous_import_source"
EXCLUSION_STALE = "stale_comparison"
# Import-quality facts describe evidence quality, which the normalizer and source-quality scorer already own.
# They are kept and counted, but they never drive an adjustment or count toward the observation gate.
EXCLUSION_IMPORT_QUALITY = "import_quality_not_comparison"


@dataclass
class SourceUsefulnessSignal:
    signal_id: str
    workspace_id: str
    source_name: str
    source_type: str
    parser_type: str
    related_import_id: str = ""
    baseline_discovery_id: str = ""
    current_discovery_id: str = ""
    comparison_id: str = ""
    signal_type: str = ""
    entity_type: str = "category"
    entity_name: str = ""
    value: float = 0.0
    weight: float = 1.0
    confidence: float = 0.5
    rationale: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    attribution: str = "single_source"
    exclusion_reason: str = ELIGIBLE

    def __post_init__(self):
        self.weight = max(0.0, min(float(self.weight), 1.0))
        self.confidence = max(0.0, min(float(self.confidence), 1.0))
        self.value = float(self.value)

    @property
    def eligible(self) -> bool:
        return not self.exclusion_reason

    def to_dict(self): return {key: getattr(self, key) for key in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data): return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


@dataclass
class SourceCalibrationProfile:
    profile_id: str
    workspace_id: str
    source_name: str
    source_type: str
    parser_type: str
    usefulness_score: float = 50.0
    confidence_multiplier_adjustment: float = 1.0
    recommended_priority_adjustment: float = 0.0
    positive_signal_count: int = 0
    negative_signal_count: int = 0
    neutral_signal_count: int = 0
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    best_signal_types: list[str] = field(default_factory=list)
    poor_signal_types: list[str] = field(default_factory=list)
    last_updated_at: float = field(default_factory=time.time)
    provenance: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    evidence_status: str = "no_eligible_signals"
    eligible_signal_count: int = 0
    excluded_signal_count: int = 0
    comparison_count: int = 0
    exclusion_counts: dict[str, int] = field(default_factory=dict)
    positive_share_lower_95: float = 0.0
    positive_share_upper_95: float = 1.0
    policy_version: str = CALIBRATION_POLICY_VERSION

    def __post_init__(self):
        self.usefulness_score = max(0.0, min(float(self.usefulness_score), 100.0))
        self.confidence_multiplier_adjustment = max(0.25, min(float(self.confidence_multiplier_adjustment), 1.25))
        self.recommended_priority_adjustment = max(-25.0, min(float(self.recommended_priority_adjustment), 25.0))
        self.positive_share_lower_95 = max(0.0, min(float(self.positive_share_lower_95), 1.0))
        self.positive_share_upper_95 = max(0.0, min(float(self.positive_share_upper_95), 1.0))

    def to_dict(self): return {key: getattr(self, key) for key in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data): return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


@dataclass
class CalibrationRun:
    calibration_id: str
    workspace_id: str
    title: str
    objective: str
    signals: list[SourceUsefulnessSignal] = field(default_factory=list)
    profiles: list[SourceCalibrationProfile] = field(default_factory=list)
    summary: str = ""
    recommendations: list[str] = field(default_factory=list)
    status: str = "completed"
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self): return {key: [x.to_dict() for x in value] if key in {"signals", "profiles"} else value for key, value in ((key, getattr(self, key)) for key in self.__dataclass_fields__)}

    @classmethod
    def from_dict(cls, data):
        data = dict(data); data["signals"] = [SourceUsefulnessSignal.from_dict(x) for x in data.get("signals", [])]; data["profiles"] = [SourceCalibrationProfile.from_dict(x) for x in data.get("profiles", [])]
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})

    def to_markdown(self):
        rows = "\n".join(
            f"- **{p.source_name} / {p.parser_type}** — evidence `{p.evidence_status}` ({p.eligible_signal_count} eligible signals, {p.comparison_count} comparisons), usefulness `{p.usefulness_score:.1f}`, priority adjustment `{p.recommended_priority_adjustment:+.1f}`, strengths: {', '.join(p.strengths) or 'none'}, weaknesses: {', '.join(p.weaknesses) or 'none'}"
            for p in self.profiles
        ) or "- No calibrated profiles available."
        return f"# {self.title}\n\n**Status:** `{self.status}`  \n**Summary:** {self.summary}\n\n## Profiles\n\n{rows}\n\n## Recommendations\n\n" + "\n".join(f"- {x}" for x in self.recommendations) + "\n\n## Interpretation\n\nThese profiles describe observed changes after evidence inclusion. They are not causal claims and do not prove that a source improved a market or category. A profile is only `observed` when its sample and attribution meet the policy; otherwise its adjustments are neutral.\n"


def _signal_sign(signal_type: str) -> float:
    return {"evidence_count_increase": 1, "confidence_increase": 1, "gap_reduction": 1, "rank_improvement": 1, "recommendation_upgrade": 1, "risk_reduction": 1, "duplicate_noise": -1, "low_confidence_noise": -1, "unsupported_signal_rejection": -1}.get(signal_type, 0)


def signal_order_key(signal: SourceUsefulnessSignal) -> tuple[str, str, str, str, str, str]:
    """A total order over signals, so that aggregation never depends on input order."""
    return (signal.workspace_id, signal.source_name, signal.parser_type, signal.comparison_id, signal.signal_type, signal.entity_name, signal.signal_id)


def wilson_interval(successes: int, trials: int, z: float = WILSON_Z_95) -> tuple[float, float]:
    """Wilson score interval for a proportion. With no trials the interval is the whole [0, 1]."""
    if trials <= 0:
        return (0.0, 1.0)
    p = successes / trials
    z2 = z * z
    denominator = 1 + z2 / trials
    centre = (p + z2 / (2 * trials)) / denominator
    half = z * math.sqrt(p * (1 - p) / trials + z2 / (4 * trials * trials)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def stable_id(prefix: str, payload: Any) -> str:
    """Content-derived identifier. Canonical JSON keeps it unambiguous when a value contains a separator."""
    return prefix + uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)).hex[:16]


def profile_identity(workspace_id: str, source_name: str, parser_type: str) -> str:
    return stable_id("profile_", [workspace_id, source_name, parser_type])


def build_source_calibration_profiles(signals: list[SourceUsefulnessSignal], existing_profiles: list[SourceCalibrationProfile] | None = None) -> list[SourceCalibrationProfile]:
    """Aggregate signals per (workspace, source, parser). Input order does not change the result."""
    groups: dict[tuple[str, str, str], list[SourceUsefulnessSignal]] = {}
    for signal in sorted(signals, key=signal_order_key):
        groups.setdefault((signal.workspace_id, signal.source_name, signal.parser_type), []).append(signal)
    profiles = []
    for key, items in sorted(groups.items()):
        eligible = [x for x in items if x.eligible]
        exclusions: dict[str, int] = {}
        for x in items:
            if not x.eligible:
                exclusions[x.exclusion_reason] = exclusions.get(x.exclusion_reason, 0) + 1
        comparisons = {x.comparison_id for x in eligible if x.comparison_id}
        positive = sum(_signal_sign(x.signal_type) > 0 for x in eligible)
        negative = sum(_signal_sign(x.signal_type) < 0 for x in eligible)
        neutral = len(eligible) - positive - negative
        weighted = math.fsum(_signal_sign(x.signal_type) * min(abs(x.value), 25.0) / 25.0 * x.weight * x.confidence for x in eligible)
        if not eligible:
            status = "no_eligible_signals"
        elif len(eligible) >= MIN_ELIGIBLE_SIGNALS_FOR_ADJUSTMENT and len(comparisons) >= MIN_COMPARISONS_FOR_ADJUSTMENT:
            status = "observed"
        else:
            status = "limited"
        observed = status == "observed"
        score = max(0.0, min(100.0, 50.0 + weighted * 12.0)) if observed else 50.0
        adjustment = max(-25.0, min(25.0, weighted * 8.0)) if observed else 0.0
        multiplier = max(0.25, min(1.25, 1.0 + weighted * 0.03)) if observed else 1.0
        lower, upper = wilson_interval(positive, positive + negative)
        strengths = sorted({x.signal_type for x in eligible if _signal_sign(x.signal_type) > 0})
        weaknesses = sorted({x.signal_type for x in eligible if _signal_sign(x.signal_type) < 0})
        source_types = sorted({x.source_type for x in items})
        profiles.append(SourceCalibrationProfile(
            profile_identity(*key), key[0], key[1], source_types[0] if len(source_types) == 1 else "mixed", key[2],
            score, multiplier, adjustment, positive, negative, neutral, strengths, weaknesses, strengths, weaknesses,
            last_updated_at=max(x.created_at for x in items),
            provenance={"method": "deterministic_observed_change_aggregation", "non_causal": True, "policy_version": CALIBRATION_POLICY_VERSION, "attribution": "single_source_eligible_only", "interval": "wilson_95_over_signals", "interval_caveat": "signals from one comparison are correlated, so the interval is optimistic"},
            metadata={"signal_count": len(items), "source_type_conflict": len(source_types) > 1},
            evidence_status=status, eligible_signal_count=len(eligible), excluded_signal_count=len(items) - len(eligible),
            comparison_count=len(comparisons), exclusion_counts=dict(sorted(exclusions.items())),
            positive_share_lower_95=lower, positive_share_upper_95=upper,
        ))
    return profiles
