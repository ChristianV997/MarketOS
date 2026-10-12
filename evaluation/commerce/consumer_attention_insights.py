"""Offline consumer-attention insight synthesis.

Turns already-normalized search-interest, ad-library, review, and comment
signals into demand themes, objections, audience/context hints, and
evidence-backed product questions. It does not collect data, rescore the
opportunity, or treat an engagement count as purchase intent or supplier proof.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .consumer_attention import (
    ConsumerAttentionEvidence,
    ConsumerAttentionReport,
    freshness_state,
    number,
    text,
)

SIGNAL_FAMILIES = ("search_trend", "ad_library", "review", "comment", "unknown")
INSIGHT_KINDS = ("demand_theme", "objection", "audience_hint", "product_question")
_SEARCH_PLATFORMS = frozenset({"google_trends"})
_AD_PLATFORMS = frozenset({"meta", "tiktok", "minea", "dropshipio", "pipiads", "kalodata"})
_REVIEW_PLATFORMS = frozenset({"amazon", "mercadolibre", "ebay", "shopify"})
_COMMENT_PLATFORMS = frozenset({"youtube", "reddit"})
_UNSUPPORTED_MARKERS = (
    "purchase intent",
    "buying intent",
    "will buy",
    "customers will buy",
    "proven demand",
    "verified demand",
    "supplier proof",
    "supplier verified",
    "verified supplier",
    "guaranteed sales",
    "conversion rate",
)
_SECRET_MARKERS = ("ghp_", "github_pat_", "bearer ", "-----begin", "api_key", "password", "client_secret")
_NOT_AUTHORITY = "not_purchase_intent_or_supplier_proof"
_EVIDENCE_FIELDS = set(ConsumerAttentionEvidence.__dataclass_fields__)


def _safe_phrase(value: Any, limit: int = 160) -> str:
    cleaned = text(value, limit)
    lowered = cleaned.casefold()
    if any(marker in lowered for marker in _SECRET_MARKERS):
        return ""
    return cleaned


def _unsupported(value: Any) -> bool:
    lowered = _safe_phrase(value, 240).casefold()
    return any(marker in lowered for marker in _UNSUPPORTED_MARKERS)


def signal_family(record: ConsumerAttentionEvidence) -> str:
    """Keep ads, reviews, comments, and search trends distinguishable."""
    source_type = record.source_type
    if record.platform in _SEARCH_PLATFORMS or source_type.startswith("google_trends"):
        return "search_trend"
    if (
        record.platform in _AD_PLATFORMS
        or record.ad_active_signal
        or record.ad_platform
        or "ad_" in source_type
        or source_type.endswith("_ad_snapshot")
    ):
        return "ad_library"
    if record.platform in _REVIEW_PLATFORMS or "review" in source_type:
        return "review"
    if record.platform in _COMMENT_PLATFORMS:
        return "comment"
    if record.keyword or record.search_growth_signal is not None:
        return "search_trend"
    if record.review_count or record.objection or record.pain_point:
        return "review"
    return "unknown"


def _records_from(value: Any) -> list[ConsumerAttentionEvidence]:
    if isinstance(value, ConsumerAttentionEvidence):
        return [value]
    if isinstance(value, ConsumerAttentionReport):
        return [item for candidate in value.candidates for item in candidate.evidence]
    if isinstance(value, Mapping):
        if isinstance(value.get("candidates"), list):
            rows: list[ConsumerAttentionEvidence] = []
            for candidate in value["candidates"]:
                if not isinstance(candidate, Mapping):
                    continue
                for item in candidate.get("evidence") or []:
                    if isinstance(item, Mapping):
                        rows.append(_evidence_from_mapping(item, candidate.get("candidate_id"), candidate.get("query")))
            return rows
        if "candidate_id" in value and "source" in value:
            return [_evidence_from_mapping(value)]
        return []
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        rows = []
        for item in value:
            if isinstance(item, ConsumerAttentionEvidence):
                rows.append(item)
            elif isinstance(item, Mapping):
                rows.append(_evidence_from_mapping(item))
        return rows
    return []


def _evidence_from_mapping(
    item: Mapping[str, Any],
    candidate_id: Any = None,
    query: Any = None,
) -> ConsumerAttentionEvidence:
    payload = {key: value for key, value in item.items() if key in _EVIDENCE_FIELDS}
    payload.setdefault("candidate_id", candidate_id or item.get("candidate_id") or "unknown-candidate")
    payload.setdefault("query", query or item.get("query") or payload["candidate_id"])
    payload.setdefault("source", item.get("source") or item.get("source_type") or "normalized-signal")
    payload.setdefault("source_type", item.get("source_type") or "fixture_demo")
    return ConsumerAttentionEvidence(**payload)


def _sum_count(records: Iterable[ConsumerAttentionEvidence], field_name: str) -> int | None:
    observed = [number(getattr(record, field_name)) for record in records]
    values = [int(item) for item in observed if item is not None]
    return sum(values) if values else None


def _window(records: list[ConsumerAttentionEvidence], *, as_of: Any, max_age_days: int) -> dict[str, Any]:
    observed = [record.observed_at for record in records if record.observed_at]
    freshness = tuple(sorted({freshness_state(record.observed_at, as_of=as_of, max_age_days=max_age_days) for record in records}))
    return {
        "earliest": min(observed) if observed else None,
        "latest": max(observed) if observed else None,
        "freshness": list(freshness),
        "missing_time_count": sum(1 for record in records if not record.observed_at),
        "as_of": as_of if isinstance(as_of, str) else None,
    }


def _counts(records: list[ConsumerAttentionEvidence]) -> dict[str, Any]:
    return {
        "evidence_count": len(records),
        "engagement_count": _sum_count(records, "engagement_count"),
        "review_count": _sum_count(records, "review_count"),
        "view_count": _sum_count(records, "view_count"),
        "interpretation": _NOT_AUTHORITY,
    }


def _evidence_class(records: list[ConsumerAttentionEvidence], *, conflicts: bool, window: Mapping[str, Any]) -> str:
    if not records:
        return "unavailable"
    if conflicts:
        return "conflicting"
    freshness = set(window.get("freshness") or [])
    if "stale" in freshness or "future_dated" in freshness:
        return "stale" if "stale" in freshness else "future_dated"
    modes = {record.evidence_mode for record in records}
    if modes <= {"fixture", "fixture_demo"}:
        return "fixture"
    if modes & {"manual_import", "manual_csv_import"}:
        return "manual_import"
    return "observed"


def _duplicate_note(records: list[ConsumerAttentionEvidence]) -> tuple[str, ...]:
    seen: dict[tuple[str, str, str, str], int] = {}
    for record in records:
        key = (
            record.candidate_id,
            record.source,
            record.platform,
            record.content_title or record.hook or record.keyword or record.objection,
        )
        seen[key] = seen.get(key, 0) + 1
    return tuple(sorted(f"duplicate_source:{source}:{platform}" for (_, source, platform, _), count in seen.items() if count > 1))


def _conflicts(records: list[ConsumerAttentionEvidence]) -> tuple[str, ...]:
    values: dict[str, set[str]] = {}
    sentiments: dict[str, set[str]] = {}
    for record in records:
        if record.observation_key and record.observation_value:
            values.setdefault(record.observation_key, set()).add(record.observation_value)
        if record.sentiment_label and record.sentiment_label != "unknown":
            sentiments.setdefault(record.candidate_id, set()).add(record.sentiment_label)
    notes = [f"conflicting_observation:{key}" for key, observed in values.items() if len(observed) > 1]
    notes.extend(
        f"conflicting_sentiment:{candidate}"
        for candidate, labels in sentiments.items()
        if "positive" in labels and "negative" in labels
    )
    return tuple(sorted(notes))


@dataclass(frozen=True)
class AttentionInsight:
    insight_id: str
    candidate_id: str
    kind: str
    statement: str
    signal_family: str
    sources: tuple[str, ...]
    platforms: tuple[str, ...]
    geographies: tuple[str, ...]
    languages: tuple[str, ...]
    observation_window: Mapping[str, Any]
    aggregate_counts: Mapping[str, Any]
    evidence_class: str
    uncertainty: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    unsupported_claims: tuple[str, ...] = ()
    supporting_excerpts: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "insight_id": self.insight_id,
            "candidate_id": self.candidate_id,
            "kind": self.kind,
            "statement": self.statement,
            "signal_family": self.signal_family,
            "sources": list(self.sources),
            "platforms": list(self.platforms),
            "geographies": list(self.geographies),
            "languages": list(self.languages),
            "observation_window": dict(self.observation_window),
            "aggregate_counts": dict(self.aggregate_counts),
            "evidence_class": self.evidence_class,
            "uncertainty": list(self.uncertainty),
            "contradictions": list(self.contradictions),
            "unsupported_claims": list(self.unsupported_claims),
            "supporting_excerpts": list(self.supporting_excerpts),
        }


@dataclass(frozen=True)
class ConsumerAttentionInsightReport:
    report_version: str
    evidence_mode: str
    candidate_count: int
    evidence_count: int
    signal_families: tuple[str, ...]
    demand_themes: tuple[AttentionInsight, ...]
    objections: tuple[AttentionInsight, ...]
    audience_hints: tuple[AttentionInsight, ...]
    product_questions: tuple[AttentionInsight, ...]
    warnings: tuple[str, ...] = ()
    read_only: bool = True
    network_calls: bool = False
    mutated: bool = False
    authority: Mapping[str, bool] = field(
        default_factory=lambda: {
            "purchase_intent": False,
            "supplier_proof": False,
            "launch_authorization": False,
            "opportunity_rescore": False,
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": self.report_version,
            "evidence_mode": self.evidence_mode,
            "candidate_count": self.candidate_count,
            "evidence_count": self.evidence_count,
            "signal_families": list(self.signal_families),
            "demand_themes": [item.to_dict() for item in self.demand_themes],
            "objections": [item.to_dict() for item in self.objections],
            "audience_hints": [item.to_dict() for item in self.audience_hints],
            "product_questions": [item.to_dict() for item in self.product_questions],
            "warnings": list(self.warnings),
            "read_only": True,
            "network_calls": False,
            "mutated": False,
            "authority": dict(self.authority),
        }


def _meta(records: list[ConsumerAttentionEvidence]) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    sources = tuple(sorted({record.source for record in records if record.source}))
    platforms = tuple(sorted({record.platform for record in records if record.platform}))
    geographies = tuple(sorted({record.geography for record in records if record.geography}))
    languages = tuple(sorted({record.language for record in records if record.language}))
    return sources, platforms, geographies, languages


def _uncertainty(records: list[ConsumerAttentionEvidence], window: Mapping[str, Any], conflicts: tuple[str, ...]) -> tuple[str, ...]:
    notes: list[str] = []
    if any(not record.geography for record in records):
        notes.append("geography_missing")
    if any(not record.language for record in records):
        notes.append("language_missing")
    if window.get("missing_time_count"):
        notes.append("observation_time_missing")
    if "stale" in set(window.get("freshness") or []):
        notes.append("stale_observation")
    if "future_dated" in set(window.get("freshness") or []):
        notes.append("future_dated_observation")
    notes.extend(conflicts)
    notes.extend(_duplicate_note(records))
    return tuple(dict.fromkeys(notes))


def _excerpts(records: list[ConsumerAttentionEvidence]) -> tuple[str, ...]:
    values = []
    for record in records:
        excerpt = _safe_phrase(record.content_text_excerpt or record.hook or record.pain_point or record.objection)
        if excerpt and excerpt not in values and not _unsupported(excerpt):
            values.append(excerpt)
    return tuple(values[:3])


def _theme_statement(family: str, records: list[ConsumerAttentionEvidence]) -> str:
    lead = records[0]
    if family == "search_trend":
        keyword = _safe_phrase(lead.keyword or lead.query, 80) or "the observed query"
        label = _safe_phrase(lead.trend_label, 40) or "unlabeled"
        return f"Search interest observed for '{keyword}' ({label}). Directional search movement only; not sales, purchase intent, or supplier proof."
    if family == "ad_library":
        hook = _safe_phrase(lead.hook or lead.angle or lead.pain_point, 80) or "an unlabeled creative"
        return f"Ad activity observed on {lead.platform}: '{hook}'. Creative presence only; not campaign performance, purchase intent, or supplier proof."
    if family == "review":
        phrase = _safe_phrase(lead.pain_point or lead.desired_outcome or lead.objection, 80) or "review language"
        return f"Review language includes '{phrase}'. Voice-of-customer only; not verified demand or supplier proof."
    if family == "comment":
        phrase = _safe_phrase(lead.hook or lead.pain_point or lead.desired_outcome, 80) or "comment language"
        return f"Comment or video language includes '{phrase}'. Language evidence only; not representative demand or supplier proof."
    return "An unlabeled attention signal was supplied. It is not purchase intent or supplier proof."


def _build_insight(
    *,
    insight_id: str,
    candidate_id: str,
    kind: str,
    statement: str,
    family: str,
    records: list[ConsumerAttentionEvidence],
    as_of: Any,
    max_age_days: int,
    extra_uncertainty: tuple[str, ...] = (),
    contradictions: tuple[str, ...] = (),
    unsupported: tuple[str, ...] = (),
) -> AttentionInsight:
    sources, platforms, geographies, languages = _meta(records)
    window = _window(records, as_of=as_of, max_age_days=max_age_days)
    conflicts = _conflicts(records)
    return AttentionInsight(
        insight_id,
        candidate_id,
        kind,
        statement,
        family,
        sources,
        platforms,
        geographies,
        languages,
        window,
        _counts(records),
        _evidence_class(records, conflicts=bool(conflicts), window=window),
        _uncertainty(records, window, conflicts) + extra_uncertainty,
        contradictions or conflicts,
        unsupported,
        _excerpts(records),
    )


def _themes(grouped: dict[tuple[str, str], list[ConsumerAttentionEvidence]], *, as_of: Any, max_age_days: int) -> tuple[AttentionInsight, ...]:
    themes = []
    for (candidate_id, family), records in sorted(grouped.items()):
        usable = [record for record in records if not _unsupported(record.claim) and not _unsupported(record.proof_signal)]
        if not usable or family == "unknown":
            continue
        themes.append(
            _build_insight(
                insight_id=f"theme:{candidate_id}:{family}",
                candidate_id=candidate_id,
                kind="demand_theme",
                statement=_theme_statement(family, usable),
                family=family,
                records=usable,
                as_of=as_of,
                max_age_days=max_age_days,
                unsupported=tuple(sorted({
                    "unsupported_claim_not_promoted"
                    for record in records
                    if _unsupported(record.claim) or _unsupported(record.proof_signal) or _unsupported(record.observation_value)
                })),
            )
        )
    return tuple(themes)


def _objections(records: list[ConsumerAttentionEvidence], *, as_of: Any, max_age_days: int) -> tuple[AttentionInsight, ...]:
    grouped: dict[tuple[str, str, str], list[ConsumerAttentionEvidence]] = {}
    for record in records:
        phrase = _safe_phrase(record.objection, 120)
        if not phrase:
            continue
        grouped.setdefault((record.candidate_id, signal_family(record), phrase.casefold()), []).append(record)
    objections = []
    for (candidate_id, family, _), rows in sorted(grouped.items()):
        phrase = _safe_phrase(rows[0].objection, 120)
        objections.append(
            _build_insight(
                insight_id=f"objection:{candidate_id}:{family}:{re.sub(r'[^a-z0-9]+', '-', phrase.casefold()).strip('-')[:40]}",
                candidate_id=candidate_id,
                kind="objection",
                statement=f"Objection observed in {family} evidence: '{phrase}'. This is a stated friction, not a purchase or supplier conclusion.",
                family=family,
                records=rows,
                as_of=as_of,
                max_age_days=max_age_days,
            )
        )
    return tuple(objections)


def _audience(records: list[ConsumerAttentionEvidence], *, as_of: Any, max_age_days: int) -> tuple[AttentionInsight, ...]:
    grouped: dict[str, list[ConsumerAttentionEvidence]] = {}
    for record in records:
        grouped.setdefault(record.candidate_id, []).append(record)
    hints = []
    for candidate_id, rows in sorted(grouped.items()):
        geographies = sorted({row.geography for row in rows if row.geography})
        languages = sorted({row.language for row in rows if row.language})
        styles = sorted({_safe_phrase(row.creator_style, 40) for row in rows if row.creator_style})
        intents = sorted({row.intent_label for row in rows if row.intent_label and row.intent_label != "unknown"})
        geo = ", ".join(geographies) if geographies else "unspecified"
        language = ", ".join(languages) if languages else "unspecified"
        hints.append(
            _build_insight(
                insight_id=f"audience:{candidate_id}",
                candidate_id=candidate_id,
                kind="audience_hint",
                statement=(
                    f"Context hint only: geography={geo}; language={language}; "
                    f"creator_style={', '.join(styles) or 'unspecified'}; intent_label={', '.join(intents) or 'unknown'}. "
                    "Missing context is not inferred. Engagement counts do not identify an audience or purchase intent."
                ),
                family="mixed" if len({signal_family(row) for row in rows}) > 1 else signal_family(rows[0]),
                records=rows,
                as_of=as_of,
                max_age_days=max_age_days,
            )
        )
    return tuple(hints)


def _questions(records: list[ConsumerAttentionEvidence], *, as_of: Any, max_age_days: int) -> tuple[AttentionInsight, ...]:
    grouped: dict[str, list[ConsumerAttentionEvidence]] = {}
    for record in records:
        grouped.setdefault(record.candidate_id, []).append(record)
    questions = []
    for candidate_id, rows in sorted(grouped.items()):
        families = {signal_family(row) for row in rows}
        conflicts = _conflicts(rows)
        window = _window(rows, as_of=as_of, max_age_days=max_age_days)
        prompts: list[tuple[str, str]] = []
        if "search_trend" in families and "review" not in families:
            prompts.append(("search-without-review", "Search movement was observed without review evidence. What usage or purchase evidence should the opportunity review require before treating this as demand?"))
        if "ad_library" in families and "search_trend" not in families:
            prompts.append(("ads-without-search", "Ad activity was observed without a search-interest signal. What remains unknown for the opportunity review?"))
        if any(row.objection for row in rows):
            prompts.append(("objection-coverage", "An objection was observed. Does it appear in the other signal families, and is it a product issue or a context issue?"))
        if any(not row.geography for row in rows):
            prompts.append(("missing-geography", "Geography was not supplied on at least one signal. Which market is this attention evidence allowed to describe?"))
        if window["missing_time_count"]:
            prompts.append(("missing-time", "Observation time was missing. Which window should the opportunity review treat as current?"))
        if "stale" in set(window["freshness"]):
            prompts.append(("stale", "At least one observation is stale relative to the supplied reference time. Should it still inform the opportunity decision?"))
        if conflicts:
            prompts.append(("conflict", f"Sources disagree ({', '.join(conflicts)}). Which observation should the opportunity review use, and which stays unresolved?"))
        if any(_unsupported(row.claim) or _unsupported(row.proof_signal) or _unsupported(row.observation_value) for row in rows):
            prompts.append(("unsupported-claim", "A supplied claim asserted purchase intent or supplier proof. Which independent evidence, if any, supports that claim?"))
        if not prompts:
            prompts.append(("coverage", "Which missing search, ad, or review evidence would change this opportunity review?"))
        for suffix, statement in prompts:
            questions.append(
                _build_insight(
                    insight_id=f"question:{candidate_id}:{suffix}",
                    candidate_id=candidate_id,
                    kind="product_question",
                    statement=statement,
                    family="mixed" if len(families) > 1 else next(iter(families)),
                    records=rows,
                    as_of=as_of,
                    max_age_days=max_age_days,
                    contradictions=conflicts,
                    unsupported=("unsupported_claim_not_promoted",) if suffix == "unsupported-claim" else (),
                )
            )
    return tuple(questions)


def build_consumer_attention_insights(
    evidence: Any,
    *,
    as_of: Any = None,
    max_age_days: int = 90,
    evidence_mode: str = "fixture",
) -> ConsumerAttentionInsightReport:
    """Synthesize insights from normalized attention evidence. Caller data is not mutated."""
    if max_age_days < 1:
        raise ValueError("max_age_days must be positive")
    records = _records_from(evidence)
    grouped: dict[tuple[str, str], list[ConsumerAttentionEvidence]] = {}
    for record in records:
        grouped.setdefault((record.candidate_id, signal_family(record)), []).append(record)
    families = tuple(sorted({family for _, family in grouped}))
    warnings = ["consumer_attention_is_not_supplier_proof", "engagement_count_is_not_purchase_intent"]
    if not records:
        warnings.append("consumer_attention_insights_not_supplied")
    if any(_conflicts(rows) for rows in grouped.values()):
        warnings.append("conflicting_consumer_observations")
    modes = {record.evidence_mode for record in records}
    mode = evidence_mode
    if modes:
        mode = "fixture" if modes <= {"fixture", "fixture_demo"} else "manual_import" if modes & {"manual_import", "manual_csv_import"} else "observed"
    return ConsumerAttentionInsightReport(
        "consumer-attention-insights-v1",
        mode,
        len({record.candidate_id for record in records}),
        len(records),
        families,
        _themes(grouped, as_of=as_of, max_age_days=max_age_days),
        _objections(records, as_of=as_of, max_age_days=max_age_days),
        _audience(records, as_of=as_of, max_age_days=max_age_days),
        _questions(records, as_of=as_of, max_age_days=max_age_days),
        tuple(dict.fromkeys(warnings)),
    )


def questions_for_opportunity(report: ConsumerAttentionInsightReport | Mapping[str, Any]) -> tuple[str, ...]:
    """Return evidence-backed questions for the existing opportunity workflow."""
    if isinstance(report, ConsumerAttentionInsightReport):
        return tuple(item.statement for item in report.product_questions)
    questions = report.get("product_questions") if isinstance(report, Mapping) else ()
    return tuple(str(item.get("statement")) for item in questions or [] if isinstance(item, Mapping) and item.get("statement"))


def render_consumer_attention_insights_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Consumer attention insights",
        "",
        "Offline synthesis only. Not purchase intent, supplier proof, or launch authorization.",
        f"Evidence mode: `{report.get('evidence_mode', 'unavailable')}`",
        f"Signal families: {', '.join(report.get('signal_families') or []) or 'none'}",
        "",
        "## Demand themes",
    ]
    for item in report.get("demand_themes") or []:
        lines.append(f"- [{item.get('signal_family')}] {item.get('statement')}")
    lines += ["", "## Objections"]
    objections = report.get("objections") or []
    lines.extend(f"- [{item.get('signal_family')}] {item.get('statement')}" for item in objections)
    if not objections:
        lines.append("- None recorded.")
    lines += ["", "## Audience and context hints"]
    hints = report.get("audience_hints") or []
    lines.extend(f"- {item.get('statement')}" for item in hints)
    if not hints:
        lines.append("- None recorded.")
    lines += ["", "## Product questions for the opportunity review"]
    questions = report.get("product_questions") or []
    lines.extend(f"- {item.get('statement')}" for item in questions)
    if not questions:
        lines.append("- None recorded.")
    lines += ["", "## Safety", "- No live collection, credentials, scraping, publishing, or customer messaging.", ""]
    return "\n".join(lines)


__all__ = [
    "AttentionInsight",
    "ConsumerAttentionInsightReport",
    "build_consumer_attention_insights",
    "questions_for_opportunity",
    "render_consumer_attention_insights_markdown",
    "signal_family",
]
