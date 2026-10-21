from __future__ import annotations

import logging
import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .evidence_gap import EvidenceGapAnalysis
from .calibration_registry import get_calibration_registry
from .source_calibration import CALIBRATION_POLICY_VERSION, MAX_ORDERING_EFFECT, STALE_AFTER_SECONDS, stable_id

_log = logging.getLogger(__name__)

# A severe gap is never ordered below this, whatever calibration says.
CRITICAL_PRIORITY_FLOOR = 70.0


_FIELDS = {
    "google_trends_csv": (["category", "keyword", "trend_score"], ["growth", "region", "timeframe"]),
    "tiktok_creative_center_csv": (["category", "product"], ["views", "likes", "ctr", "cvr", "creative_type", "region"]),
    "amazon_bestsellers_csv": (["category", "product", "rank"], ["price", "review_count", "rating"]),
    "meta_ad_library_csv": (["category", "product", "ad_count"], ["advertiser", "active_days", "platform", "region"]),
    "reddit_keyword_csv": (["keyword", "category"], ["subreddit", "mentions", "upvotes", "comments", "pain_point", "sentiment"]),
    "mercadolibre_snapshot_csv": (["category", "product", "price"], ["sold_count", "rating", "reviews", "seller_count"]),
    "supplier_catalog_csv": (["category", "candidate_id", "product", "supplier_cost"], ["shipping_cost", "moq", "lead_time_days", "availability", "supplier"]),
    "shopify_orders_csv": (["product", "category", "net_sales"], ["gross_sales", "quantity", "refunds", "discount", "created_at"]),
    "stripe_payments_csv": (["product", "amount", "currency", "status"], ["refunded", "created_at"]),
    "generic_market_csv": (["entity_type", "entity_name", "signal_type", "value"], ["weight", "confidence", "category", "metadata_json"]),
}


@dataclass
class ImportRecommendation:
    recommendation_id: str
    workspace_id: str
    parser_type: str
    source_name_suggestion: str
    title: str
    reason: str
    priority_score: float
    expected_signal_types: list[str] = field(default_factory=list)
    required_fields: list[str] = field(default_factory=list)
    optional_fields: list[str] = field(default_factory=list)
    related_gap_ids: list[str] = field(default_factory=list)
    template_path: str = ""
    status: str = "recommended"
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    def __post_init__(self) -> None: self.priority_score = max(0.0, min(float(self.priority_score), 100.0))
    def to_dict(self) -> dict[str, Any]: return {key: getattr(self, key) for key in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImportRecommendation": return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


@dataclass
class ImportRecommendationPlan:
    plan_id: str
    workspace_id: str
    title: str
    recommendations: list[ImportRecommendation] = field(default_factory=list)
    coverage_summary: dict[str, Any] = field(default_factory=dict)
    status: str = "completed"
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    def to_dict(self) -> dict[str, Any]: return {key: [item.to_dict() for item in value] if key == "recommendations" else value for key, value in ((key, getattr(self, key)) for key in self.__dataclass_fields__)}
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImportRecommendationPlan":
        data = dict(data); data["recommendations"] = [ImportRecommendation.from_dict(item) for item in data.get("recommendations", [])]; return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})
    def to_markdown(self) -> str:
        rows = "\n".join(f"- **{item.title}** — priority `{item.priority_score:.1f}`; required columns: `{', '.join(item.required_fields)}`; template: `{item.template_path or 'not created'}`" for item in self.recommendations) or "- No imports recommended."
        return f"# {self.title}\n\n{rows}\n\n## Operator instruction\n\nExport the listed fields into the template under `data/import_templates/`, then use the local import-and-run workflow. No live provider access is required.\n"


def _freshness(profile: Any, as_of: float) -> str:
    """Judge a profile against the plan's own time: current, stale, or dated after the plan."""
    age = as_of - float(profile.last_updated_at)
    if age < 0:
        return "profile_after_plan_time"
    if age > STALE_AFTER_SECONDS:
        return "stale_profile"
    return "current"


def _calibration_for_parser(workspace_id: str, parser: str, as_of: float) -> tuple[Any, Any, str]:
    """Return (effective_profile, reported_profile, reason) for one parser in one workspace.

    Only an observed profile that is current at planning time can move ordering. Exactly one such profile
    applies; two with different source names are ambiguous and apply nothing. Other profiles are reported for
    transparency but never change ordering, so a neutral or stale profile cannot block a current one.
    """
    try:
        profiles = get_calibration_registry().profiles_for_parser(workspace_id, parser)
    except Exception as exc:
        _log.warning("calibration unavailable for recommendation planning: %s", type(exc).__name__)
        return None, None, "calibration_unavailable"
    observed = [profile for profile in profiles if profile.evidence_status == "observed"]
    current = [profile for profile in observed if _freshness(profile, as_of) == "current"]
    if len({profile.source_name for profile in current}) > 1:
        return None, None, "ambiguous_profile"
    if current:
        return current[0], current[0], "policy_observed"
    if observed:
        reason = _freshness(observed[0], as_of)
        return None, observed[0] if len(observed) == 1 else None, reason
    if not profiles:
        return None, None, "no_profile"
    reported = profiles[0] if len(profiles) == 1 else None
    return None, reported, f"not_observed:{reported.evidence_status}" if reported else "not_observed:multiple_sources"


def _ordering_effect(profile: Any, reason: str) -> float:
    """Calibration moves priority only for an observed profile, and never by more than the policy bound."""
    if profile is None or reason != "policy_observed":
        return 0.0
    return max(-MAX_ORDERING_EFFECT, min(MAX_ORDERING_EFFECT, float(profile.recommended_priority_adjustment)))


def build_import_recommendation_plan(gap_analysis: EvidenceGapAnalysis, max_recommendations: int = 8) -> ImportRecommendationPlan:
    groups: dict[str, list[Any]] = {}
    for gap in gap_analysis.gaps:
        for parser in gap.recommended_parser_types: groups.setdefault(parser, []).append(gap)
    recommendations: list[ImportRecommendation] = []
    effects: dict[str, list[Any]] = {}
    for parser, gaps in sorted(groups.items()):
        required, optional = _FIELDS.get(parser, _FIELDS["generic_market_csv"])
        priority = min(100.0, math.fsum(gap.priority_score for gap in gaps) / max(1, len(gaps)) + min(25.0, len(gaps) * 5.0))
        signals = sorted({gap.missing_signal_type for gap in gaps})
        calibration, reported, reason = _calibration_for_parser(gap_analysis.workspace_id, parser, gap_analysis.created_at)
        effects[parser] = [getattr(calibration, "profile_id", ""), reason, round(_ordering_effect(calibration, reason), 6)]
        adjustment = _ordering_effect(calibration, reason)
        adjusted_priority = max(0.0, min(100.0, priority + adjustment))
        if any(gap.severity in {"critical", "high"} for gap in gaps): adjusted_priority = max(adjusted_priority, CRITICAL_PRIORITY_FLOOR)
        metadata = {"real_market_claims": False, "calibration_profile_id": getattr(reported, "profile_id", ""), "calibration_policy_version": CALIBRATION_POLICY_VERSION, "calibration_reason": reason, "calibration_evidence_status": getattr(reported, "evidence_status", "none"), "usefulness_score": getattr(reported, "usefulness_score", None), "priority_adjustment": adjustment, "calibration_strengths": getattr(reported, "strengths", []), "calibration_weaknesses": getattr(reported, "weaknesses", [])}
        recommendations.append(ImportRecommendation("recommendation_" + uuid.uuid5(uuid.NAMESPACE_URL, f"{gap_analysis.workspace_id}:{parser}").hex[:16], gap_analysis.workspace_id, parser, parser.replace("_csv", ""), f"Import {parser.replace('_', ' ')} evidence", f"This local export can address: {', '.join(signals)}.", adjusted_priority, signals, required, optional, sorted({gap.gap_id for gap in gaps}), f"data/import_templates/{parser}.csv", created_at=gap_analysis.created_at, metadata=metadata))
    recommendations.sort(key=lambda item: (-item.priority_score, item.parser_type))
    recommendations = recommendations[:max(1, min(int(max_recommendations), 20))]
    # The calibration that was applied is part of the identity, so a plan rebuilt after calibration changes gets a new id.
    # Content-derived: the gaps, the limit, the applied calibration, and the resulting priorities all define the plan.
    plan_id = stable_id("import_plan_", [gap_analysis.workspace_id, sorted(gap.gap_id for gap in gap_analysis.gaps), max_recommendations, sorted(effects.items()), [(item.parser_type, round(item.priority_score, 6)) for item in recommendations]])
    return ImportRecommendationPlan(plan_id, gap_analysis.workspace_id, "Recommended Evidence Imports", recommendations, {"gap_count": len(gap_analysis.gaps), "parser_count": len(recommendations), "coverage_method": "gap_to_parser_mapping"}, created_at=gap_analysis.created_at, metadata={"no_live_access": True})
