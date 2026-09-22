"""Offline consumer-attention importers with strict sanitization."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Mapping

from evaluation.commerce.consumer_attention import (
    PROVENANCE,
    PLATFORMS,
    SOURCE_TYPES,
    ConsumerAttentionEvidence,
    bounded,
    collapse_duplicates,
    normalize_geography,
    normalize_intent,
    normalize_language,
    normalize_observed_at,
    normalize_offering_kind,
    normalize_sentiment,
    number,
    text,
)

SECRET_KEY = re.compile(r"(token|secret|password|api[_-]?key|authorization|cookie|private[_-]?key)", re.I)
SECRET_VALUE = re.compile(r"(bearer\s+|sk_live_|sk_test_|ghp_|xox[baprs]-|-----BEGIN)", re.I)
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
RAW_HTML = re.compile(r"<(?:!doctype\s+html|html|body|script)\b", re.I)
RAW_PAYLOAD_KEY = re.compile(r"^(?:raw[_-]?(?:html|payload)|provider[_-]?payload)$", re.I)


class ConsumerAttentionImportError(ValueError):
    pass


def validate_input_path(path: str | Path) -> Path:
    candidate = Path(path)
    if ".." in candidate.parts:
        raise ConsumerAttentionImportError("path traversal is not allowed")
    if candidate.suffix.lower() not in {".json", ".csv"}:
        raise ConsumerAttentionImportError("only sanitized JSON and CSV inputs are supported")
    if not candidate.is_file():
        raise ConsumerAttentionImportError("consumer attention import file does not exist")
    return candidate


def contains_secret(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(SECRET_KEY.search(str(key)) or contains_secret(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(contains_secret(item) for item in value)
    return bool(SECRET_VALUE.search(str(value))) if value is not None else False


def contains_raw_payload(value: Any) -> bool:
    """Reject raw provider documents before bounded evidence normalization."""
    if isinstance(value, Mapping):
        return any(RAW_PAYLOAD_KEY.search(str(key)) or contains_raw_payload(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(contains_raw_payload(item) for item in value)
    return bool(RAW_HTML.search(str(value))) if value is not None else False


def _clean(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _clean(item) for key, item in value.items() if not SECRET_KEY.search(str(key))}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value


def _value(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if row.get(name) not in (None, ""):
            return row[name]
    return None


SOURCE_DEFAULTS = {
    "google_trends": "google_trends_fixture", "tiktok": "tiktok_creative_center_snapshot", "meta": "meta_ad_library_snapshot", "youtube": "youtube_search_snapshot", "reddit": "reddit_threads_manual_import", "amazon": "amazon_reviews_snapshot", "mercadolibre": "mercadolibre_reviews_snapshot", "ebay": "ebay_reviews_snapshot", "shopify": "shopify_reviews_snapshot", "minea": "minea_manual_import", "dropshipio": "dropshipio_manual_import", "pipiads": "pipiads_manual_import", "kalodata": "kalodata_manual_import", "manual": "manual_csv_import",
}


def normalize_record(row: Mapping[str, Any], *, default_platform: str = "manual", default_source_type: str = "fixture_demo", mode: str = "fixture") -> ConsumerAttentionEvidence | None:
    if not isinstance(row, Mapping) or contains_secret(row) or contains_raw_payload(row):
        return None
    row = _clean(row)
    nested = row.get("content") if isinstance(row.get("content"), Mapping) else {}
    merged = {**nested, **row}
    platform = str(_value(merged, "platform", "source_platform") or default_platform).lower()
    if platform not in PLATFORMS:
        return None
    source_type = str(_value(merged, "source_type") or default_source_type)
    if source_type not in SOURCE_TYPES:
        source_type = SOURCE_DEFAULTS.get(platform, "fixture_demo")
    candidate_id = str(_value(merged, "candidate_id", "product_id") or "").strip()
    if not candidate_id:
        return None
    identifier_values = (
        candidate_id,
        _value(merged, "observation_key", "signal_id", "metric"),
        _value(merged, "observation_value", "value"),
        _value(merged, "offering_kind", "offering_type", "business_type"),
        _value(merged, "geography", "market", "country", "region"),
        _value(merged, "language", "locale"),
    )
    if any(isinstance(value, str) and CONTROL.search(value) for value in identifier_values):
        return None
    fallback = "manual_import" if mode == "manual_import" else "fixture"
    raw_provenance = merged.get("field_provenance")
    provenance = {str(key): (str(value) if str(value) in PROVENANCE else "malformed") for key, value in raw_provenance.items()} if isinstance(raw_provenance, Mapping) else {}
    fields = ("hook", "angle", "pain_point", "desired_outcome", "objection", "claim", "proof_signal", "engagement_count", "view_count", "review_count", "search_growth_signal", "ad_active_signal")
    for field_name in fields:
        if field_name not in provenance and merged.get(field_name) not in (None, ""):
            provenance[field_name] = fallback
    engagement = number(_value(merged, "engagement_count"))
    try:
        return ConsumerAttentionEvidence(
            candidate_id=candidate_id,
            query=text(_value(merged, "query", "keyword", "content_title") or candidate_id, 120),
            source=text(_value(merged, "source", "source_name") or platform, 80),
            source_type=source_type,
            source_url=text(_value(merged, "source_url", "url") or "", 240),
            evidence_mode=mode,
            platform=platform,
            content_title=text(_value(merged, "content_title", "title") or "", 160),
            content_text_excerpt=text(_value(merged, "content_text_excerpt", "text", "comment", "review") or "", 240),
            hook=text(_value(merged, "hook", "creative_hook") or "", 160),
            angle=text(_value(merged, "angle", "creative_angle") or "", 100),
            pain_point=text(_value(merged, "pain_point", "pain") or "", 160),
            desired_outcome=text(_value(merged, "desired_outcome", "outcome") or "", 160),
            objection=text(_value(merged, "objection", "concern") or "", 160),
            claim=text(_value(merged, "claim", "ad_claim") or "", 160),
            proof_signal=text(_value(merged, "proof_signal", "proof") or "", 160),
            format=text(_value(merged, "format", "content_format") or "", 80),
            engagement_count=int(engagement) if engagement is not None else None,
            view_count=int(number(_value(merged, "view_count", "views")) or 0) or None,
            like_count=int(number(_value(merged, "like_count", "likes")) or 0) or None,
            comment_count=int(number(_value(merged, "comment_count", "comments")) or 0) or None,
            share_count=int(number(_value(merged, "share_count", "shares")) or 0) or None,
            save_count=int(number(_value(merged, "save_count", "saves")) or 0) or None,
            review_count=int(number(_value(merged, "review_count", "reviews")) or 0) or None,
            rating=number(_value(merged, "rating", "stars")),
            sentiment_label=normalize_sentiment(_value(merged, "sentiment_label", "sentiment")),
            intent_label=normalize_intent(_value(merged, "intent_label", "intent", "keyword_intent")),
            trend_label=text(_value(merged, "trend_label", "trend") or "", 80),
            search_growth_signal=number(_value(merged, "search_growth_signal", "growth_signal", "growth")),
            keyword=text(_value(merged, "keyword", "query") or "", 120),
            keyword_intent=normalize_intent(_value(merged, "keyword_intent", "intent")),
            ad_active_signal=str(_value(merged, "ad_active_signal", "ad_active") or "").lower() in {"1", "true", "yes", "active"},
            ad_platform=text(_value(merged, "ad_platform") or "", 60),
            creative_format=text(_value(merged, "creative_format", "format") or "", 80),
            creator_style=text(_value(merged, "creator_style") or "", 80),
            ugc_scriptability=number(_value(merged, "ugc_scriptability", "ugc_score")),
            visual_demo_score=number(_value(merged, "visual_demo_score", "demo_score")),
            source_confidence=bounded(_value(merged, "source_confidence", "confidence") or (0.7 if mode == "manual_import" else 0.55)),
            field_provenance=provenance,
            warnings=tuple(sorted({text(item, 160) for item in merged.get("warnings", []) if isinstance(item, str)})),
            observed_at=normalize_observed_at(_value(merged, "observed_at", "captured_at")),
            offering_kind=normalize_offering_kind(_value(merged, "offering_kind", "offering_type", "business_type")),
            geography=normalize_geography(_value(merged, "geography", "market", "country", "region")),
            language=normalize_language(_value(merged, "language", "locale")),
            observation_key=text(_value(merged, "observation_key", "signal_id", "metric") or "", 100),
            observation_value=None if _value(merged, "observation_value", "value") in (None, "") else text(_value(merged, "observation_value", "value"), 120),
        )
    except ValueError:
        # A malformed row is unavailable evidence, never a partially trusted
        # record with inferred timestamp, geography, or offering identity.
        return None


def _json_rows(path: str | Path) -> list[Mapping[str, Any]]:
    raw = json.loads(validate_input_path(path).read_text(encoding="utf8"))
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, Mapping)]
    if isinstance(raw, Mapping):
        for key in ("records", "items", "results", "reviews", "comments", "ads"):
            if isinstance(raw.get(key), list):
                return [row for row in raw[key] if isinstance(row, Mapping)]
        return [raw]
    return []


def import_json(path: str | Path, *, platform: str = "manual", source_type: str = "fixture_demo") -> list[ConsumerAttentionEvidence]:
    return collapse_duplicates(item for row in _json_rows(path) if (item := normalize_record(row, default_platform=platform, default_source_type=source_type, mode="fixture")))


def import_csv(path: str | Path, *, platform: str = "manual", source_type: str = "manual_csv_import") -> list[ConsumerAttentionEvidence]:
    target = validate_input_path(path)
    with target.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    return collapse_duplicates(item for row in rows if (item := normalize_record(row, default_platform=str(row.get("platform") or platform), default_source_type=str(row.get("source_type") or source_type), mode="manual_import")))
