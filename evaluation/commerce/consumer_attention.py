"""Offline consumer-attention and creative-evidence intelligence.

This module turns sanitized trend, review, comment, and creative snapshots into
deterministic marketing hypotheses. It never posts content, launches ads, or
turns attention into supplier proof or launch authorization.
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

PROVENANCE = frozenset({"observed", "derived", "assumed", "unavailable", "malformed", "blocked", "manual_import", "fixture"})
EVIDENCE_MODES = PROVENANCE | frozenset({"fixture_demo", "manual_csv_import"})
UNTRUSTED_LIVE_MODES = frozenset({"live", "live_validated", "live_observed", "production", "verified"})
SOURCE_TYPES = frozenset(
    {
        "google_trends_manual_import", "google_trends_fixture", "tiktok_creative_center_snapshot", "tiktok_ad_snapshot",
        "meta_ad_library_snapshot", "youtube_search_snapshot", "youtube_comments_manual_import", "reddit_threads_manual_import",
        "reddit_comments_manual_import", "amazon_reviews_snapshot", "mercadolibre_reviews_snapshot", "ebay_reviews_snapshot",
        "shopify_reviews_snapshot", "minea_manual_import", "dropshipio_manual_import", "pipiads_manual_import",
        "kalodata_manual_import", "minee_manual_import", "manual_csv_import", "fixture_demo",
    }
)
PLATFORMS = frozenset({"google_trends", "tiktok", "meta", "youtube", "reddit", "amazon", "mercadolibre", "ebay", "shopify", "minea", "dropshipio", "pipiads", "kalodata", "manual"})
OFFERING_KINDS = frozenset({"goods", "service", "hybrid", "unknown"})
FRESHNESS_STATES = frozenset({"fresh", "stale", "future_dated", "unavailable"})
_LANGUAGE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$", re.I)


def number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
        return result if math.isfinite(result) else None
    text = str(value).strip().lower().replace(",", "")
    text = re.sub(r"^[\$€£]\s*", "", text)
    multiplier = 1000000 if text.endswith("m") else 1000 if text.endswith("k") else 1
    text = text.rstrip("km")
    if not _NUMBER.fullmatch(text):
        return None
    try:
        result = float(text) * multiplier
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def bounded(value: Any) -> float:
    return round(max(0.0, min(1.0, number(value) or 0.0)), 4)


# Keep the scoring module's private helper explicit.  Importers use the public
# ``bounded`` name, while score formulas read more naturally with ``_bounded``.
_bounded = bounded


def text(value: Any, limit: int = 240) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def normalize_observed_at(value: Any) -> str | None:
    """Return a canonical UTC timestamp, or None when it was not supplied."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    if not isinstance(value, str):
        raise ValueError("observed_at must be an ISO-8601 string")
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        raise ValueError("observed_at must be an ISO-8601 timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("observed_at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_evidence_mode(value: Any) -> str:
    mode = str(value or "unavailable").strip().lower()
    if mode in UNTRUSTED_LIVE_MODES or mode not in EVIDENCE_MODES:
        return "unavailable"
    return mode


def _reference_time(value: Any) -> datetime | None:
    normalized = normalize_observed_at(value)
    if normalized is None:
        return None
    return datetime.fromisoformat(normalized.replace("Z", "+00:00"))


def normalize_offering_kind(value: Any) -> str:
    kind = str(value or "unknown").strip().lower()
    if kind not in OFFERING_KINDS:
        raise ValueError("offering_kind must be goods, service, hybrid, or unknown")
    return kind


def normalize_geography(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or _CONTROL.search(value):
        raise ValueError("geography must be a safe text label")
    value = text(value, 80)
    return value or None


def normalize_language(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not _LANGUAGE.fullmatch(value.strip()):
        raise ValueError("language must be a BCP-47-like label")
    return value.strip()


def freshness_state(observed_at: Any, *, as_of: Any = None, max_age_days: int = 90) -> str:
    """Classify freshness without consulting the clock or inventing a timestamp."""
    if max_age_days < 1:
        raise ValueError("max_age_days must be positive")
    observed = _reference_time(observed_at)
    reference = _reference_time(as_of)
    if observed is None or reference is None:
        return "unavailable"
    if observed > reference:
        return "future_dated"
    age_seconds = (reference - observed).total_seconds()
    return "stale" if age_seconds > max_age_days * 86_400 else "fresh"


def normalize_sentiment(value: Any) -> str:
    label = str(value or "").lower().replace(" ", "_")
    if label in {"positive", "very_positive", "love", "satisfied"}:
        return "positive"
    if label in {"negative", "very_negative", "hate", "frustrated", "complaint"}:
        return "negative"
    if label in {"mixed", "neutral", "informational"}:
        return label
    return "unknown"


def normalize_intent(value: Any) -> str:
    label = str(value or "").lower().replace(" ", "_")
    if label in {"buy", "purchase", "commercial", "transactional", "high_intent"}:
        return "transactional"
    if label in {"compare", "commercial_research", "consideration"}:
        return "commercial_research"
    if label in {"learn", "informational", "research"}:
        return "informational"
    if label in {"problem", "support", "complaint"}:
        return "problem_aware"
    return "unknown"


@dataclass(frozen=True)
class CreativeHookEvidence:
    hook: str
    angle: str
    evidence_count: int
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VoiceOfCustomerEvidence:
    pain_points: tuple[str, ...] = ()
    desired_outcomes: tuple[str, ...] = ()
    objections: tuple[str, ...] = ()
    claims: tuple[str, ...] = ()
    proof_signals: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {key: list(value) for key, value in asdict(self).items()}


@dataclass(frozen=True)
class AdSignalEvidence:
    platform: str
    active: bool
    creative_format: str
    creator_style: str
    engagement_rate: float
    source_confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SearchTrendEvidence:
    keyword: str
    growth_signal: float
    keyword_intent: str
    trend_label: str
    source_confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReviewMiningEvidence:
    review_count: int
    rating: float | None
    sentiment_label: str
    pain_points: tuple[str, ...]
    objections: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["pain_points"] = list(self.pain_points)
        result["objections"] = list(self.objections)
        return result


@dataclass(frozen=True)
class ConsumerAttentionEvidence:
    candidate_id: str
    query: str
    source: str
    source_type: str
    source_url: str = ""
    evidence_mode: str = "fixture"
    platform: str = "manual"
    content_title: str = ""
    content_text_excerpt: str = ""
    hook: str = ""
    angle: str = ""
    pain_point: str = ""
    desired_outcome: str = ""
    objection: str = ""
    claim: str = ""
    proof_signal: str = ""
    format: str = ""
    engagement_count: int | None = None
    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    share_count: int | None = None
    save_count: int | None = None
    review_count: int | None = None
    rating: float | None = None
    sentiment_label: str = "unknown"
    intent_label: str = "unknown"
    trend_label: str = ""
    search_growth_signal: float | None = None
    keyword: str = ""
    keyword_intent: str = "unknown"
    ad_active_signal: bool = False
    ad_platform: str = ""
    creative_format: str = ""
    creator_style: str = ""
    ugc_scriptability: float | None = None
    visual_demo_score: float | None = None
    source_confidence: float = 0.0
    field_provenance: Mapping[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    observed_at: str | None = None
    read_only: bool = True
    network_calls: bool = False
    mutated: bool = False
    offering_kind: str = "unknown"
    geography: str | None = None
    language: str | None = None
    observation_key: str = ""
    observation_value: str | None = None

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.query or not self.source:
            raise ValueError("consumer attention identity fields are required")
        if any(_CONTROL.search(value) for value in (self.candidate_id, self.query, self.source)):
            raise ValueError("consumer attention identity fields must be safe text")
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"unsupported source_type: {self.source_type}")
        if self.platform not in PLATFORMS:
            raise ValueError(f"unsupported platform: {self.platform}")
        object.__setattr__(self, "evidence_mode", normalize_evidence_mode(self.evidence_mode))
        object.__setattr__(self, "observed_at", normalize_observed_at(self.observed_at))
        object.__setattr__(self, "offering_kind", normalize_offering_kind(self.offering_kind))
        object.__setattr__(self, "geography", normalize_geography(self.geography))
        object.__setattr__(self, "language", normalize_language(self.language))
        if not isinstance(self.observation_key, str) or _CONTROL.search(self.observation_key):
            raise ValueError("observation_key must be safe text")
        if self.observation_value is not None:
            if _CONTROL.search(str(self.observation_value)):
                raise ValueError("observation_value must be safe text")
            object.__setattr__(self, "observation_value", text(self.observation_value, 120))
        if set(self.field_provenance.values()) - PROVENANCE:
            raise ValueError("invalid consumer-attention provenance")
        if not self.read_only or self.network_calls or self.mutated:
            raise ValueError("consumer attention evidence must be offline and read-only")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["field_provenance"] = dict(self.field_provenance)
        result["warnings"] = list(self.warnings)
        return result


@dataclass(frozen=True)
class ConsumerAttentionScore:
    candidate_id: str
    search_demand_signal: float
    trend_growth_signal: float
    social_engagement_signal: float
    ad_activity_signal: float
    review_density_signal: float
    voice_of_customer_quality: float
    pain_point_clarity: float
    objection_density: float
    creative_hook_diversity: float
    ugc_scriptability: float
    visual_demo_potential: float
    intent_strength: float
    source_diversity: float
    attention_saturation_risk: float
    overall_consumer_attention: float
    recommendation: str
    contributions: Mapping[str, float]
    reasons: tuple[str, ...] = ()
    creative_hooks: tuple[CreativeHookEvidence, ...] = ()
    voice_of_customer: VoiceOfCustomerEvidence = VoiceOfCustomerEvidence()
    ad_signals: tuple[AdSignalEvidence, ...] = ()
    search_signals: tuple[SearchTrendEvidence, ...] = ()
    review_signals: tuple[ReviewMiningEvidence, ...] = ()
    recommended_ad_angles: tuple[str, ...] = ()
    recommended_ugc_formats: tuple[str, ...] = ()
    landing_page_copy_hints: tuple[str, ...] = ()
    creative_risks: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["contributions"] = dict(self.contributions)
        for key in ("reasons", "recommended_ad_angles", "recommended_ugc_formats", "landing_page_copy_hints", "creative_risks"):
            result[key] = list(result[key])
        result["creative_hooks"] = [item.to_dict() for item in self.creative_hooks]
        result["ad_signals"] = [item.to_dict() for item in self.ad_signals]
        result["search_signals"] = [item.to_dict() for item in self.search_signals]
        result["review_signals"] = [item.to_dict() for item in self.review_signals]
        result["voice_of_customer"] = self.voice_of_customer.to_dict()
        return result


@dataclass(frozen=True)
class ConsumerAttentionCandidateResult:
    candidate_id: str
    query: str
    evidence: tuple[ConsumerAttentionEvidence, ...]
    score: ConsumerAttentionScore
    warnings: tuple[str, ...] = ()
    offering_kinds: tuple[str, ...] = ()
    geographies: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    freshness_statuses: tuple[str, ...] = ()
    conflicting_observation_keys: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "query": self.query,
            "evidence": [item.to_dict() for item in self.evidence],
            "score": self.score.to_dict(),
            "platforms": sorted({item.platform for item in self.evidence}),
            "source_types": sorted({item.source_type for item in self.evidence}),
            "offering_kinds": list(self.offering_kinds),
            "geographies": list(self.geographies),
            "languages": list(self.languages),
            "freshness_statuses": list(self.freshness_statuses),
            "conflicting_observation_keys": list(self.conflicting_observation_keys),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ConsumerAttentionReport:
    report_version: str
    evidence_mode: str
    candidate_count: int
    evidence_count: int
    platforms_observed: tuple[str, ...]
    top_candidate_id: str | None
    next_best_action: str
    candidates: tuple[ConsumerAttentionCandidateResult, ...]
    warnings: tuple[str, ...] = ()
    read_only: bool = True
    network_calls: bool = False
    mutated: bool = False
    freshness_status: str = "unavailable"
    offering_kinds: tuple[str, ...] = ()
    geographies: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    conflict_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": self.report_version,
            "evidence_mode": self.evidence_mode,
            "candidate_count": self.candidate_count,
            "evidence_count": self.evidence_count,
            "platforms_observed": list(self.platforms_observed),
            "offering_kinds": list(self.offering_kinds),
            "geographies": list(self.geographies),
            "languages": list(self.languages),
            "freshness_status": self.freshness_status,
            "conflict_count": self.conflict_count,
            "top_candidate_id": self.top_candidate_id,
            "next_best_action": self.next_best_action,
            "candidates": [item.to_dict() for item in self.candidates],
            "warnings": list(self.warnings),
            "read_only": self.read_only,
            "network_calls": self.network_calls,
            "mutated": self.mutated,
        }


ANGLE_RULES = (
    ("problem_solution", ("problem", "frustrat", "struggle", "messy")),
    ("before_after", ("before", "after", "transform")),
    ("giftable", ("gift", "present")),
    ("demo", ("demo", "show", "how it works", "unbox")),
    ("comparison", ("versus", "compare", "alternative")),
    ("convenience", ("easy", "simple", "convenient")),
    ("cost_saving", ("save", "affordable", "cost")),
    ("time_saving", ("quick", "fast", "time")),
    ("aesthetic", ("beautiful", "minimal", "design")),
    ("health_wellness", ("health", "wellness", "relief")),
    ("productivity", ("organize", "work", "productive")),
    ("family_pet_home", ("family", "pet", "home")),
    ("travel_portability", ("travel", "portable", "carry")),
)


def _average(values: Iterable[float]) -> float:
    values = list(values)
    return round(sum(values) / len(values), 4) if values else 0.0


def _phrases(records: Iterable[ConsumerAttentionEvidence], field_name: str) -> tuple[str, ...]:
    values = []
    for record in records:
        value = str(getattr(record, field_name, "") or "").strip()
        if value and value.lower() not in {item.lower() for item in values}:
            values.append(value)
    return tuple(values[:5])


def extract_creative_angles(records: list[ConsumerAttentionEvidence]) -> dict[str, Any]:
    hooks = _phrases(records, "hook")
    text_blob = " ".join(" ".join((record.hook, record.angle, record.pain_point, record.desired_outcome, record.claim, record.content_text_excerpt)) for record in records).lower()
    angle_names = [name for name, keywords in ANGLE_RULES if any(keyword in text_blob for keyword in keywords)]
    if not angle_names and records:
        angle_names = ["problem_solution"]
    formats = sorted({record.creative_format or record.format for record in records if record.creative_format or record.format})
    ugc = ["talking_head_demo", "hands_only_demo"] if any(record.ugc_scriptability and record.ugc_scriptability >= 0.6 for record in records) else ["testimonial_voiceover"] if records else []
    return {"top_hooks": list(hooks), "recommended_ad_angles": angle_names[:6], "recommended_ugc_formats": formats[:5] or ugc[:3], "landing_page_copy_hints": [f"Lead with: {item}" for item in _phrases(records, "desired_outcome")[:3]], "creative_risks": ["objection_evidence_present"] if any(record.objection for record in records) else []}


def _voc(records: list[ConsumerAttentionEvidence]) -> VoiceOfCustomerEvidence:
    return VoiceOfCustomerEvidence(_phrases(records, "pain_point"), _phrases(records, "desired_outcome"), _phrases(records, "objection"), _phrases(records, "claim"), _phrases(records, "proof_signal"))


def _conflicting_observation_keys(records: Iterable[ConsumerAttentionEvidence]) -> tuple[str, ...]:
    values: dict[str, set[str]] = {}
    for record in records:
        if record.observation_key and record.observation_value not in (None, ""):
            values.setdefault(record.observation_key, set()).add(record.observation_value)
    return tuple(sorted(key for key, observed_values in values.items() if len(observed_values) > 1))


def _report_freshness(records: Iterable[ConsumerAttentionEvidence], *, as_of: Any, max_age_days: int) -> tuple[str, ...]:
    return tuple(freshness_state(record.observed_at, as_of=as_of, max_age_days=max_age_days) for record in records)


def score_candidate(
    candidate_id: str,
    evidence: list[ConsumerAttentionEvidence],
    *,
    supplier_proof: bool = False,
    quality_blockers: Iterable[str] = (),
) -> ConsumerAttentionScore:
    if not evidence:
        return ConsumerAttentionScore(candidate_id, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, "reject_low_attention", {}, ("no_consumer_attention_evidence",), voice_of_customer=VoiceOfCustomerEvidence())
    growth = _average(bounded(item.search_growth_signal) for item in evidence if item.search_growth_signal is not None)
    search = _average([bounded(item.search_growth_signal) for item in evidence if item.keyword or item.search_growth_signal is not None])
    engagement = _average(min(1.0, ((item.engagement_count or (item.like_count or 0) + (item.comment_count or 0) + (item.share_count or 0)) / max(1, item.view_count or 10000)) * 10) for item in evidence)
    ad = _average(1.0 if item.ad_active_signal else 0.0 for item in evidence)
    reviews = _average(min(1.0, (item.review_count or 0) / 1000) for item in evidence if item.review_count is not None)
    voc = _average(min(1.0, ((item.review_count or 0) + (item.comment_count or 0)) / 500) for item in evidence)
    pains = _average(1.0 if item.pain_point else 0.0 for item in evidence)
    objections = _average(1.0 if item.objection else 0.0 for item in evidence)
    hooks = _bounded(len({item.hook.lower() for item in evidence if item.hook}) / 4)
    ugc = _average(bounded(item.ugc_scriptability) for item in evidence if item.ugc_scriptability is not None)
    visual = _average(bounded(item.visual_demo_score) for item in evidence if item.visual_demo_score is not None)
    intent = _average({"transactional": 1.0, "commercial_research": 0.75, "problem_aware": 0.65, "informational": 0.35, "unknown": 0.2}.get(item.intent_label, 0.2) for item in evidence)
    diversity = bounded(len({item.platform for item in evidence}) / 4)
    saturation = bounded((len([item for item in evidence if item.ad_active_signal]) / max(1, len(evidence))) * 0.7 + (1 - hooks) * 0.3)
    confidence = _average(item.source_confidence for item in evidence)
    base = _average([search, growth, engagement, ad, reviews, voc, pains, hooks, ugc, visual, intent, diversity])
    overall = round(bounded(base * (1 - saturation * 0.35) * (0.65 + confidence * 0.35)), 4)
    creative = extract_creative_angles(evidence)
    voc_result = _voc(evidence)
    quality_blockers = tuple(dict.fromkeys(str(item) for item in quality_blockers if item))
    reasons = ["consumer_attention_is_not_supplier_proof", *quality_blockers]
    if not supplier_proof:
        reasons.append("supplier_proof_not_observed")
    if quality_blockers:
        # Reuse the existing conservative rejection path so downstream
        # synthesis cannot treat an attractive but contradictory signal as a
        # promotion input. The reason identifies the actual blocker.
        recommendation = "reject_low_attention"
    elif objections >= 0.6:
        recommendation = "reject_high_objection_risk"
    elif overall < 0.25:
        recommendation = "reject_low_attention"
    elif not supplier_proof and overall >= 0.45:
        recommendation = "validate_supplier_first"
    elif overall >= 0.7:
        # Attention is an input to downstream decisions, never launch authority.
        recommendation = "manual_review_required"
    elif hooks >= 0.5:
        recommendation = "generate_creative_tests"
    else:
        recommendation = "expand_consumer_research"
    contributions = {"search_demand_signal": search, "trend_growth_signal": growth, "social_engagement_signal": engagement, "ad_activity_signal": ad, "review_density_signal": reviews, "voice_of_customer_quality": voc, "pain_point_clarity": pains, "objection_density": objections, "creative_hook_diversity": hooks, "ugc_scriptability": ugc, "visual_demo_potential": visual, "intent_strength": intent, "source_diversity": diversity, "attention_saturation_risk": saturation}
    ads = tuple(AdSignalEvidence(item.ad_platform or item.platform, item.ad_active_signal, item.creative_format or item.format, item.creator_style, bounded(((item.engagement_count or 0) / max(1, item.view_count or 10000)) * 10), item.source_confidence) for item in evidence if item.ad_active_signal or item.ad_platform)
    searches = tuple(SearchTrendEvidence(item.keyword or item.query, bounded(item.search_growth_signal), item.keyword_intent, item.trend_label, item.source_confidence) for item in evidence if item.keyword or item.search_growth_signal is not None)
    reviews_mined = tuple(ReviewMiningEvidence(item.review_count or 0, item.rating, item.sentiment_label, (item.pain_point,) if item.pain_point else (), (item.objection,) if item.objection else ()) for item in evidence if item.review_count or item.pain_point or item.objection)
    hook_items = tuple(CreativeHookEvidence(hook, next((name for name, keywords in ANGLE_RULES if any(keyword in hook.lower() for keyword in keywords)), "problem_solution"), sum(1 for item in evidence if item.hook == hook), confidence) for hook in creative["top_hooks"])
    return ConsumerAttentionScore(candidate_id, search, growth, engagement, ad, reviews, voc, pains, objections, hooks, ugc, visual, intent, diversity, saturation, overall, recommendation, {key: round(value, 4) for key, value in contributions.items()}, tuple(reasons), hook_items, voc_result, ads, searches, reviews_mined, tuple(creative["recommended_ad_angles"]), tuple(creative["recommended_ugc_formats"]), tuple(creative["landing_page_copy_hints"]), tuple(creative["creative_risks"]))


def collapse_duplicates(records: Iterable[ConsumerAttentionEvidence]) -> list[ConsumerAttentionEvidence]:
    selected: dict[tuple[str, str, str, str, str | None], ConsumerAttentionEvidence] = {}
    for record in records:
        # Keep contradictory observations separate so a stronger-looking
        # duplicate cannot erase dissent before conflict analysis runs.
        key = (record.candidate_id, record.source, record.content_title or record.hook, record.observation_key, record.observation_value)
        old = selected.get(key)
        if old is None or (record.source_confidence, record.engagement_count or 0, record.review_count or 0) > (old.source_confidence, old.engagement_count or 0, old.review_count or 0):
            selected[key] = record
    return sorted(selected.values(), key=lambda item: (item.candidate_id, item.platform, item.source, item.content_title))


def build_report(
    records: list[ConsumerAttentionEvidence],
    *,
    evidence_mode: str = "fixture",
    supplier_proof_by_candidate: Mapping[str, bool] | None = None,
    as_of: str | datetime | None = None,
    max_age_days: int = 90,
) -> ConsumerAttentionReport:
    if max_age_days < 1:
        raise ValueError("max_age_days must be positive")
    reference = _reference_time(as_of) if as_of is not None else None
    records = collapse_duplicates(records)
    grouped: dict[str, list[ConsumerAttentionEvidence]] = {}
    for record in records:
        if record.candidate_id:
            grouped.setdefault(record.candidate_id, []).append(record)
    proofs = supplier_proof_by_candidate or {}
    candidate_results: list[ConsumerAttentionCandidateResult] = []
    for candidate_id, rows in sorted(grouped.items()):
        conflicts = _conflicting_observation_keys(rows)
        freshness = _report_freshness(rows, as_of=reference, max_age_days=max_age_days)
        freshness_blockers = ()
        if as_of is not None:
            freshness_blockers = tuple(
                f"consumer_observation_{state}"
                for state in sorted(set(freshness) - {"fresh"})
            )
        warnings = {warning for row in rows for warning in row.warnings}
        if conflicts:
            warnings.add("conflicting_consumer_observations")
        if as_of is not None:
            if any(state == "future_dated" for state in freshness):
                warnings.add("future_dated_consumer_observation")
            if any(state == "stale" for state in freshness):
                warnings.add("stale_consumer_observation")
            if any(state == "unavailable" for state in freshness):
                warnings.add("consumer_observation_freshness_unavailable")
        score = score_candidate(
            candidate_id,
            rows,
            supplier_proof=proofs.get(candidate_id, False),
            quality_blockers=("conflicting_consumer_observations",) * bool(conflicts) + freshness_blockers,
        )
        candidate_results.append(
            ConsumerAttentionCandidateResult(
                candidate_id,
                rows[0].query,
                tuple(rows),
                score,
                tuple(sorted(warnings)),
                tuple(sorted({row.offering_kind for row in rows})),
                tuple(sorted({row.geography for row in rows if row.geography})),
                tuple(sorted({row.language for row in rows if row.language})),
                tuple(sorted(set(freshness))),
                conflicts,
            )
        )
    results = tuple(candidate_results)
    results = tuple(sorted(results, key=lambda item: (-item.score.overall_consumer_attention, item.candidate_id)))
    top = results[0] if results else None
    states = {state for item in results for state in item.freshness_statuses}
    if "future_dated" in states:
        report_freshness = "future_dated"
    elif "stale" in states:
        report_freshness = "stale"
    elif states == {"fresh"}:
        report_freshness = "fresh"
    else:
        report_freshness = "unavailable"
    warnings = ["consumer_attention_is_not_supplier_proof"] if records else ["consumer_attention_not_supplied"]
    conflict_count = sum(len(item.conflicting_observation_keys) for item in results)
    if conflict_count:
        warnings.append("conflicting_consumer_observations")
    if as_of is not None and report_freshness != "fresh":
        warnings.append("consumer_attention_freshness_incomplete")
    next_action = f"{top.score.recommendation}:{top.candidate_id}" if top else "expand_consumer_research"
    if conflict_count:
        next_action = "resolve_consumer_attention_conflicts"
    elif as_of is not None and report_freshness != "fresh":
        next_action = "refresh_consumer_attention_evidence"
    return ConsumerAttentionReport(
        "consumer-attention-v1",
        normalize_evidence_mode(evidence_mode),
        len(results),
        len(records),
        tuple(sorted({item.platform for item in records})),
        top.candidate_id if top else None,
        next_action,
        results,
        tuple(dict.fromkeys(warnings)),
        True,
        False,
        False,
        report_freshness,
        tuple(sorted({item.offering_kind for item in records})),
        tuple(sorted({item.geography for item in records if item.geography})),
        tuple(sorted({item.language for item in records if item.language})),
        conflict_count,
    )
