"""Offline bridge from Google Trends relative-interest evidence to consumer attention.

The official adapter (#480) emits consistently scaled relative search interest.
``ConsumerAttentionEvidence.search_growth_signal`` is not that metric: the
canonical report builder bounds it to 0–1 and averages it as growth. A time
series also needs period, resolution, and metric kind, which the canonical row
cannot store together without loss.

This module therefore:

- preserves each point as source-specific evidence
- emits trace rows into the existing ``build_report`` path
- leaves ``keyword`` and ``search_growth_signal`` unset so the series is not scored
- never treats fixture, manual, or blocked-live output as live proof

It does not collect data, resolve product identity, or change shared scorers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from evaluation.commerce.consumer_attention import (
    ConsumerAttentionEvidence,
    ConsumerAttentionReport,
    build_report,
    normalize_observed_at,
)
from evaluation.commerce.google_trends_interest_adapter import (
    PROVIDER_ID,
    GoogleTrendsInterestAdapterError,
    GoogleTrendsInterestObservation,
    GoogleTrendsInterestReport,
    build_google_trends_interest_report,
    normalize_interest_observation,
)

COMPOSITION_VERSION = "google-trends-attention-composition-v1"
UNBOUND_CANDIDATE_ID = "unbound-search-interest"
METRIC_KIND = "relative_search_interest"
SCORING_BLOCK_REASON = (
    "Canonical consumer-attention scoring cannot represent a consistently scaled "
    "relative-interest time series without writing it into search_growth_signal, "
    "which is bounded and averaged as a 0-1 growth score. The series is preserved "
    "as source-specific evidence and is unavailable for scoring."
)

_HINT_KEYS = frozenset({"candidate_id_hint", "hint"})


@dataclass(frozen=True)
class PreservedSearchInterestPoint:
    term: str
    geography: str | None
    language_metadata: str | None
    language_filter_confirmed: bool
    time_resolution: str
    observation_period_start: str
    observation_period_end: str
    relative_interest: float | None
    metric_kind: str
    status: str
    freshness_state: str
    provenance: str
    method: str
    collected_at: str | None
    source_provider: str
    source_method: str
    available_for_scoring: bool = False
    absolute_search_volume: None = None
    purchase_intent: None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "term": self.term,
            "geography": self.geography,
            "language_metadata": self.language_metadata,
            "language_filter_confirmed": False,
            "time_resolution": self.time_resolution,
            "observation_period_start": self.observation_period_start,
            "observation_period_end": self.observation_period_end,
            "relative_interest": self.relative_interest,
            "metric_kind": METRIC_KIND,
            "status": self.status,
            "freshness_state": self.freshness_state,
            "provenance": self.provenance,
            "method": self.method,
            "collected_at": self.collected_at,
            "source_provider": self.source_provider,
            "source_method": self.source_method,
            "available_for_scoring": False,
            "absolute_search_volume": None,
            "purchase_intent": None,
        }


@dataclass(frozen=True)
class GoogleTrendsAttentionComposition:
    composition_version: str
    provider_id: str
    metric_kind: str
    evidence_mode: str
    result_status: str
    available_for_scoring: bool
    scoring_block_reason: str
    score_represents_relative_interest: bool
    source_series: tuple[PreservedSearchInterestPoint, ...]
    canonical_evidence: tuple[ConsumerAttentionEvidence, ...]
    attention_report: ConsumerAttentionReport
    warnings: tuple[str, ...]
    identity_links_applied: tuple[str, ...]
    request_geography: str | None
    request_language_metadata: str | None
    request_time_resolution: str | None
    request_window_start: str | None
    request_window_end: str | None
    live_mode_blocked: bool
    read_only: bool = True
    network_calls: bool = False
    live_request_created: bool = False
    mutated: bool = False
    purchase_intent: None = None
    absolute_search_volume: None = None
    supplier_proof: bool = False
    launch_authority: bool = False
    sales_or_demand_proof: bool = False
    currency: None = None
    economics_assumed: bool = False

    def __post_init__(self) -> None:
        if self.available_for_scoring or self.score_represents_relative_interest:
            raise ValueError("relative search interest is unavailable for scoring")
        if self.network_calls or self.live_request_created or self.mutated or not self.read_only:
            raise ValueError("trends attention composition must stay offline")
        if self.purchase_intent is not None or self.absolute_search_volume is not None:
            raise ValueError("volume and purchase intent are unavailable")
        if self.supplier_proof or self.launch_authority or self.sales_or_demand_proof or self.economics_assumed:
            raise ValueError("trends attention composition has no commerce authority")
        if self.currency is not None:
            raise ValueError("no currency is assumed")
        if self.evidence_mode in {"live", "live_validated", "live_observed", "production", "verified"}:
            raise ValueError("fixture evidence must not be labeled live")

    def to_dict(self) -> dict[str, Any]:
        return {
            "composition_version": self.composition_version,
            "provider_id": self.provider_id,
            "metric_kind": METRIC_KIND,
            "evidence_mode": self.evidence_mode,
            "result_status": self.result_status,
            "available_for_scoring": False,
            "scoring_block_reason": self.scoring_block_reason,
            "score_represents_relative_interest": False,
            "source_series": [item.to_dict() for item in self.source_series],
            "canonical_evidence": [item.to_dict() for item in self.canonical_evidence],
            "attention_report": self.attention_report.to_dict(),
            "warnings": list(self.warnings),
            "identity_links_applied": list(self.identity_links_applied),
            "request_geography": self.request_geography,
            "request_language_metadata": self.request_language_metadata,
            "request_time_resolution": self.request_time_resolution,
            "request_window_start": self.request_window_start,
            "request_window_end": self.request_window_end,
            "live_mode_blocked": self.live_mode_blocked,
            "read_only": True,
            "network_calls": False,
            "live_request_created": False,
            "mutated": False,
            "purchase_intent": None,
            "absolute_search_volume": None,
            "supplier_proof": False,
            "launch_authority": False,
            "sales_or_demand_proof": False,
            "currency": None,
            "economics_assumed": False,
        }


def _warnings(*items: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for item in items if item))


def _interest_token(value: float | None) -> str:
    if value is None:
        return "unavailable"
    return format(value, ".12g")


def _bucket_key(observation: GoogleTrendsInterestObservation, geography: str | None) -> str:
    geo = geography or "geography-unavailable"
    return "|".join(
        (
            observation.term,
            geo,
            observation.time_resolution,
            observation.observation_period_start,
            observation.observation_period_end,
        )
    )


def _accept_links(links: Mapping[str, str] | None) -> tuple[dict[str, str], tuple[str, ...]]:
    if not links:
        return {}, ()
    accepted: dict[str, str] = {}
    notes: list[str] = []
    for raw_key, raw_value in links.items():
        key = str(raw_key).strip()
        value = str(raw_value).strip()
        folded = key.casefold()
        if folded in _HINT_KEYS or folded.endswith("_hint"):
            notes.append("candidate_id_hint_ignored")
            continue
        if not key or not value:
            notes.append("identity_link_ignored_blank")
            continue
        if value.casefold() == key.casefold():
            notes.append("identity_link_rejected_term_is_not_a_candidate")
            continue
        if key in accepted and accepted[key] != value:
            notes.append("identity_link_conflict_ignored")
            continue
        accepted[key] = value
    return accepted, _warnings(*notes)


def _plan_is_not_evidence(source: Mapping[str, Any]) -> bool:
    if source.get("fixture_mode") is True or source.get("observations") or source.get("series"):
        return False
    return bool(source.get("is_plan") is True or source.get("role") == "plan" or source.get("is_evidence") is False)


def _explicit_flags(payload: Mapping[str, Any]) -> list[dict[str, bool]] | None:
    series = payload.get("series", ())
    if not isinstance(series, Sequence) or isinstance(series, (str, bytes)):
        return None
    geography = str(payload.get("geography") or "US")
    language = str(payload.get("language") or "en")
    resolution = str(payload.get("time_resolution") or "WEEK")
    flags: list[dict[str, bool]] = []
    for entry in series:
        if not isinstance(entry, Mapping):
            continue
        points = entry.get("points", ())
        if not isinstance(points, Sequence) or isinstance(points, (str, bytes)):
            continue
        for point in points:
            if not isinstance(point, Mapping):
                continue
            merged = {
                "term": entry.get("term") or entry.get("keyword"),
                "geography": entry.get("geography") or geography,
                "language": entry.get("language") or language,
                "time_resolution": entry.get("time_resolution") or resolution,
                **point,
            }
            try:
                normalize_interest_observation(
                    merged,
                    default_geography=geography,
                    default_language=language,
                    default_resolution=resolution,
                )
            except GoogleTrendsInterestAdapterError:
                continue
            flags.append(
                {
                    "geography_explicit": bool(str(point.get("geography") or entry.get("geography") or "").strip()),
                    "language_explicit": bool(str(point.get("language") or entry.get("language") or "").strip()),
                }
            )
    return flags


def _observed_at(collected_at: str | None) -> tuple[str | None, str]:
    if not collected_at:
        return None, ""
    try:
        return normalize_observed_at(collected_at), ""
    except ValueError:
        return None, "collected_at_not_usable_as_observed_at"


def _trace_row(
    observation: GoogleTrendsInterestObservation,
    *,
    candidate_id: str,
    geography: str | None,
    bound: bool,
    extra_warnings: tuple[str, ...],
) -> ConsumerAttentionEvidence:
    provenance = observation.provenance
    if provenance == "manual_import":
        evidence_mode = "manual_import"
        source_type = "google_trends_manual_import"
        field_mode = "manual_import"
    else:
        evidence_mode = "fixture"
        source_type = "google_trends_fixture"
        field_mode = "fixture"
    observed_at, time_warning = _observed_at(observation.collected_at)
    bucket = _bucket_key(observation, geography)
    row_warnings = [
        "relative_search_interest_not_a_growth_signal",
        "relative_search_interest_unavailable_for_scoring",
        "language_filter_unconfirmed",
        "not_absolute_volume_sales_or_purchase_intent",
        *extra_warnings,
    ]
    if not bound:
        row_warnings.append("no_explicit_identity_link")
    if observation.relative_interest is None:
        row_warnings.append("relative_interest_missing")
    if observation.status == "stale" or observation.freshness_state == "stale":
        row_warnings.append("stale_relative_interest")
    if provenance == "observed":
        row_warnings.append("provenance_observed_not_upgraded_to_live")
    if time_warning:
        row_warnings.append(time_warning)
    return ConsumerAttentionEvidence(
        candidate_id=candidate_id,
        query=observation.term,
        source=PROVIDER_ID,
        source_type=source_type,
        evidence_mode=evidence_mode,
        platform="google_trends",
        content_title=bucket,
        trend_label="",
        search_growth_signal=None,
        keyword="",
        keyword_intent="unknown",
        intent_label="unknown",
        source_confidence=0.0,
        field_provenance={
            "query": field_mode,
            "geography": field_mode if geography else "unavailable",
            "language": "unavailable",
            "search_growth_signal": "unavailable",
            "keyword": "unavailable",
        },
        warnings=_warnings(*row_warnings),
        observed_at=observed_at,
        geography=geography,
        language=None,
        observation_key=f"relative_search_interest:{bucket}",
        observation_value=_interest_token(observation.relative_interest),
    )


def _empty_composition(
    *,
    status: str,
    evidence_mode: str,
    warnings: tuple[str, ...],
    live_mode_blocked: bool = True,
) -> GoogleTrendsAttentionComposition:
    report = build_report([], evidence_mode=evidence_mode if evidence_mode in {"fixture", "manual_import", "unavailable"} else "unavailable")
    return GoogleTrendsAttentionComposition(
        composition_version=COMPOSITION_VERSION,
        provider_id=PROVIDER_ID,
        metric_kind=METRIC_KIND,
        evidence_mode="unavailable" if evidence_mode == "unavailable" else evidence_mode,
        result_status=status,
        available_for_scoring=False,
        scoring_block_reason=SCORING_BLOCK_REASON,
        score_represents_relative_interest=False,
        source_series=(),
        canonical_evidence=(),
        attention_report=report,
        warnings=_warnings(*warnings, "canonical_attention_score_does_not_encode_relative_interest"),
        identity_links_applied=(),
        request_geography=None,
        request_language_metadata=None,
        request_time_resolution=None,
        request_window_start=None,
        request_window_end=None,
        live_mode_blocked=live_mode_blocked,
    )


def _from_report(
    report: GoogleTrendsInterestReport,
    *,
    identity_links: Mapping[str, str] | None,
    as_of: str | None,
    explicit_flags: list[dict[str, bool]] | None,
    extra_warnings: tuple[str, ...] = (),
) -> GoogleTrendsAttentionComposition:
    links, link_notes = _accept_links(identity_links)
    plan = report.request_plan
    flags = explicit_flags
    aligned = flags is not None and len(flags) == len(report.observations)
    notes = list(extra_warnings)
    notes.extend(link_notes)
    if report.result_status == "blocked_live_mode" or plan.status == "blocked_live_mode":
        notes.append("live_mode_blocked_not_upgraded")
    if flags is not None and not aligned:
        notes.append("explicitness_alignment_failed")
    if flags is None:
        notes.append("fixture_point_explicitness_unavailable")
    points: list[PreservedSearchInterestPoint] = []
    rows: list[ConsumerAttentionEvidence] = []
    seen_buckets: dict[str, str] = {}
    for index, observation in enumerate(report.observations):
        flag = flags[index] if aligned and flags is not None else None
        if flag is None:
            geography = observation.geography or None
            language_metadata = observation.language or None
        else:
            geography = observation.geography if flag["geography_explicit"] and observation.geography else None
            language_metadata = observation.language if flag["language_explicit"] and observation.language else None
        row_notes: list[str] = []
        if flag is not None and not flag["geography_explicit"]:
            row_notes.append("geography_not_explicit_left_unavailable")
        if geography and plan.geography and geography != plan.geography:
            row_notes.append("geography_mismatch_preserved")
        if flag is not None and not flag["language_explicit"]:
            row_notes.append("language_not_explicit_left_unavailable")
        bucket = _bucket_key(observation, geography)
        token = _interest_token(observation.relative_interest)
        previous = seen_buckets.get(bucket)
        if previous is None:
            seen_buckets[bucket] = token
        elif previous == token:
            row_notes.append("duplicate_reference")
        else:
            row_notes.append("conflicting_relative_interest")
        if observation.provenance == "observed":
            row_notes.append("provenance_observed_not_upgraded_to_live")
        points.append(
            PreservedSearchInterestPoint(
                term=observation.term,
                geography=geography,
                language_metadata=language_metadata,
                language_filter_confirmed=False,
                time_resolution=observation.time_resolution,
                observation_period_start=observation.observation_period_start,
                observation_period_end=observation.observation_period_end,
                relative_interest=observation.relative_interest,
                metric_kind=METRIC_KIND,
                status=observation.status,
                freshness_state=observation.freshness_state,
                provenance="fixture" if observation.provenance == "observed" else observation.provenance,
                method=observation.method,
                collected_at=observation.collected_at,
                source_provider=observation.source_provider,
                source_method=observation.source_method,
            )
        )
        candidate_id = links.get(observation.term, UNBOUND_CANDIDATE_ID)
        rows.append(
            _trace_row(
                observation,
                candidate_id=candidate_id,
                geography=geography,
                bound=observation.term in links,
                extra_warnings=tuple(row_notes),
            )
        )
    modes = {row.evidence_mode for row in rows}
    if not rows:
        evidence_mode = "unavailable" if report.result_status in {"malformed", "rejected"} else "fixture"
    elif modes == {"manual_import"}:
        evidence_mode = "manual_import"
    elif "fixture" in modes and "manual_import" in modes:
        evidence_mode = "fixture"
        notes.append("mixed_evidence_modes_not_upgraded")
    else:
        evidence_mode = "fixture"
    applied = tuple(sorted({observation.term for observation in report.observations if observation.term in links}))
    attention = build_report(list(rows), evidence_mode=evidence_mode, as_of=as_of)
    return GoogleTrendsAttentionComposition(
        composition_version=COMPOSITION_VERSION,
        provider_id=PROVIDER_ID,
        metric_kind=METRIC_KIND,
        evidence_mode=evidence_mode,
        result_status=report.result_status,
        available_for_scoring=False,
        scoring_block_reason=SCORING_BLOCK_REASON,
        score_represents_relative_interest=False,
        source_series=tuple(points),
        canonical_evidence=tuple(rows),
        attention_report=attention,
        warnings=_warnings(*notes, "canonical_attention_score_does_not_encode_relative_interest"),
        identity_links_applied=applied,
        request_geography=plan.geography or None,
        request_language_metadata=plan.language or None,
        request_time_resolution=plan.time_resolution or None,
        request_window_start=plan.window_start or None,
        request_window_end=plan.window_end or None,
        live_mode_blocked=True,
    )


def compose_google_trends_attention(
    source: GoogleTrendsInterestReport | Mapping[str, Any] | None,
    *,
    identity_links: Mapping[str, str] | None = None,
    as_of: str | None = None,
    live_read_only: bool = False,
) -> GoogleTrendsAttentionComposition:
    """Map adapter output into traceable attention evidence without scoring it."""
    hint_notes: tuple[str, ...] = ()
    if isinstance(source, Mapping) and "candidate_id_hint" in source:
        hint_notes = ("candidate_id_hint_ignored",)
    if source is None:
        return _empty_composition(status="malformed", evidence_mode="unavailable", warnings=_warnings("malformed_provider_output", *hint_notes))
    if isinstance(source, GoogleTrendsInterestReport):
        return _from_report(source, identity_links=identity_links, as_of=as_of, explicit_flags=None, extra_warnings=hint_notes)
    if not isinstance(source, Mapping):
        return _empty_composition(status="malformed", evidence_mode="unavailable", warnings=("malformed_provider_output",))
    if _plan_is_not_evidence(source):
        return _empty_composition(
            status="plan_not_evidence",
            evidence_mode="unavailable",
            warnings=_warnings("query_plan_is_not_collected_evidence", *hint_notes),
        )
    if source.get("fixture_mode") is not True:
        return _empty_composition(
            status="malformed",
            evidence_mode="unavailable",
            warnings=_warnings("malformed_provider_output", *hint_notes),
        )
    try:
        flags = _explicit_flags(source)
        terms = source.get("terms") or ()
        if not isinstance(terms, Sequence) or isinstance(terms, (str, bytes)):
            terms = ()
        report = build_google_trends_interest_report(
            request_kind=str(source.get("request_kind") or "interest_over_time"),
            terms=tuple(str(item) for item in terms) or ("desk fan",),
            geography=str(source.get("geography") or "US"),
            language=str(source.get("language") or "en"),
            time_resolution=str(source.get("time_resolution") or "WEEK"),
            window_start=str(source.get("window_start") or "2024-01-01"),
            window_end=str(source.get("window_end") or "2024-03-31"),
            payload=source,
            live_read_only=live_read_only,
        )
    except (GoogleTrendsInterestAdapterError, TypeError, ValueError):
        return _empty_composition(
            status="rejected",
            evidence_mode="unavailable",
            warnings=_warnings("malformed_or_rejected_provider_output", *hint_notes),
        )
    return _from_report(
        report,
        identity_links=identity_links,
        as_of=as_of,
        explicit_flags=flags,
        extra_warnings=hint_notes,
    )


__all__ = [
    "COMPOSITION_VERSION",
    "METRIC_KIND",
    "SCORING_BLOCK_REASON",
    "UNBOUND_CANDIDATE_ID",
    "GoogleTrendsAttentionComposition",
    "PreservedSearchInterestPoint",
    "compose_google_trends_attention",
]
