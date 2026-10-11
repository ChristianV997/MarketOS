from __future__ import annotations

import json
import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .evidence_gap import EvidenceGapAnalysis
from .calibration_registry import get_calibration_registry
from .source_calibration import CALIBRATION_POLICY_VERSION, MAX_ORDERING_EFFECT

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


def _calibration_for_parser(workspace_id: str, parser: str) -> tuple[Any, str]:
    """The one workspace profile for this parser, or a reason it cannot be used.

    Profiles are keyed by the source name an operator chose, which is often the parser name itself, so the
    lookup is by parser within the workspace. Two sources for one parser cannot be told apart: no adjustment.
    """
    try:
        profiles = get_calibration_registry().profiles_for_parser(workspace_id, parser)
    except Exception:
        return None, "calibration_unavailable"
    if not profiles:
        return None, "no_profile"
    if len({profile.source_name for profile in profiles}) > 1:
        return None, "ambiguous_profile"
    profile = profiles[0]
    return profile, "policy_observed" if profile.evidence_status == "observed" else f"not_observed:{profile.evidence_status}"


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
    for parser, gaps in sorted(groups.items()):
        required, optional = _FIELDS.get(parser, _FIELDS["generic_market_csv"])
        priority = min(100.0, math.fsum(gap.priority_score for gap in gaps) / max(1, len(gaps)) + min(25.0, len(gaps) * 5.0))
        signals = sorted({gap.missing_signal_type for gap in gaps})
        calibration, reason = _calibration_for_parser(gap_analysis.workspace_id, parser)
        adjustment = _ordering_effect(calibration, reason)
        adjusted_priority = max(0.0, min(100.0, priority + adjustment))
        if any(gap.severity in {"critical", "high"} for gap in gaps): adjusted_priority = max(adjusted_priority, CRITICAL_PRIORITY_FLOOR)
        metadata = {"real_market_claims": False, "calibration_profile_id": getattr(calibration, "profile_id", ""), "calibration_policy_version": CALIBRATION_POLICY_VERSION, "calibration_reason": reason, "calibration_evidence_status": getattr(calibration, "evidence_status", "none"), "usefulness_score": getattr(calibration, "usefulness_score", None), "priority_adjustment": adjustment, "calibration_strengths": getattr(calibration, "strengths", []), "calibration_weaknesses": getattr(calibration, "weaknesses", [])}
        recommendations.append(ImportRecommendation("recommendation_" + uuid.uuid5(uuid.NAMESPACE_URL, f"{gap_analysis.workspace_id}:{parser}").hex[:16], gap_analysis.workspace_id, parser, parser.replace("_csv", ""), f"Import {parser.replace('_', ' ')} evidence", f"This local export can address: {', '.join(signals)}.", adjusted_priority, signals, required, optional, sorted({gap.gap_id for gap in gaps}), f"data/import_templates/{parser}.csv", created_at=gap_analysis.created_at, metadata=metadata))
    recommendations.sort(key=lambda item: (-item.priority_score, item.parser_type))
    recommendations = recommendations[:max(1, min(int(max_recommendations), 20))]
    plan_identity = uuid.uuid5(uuid.NAMESPACE_URL, json.dumps([gap_analysis.workspace_id, sorted(gap.gap_id for gap in gap_analysis.gaps), max_recommendations], separators=(",", ":"))).hex[:16]
    return ImportRecommendationPlan("import_plan_" + plan_identity, gap_analysis.workspace_id, "Recommended Evidence Imports", recommendations, {"gap_count": len(gap_analysis.gaps), "parser_count": len(recommendations), "coverage_method": "gap_to_parser_mapping"}, created_at=gap_analysis.created_at, metadata={"no_live_access": True})
