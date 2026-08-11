"""Pure metric calculations for Commerce Intelligence evaluation.

All functions accept JSON-like dictionaries and return deterministic values.
They do not fetch, write, call providers, or use wall-clock time.  Missing
evidence is represented as ``None`` or an explicit zero count rather than
being converted into a favorable assumption.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

SUPPLIER_FIELDS = (
    "title", "price", "sku", "category", "variants", "weight_kg", "inventory_status",
    "inventory_quantity", "warehouse_origin", "shipping_cost", "estimated_delivery_days", "quality_evidence",
    "rating", "reviews_count", "images", "description",
)
CONFIDENCE_BINS = ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01))


def _round(value: float | None, digits: int = 4) -> float | None:
    return round(float(value), digits) if value is not None and math.isfinite(float(value)) else None


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _records_from_artifact_or_events(artifact: Mapping[str, Any], events: Iterable[Mapping[str, Any]], event_type: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for event in events:
        if event.get("event_type") == event_type and isinstance(event.get("payload"), Mapping):
            records.append(dict(event["payload"]))
    return records


def _confidence_histogram(values: Iterable[Any]) -> dict[str, int]:
    histogram = {f"{low:.1f}-{min(high, 1.0):.1f}": 0 for low, high in CONFIDENCE_BINS}
    for raw in values:
        value = _number(raw)
        if value is None:
            continue
        value = min(max(value, 0.0), 1.0)
        for low, high in CONFIDENCE_BINS:
            if low <= value < high:
                histogram[f"{low:.1f}-{min(high, 1.0):.1f}"] += 1
                break
    return histogram


def _status_from_sample(sample_size: int, warnings: list[str]) -> str:
    if sample_size == 0:
        return "insufficient_evidence"
    return "measured_with_warnings" if warnings else "measured"


def supplier_metrics(artifact: Mapping[str, Any], events: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    records = _records_from_artifact_or_events(artifact, events, "supplier_product_observed")
    result = artifact.get("supplier_evidence")
    if not records and isinstance(result, Mapping) and isinstance(result.get("result"), Mapping):
        records = [dict(result["result"])]
    warnings: list[str] = []
    if isinstance(result, Mapping):
        warnings.extend(str(item) for item in result.get("warnings", []) if item)
    status_counts: Counter[str] = Counter()
    field_counts: Counter[str] = Counter()
    field_total = 0
    confidences: list[float] = []
    extraction_methods: Counter[str] = Counter()
    cache_states: Counter[str] = Counter()
    robots_blocked = 0
    network_failures = 0
    source_distribution: Counter[str] = Counter()
    attempted_sources: Counter[str] = Counter()
    authenticated_attempted = 0
    authenticated_succeeded = 0
    credential_missing = 0
    live_flag_disabled = 0
    for record in records:
        statuses = record.get("field_status", {})
        statuses = statuses if isinstance(statuses, Mapping) else {}
        for field_name in SUPPLIER_FIELDS:
            state = str(statuses.get(field_name, "unavailable"))
            status_counts[state] += 1
            field_total += 1
            if state == "observed":
                field_counts[field_name] += 1
        confidence = _number(record.get("confidence"))
        if confidence is not None:
            confidences.append(confidence)
        method = str(record.get("extraction_method", "unknown"))
        extraction_methods[method] += 1
        source = str(record.get("source_type") or record.get("source") or "unavailable")
        if "authenticated" in source or "cj_authenticated_api" in source:
            source = "authenticated_readonly_api"
        elif "js" in source.lower() or "js_render" in method.lower():
            source = "public_page_js"
        elif "public" in source:
            source = "public_page_static"
        source_distribution[source] += 1
        if source == "authenticated_readonly_api":
            authenticated_succeeded += 1
        for warning in record.get("warnings", []) if isinstance(record.get("warnings"), list) else []:
            lowered = str(warning).lower()
            if "robots" in lowered:
                robots_blocked += 1
            if "fetch_failed" in lowered or "network" in lowered:
                network_failures += 1
        cache_status = record.get("cache_status")
        if cache_status:
            cache_states[str(cache_status)] += 1
    for event in events:
        if event.get("event_type") == "supplier_evidence_requested":
            payload = event.get("payload", {})
            metadata = event.get("metadata", {})
            source = payload.get("source_type") if isinstance(payload, Mapping) else None
            source = source or (metadata.get("supplier_source") if isinstance(metadata, Mapping) else None) or "unavailable"
            normalized_source = str(source)
            if "authenticated" in normalized_source or "cj_authenticated_api" in normalized_source:
                normalized_source = "authenticated_readonly_api"
            elif "js" in normalized_source.lower():
                normalized_source = "public_page_js"
            elif "public" in normalized_source:
                normalized_source = "public_page_static"
            attempted_sources[normalized_source] += 1
            if source == "authenticated_readonly_api":
                authenticated_attempted += 1
            status = str(payload.get("status", "")) if isinstance(payload, Mapping) else ""
            if status == "credential_missing":
                credential_missing += 1
            if status == "live_flag_disabled":
                live_flag_disabled += 1
        metadata = event.get("metadata", {})
        if isinstance(metadata, Mapping) and metadata.get("cache_status"):
            cache_states[str(metadata["cache_status"])] += 1
    known_cache = sum(cache_states.values())
    observed = status_counts.get("observed", 0)
    metric_warnings = list(dict.fromkeys(warnings))
    if not records:
        metric_warnings.append("no_supplier_product_observed_event")
    metrics = {
        "attempt_count": sum(event.get("event_type") == "supplier_evidence_requested" for event in events),
        "observed_product_count": len(records),
        "observed_field_count": observed,
        "missing_field_count": sum(status_counts[state] for state in ("unavailable", "missing")),
        "field_observation_rate": _round(observed / field_total) if field_total else None,
        "observed_fields": dict(sorted(field_counts.items())),
        "provenance_distribution": dict(sorted(status_counts.items())),
        "confidence_histogram": _confidence_histogram(confidences),
        "confidence_mean": _round(statistics.fmean(confidences)) if confidences else None,
        "confidence_min": _round(min(confidences)) if confidences else None,
        "confidence_max": _round(max(confidences)) if confidences else None,
        "cache_hit_rate": _round(cache_states.get("hit", 0) / known_cache) if known_cache else None,
        "cache_status_counts": dict(sorted(cache_states.items())),
        "robots_blocked": robots_blocked,
        "network_failures": network_failures,
        "js_rendered": sum("js_render" in method.lower() for method in extraction_methods.elements()),
        "static_extraction": sum("jsonld" in method.lower() or "static" in method.lower() for method in extraction_methods.elements()),
        "extraction_method_counts": dict(sorted(extraction_methods.items())),
        "authenticated_supplier_attempted": authenticated_attempted,
        "authenticated_supplier_succeeded": authenticated_succeeded,
        "supplier_source_distribution": dict(sorted((attempted_sources or source_distribution).items())),
        "supplier_observed_price_rate": _round(field_counts.get("price", 0) / len(records)) if records else 0.0,
        "supplier_inventory_observed_rate": _round(field_counts.get("inventory_quantity", 0) / len(records)) if records else 0.0,
        "supplier_shipping_observed_rate": _round(field_counts.get("shipping_cost", 0) / len(records)) if records else 0.0,
        "supplier_sku_observed_rate": _round(field_counts.get("sku", 0) / len(records)) if records else 0.0,
        "supplier_variant_observed_rate": _round(field_counts.get("variants", 0) / len(records)) if records else 0.0,
        "credential_missing_count": credential_missing,
        "live_flag_disabled_count": live_flag_disabled,
    }
    return metrics, metric_warnings, records


def competition_metrics(artifact: Mapping[str, Any], events: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    records = _records_from_artifact_or_events(artifact, events, "competition_observed")
    result = artifact.get("competition_evidence")
    if not records and isinstance(result, Mapping):
        records = [dict(item) for item in result.get("offers", []) if isinstance(item, Mapping)]
    warnings = [str(item) for item in result.get("warnings", [])] if isinstance(result, Mapping) else []
    prices = [_number(record.get("price")) for record in records if str(record.get("field_status", {}).get("price")) == "observed"]
    prices = [price for price in prices if price is not None]
    keys: list[str] = []
    for record in records:
        keys.append(str(record.get("external_listing_id") or record.get("source_url") or str(record.get("title", "")).strip().casefold()))
    duplicate_count = len(keys) - len(set(keys))
    warnings = list(dict.fromkeys(warnings + (["no_competitor_offers"] if not records else [])))
    metrics = {
        "offer_count": len(records),
        "observed_competitor_count": len(prices),
        "pricing_coverage": _round(len(prices) / len(records)) if records else None,
        "market_spread": _round(max(prices) - min(prices), 2) if prices else None,
        "pricing_variance": _round(statistics.pvariance(prices), 4) if len(prices) > 1 else None,
        "pricing_mean": _round(statistics.fmean(prices), 2) if prices else None,
        "pricing_median": _round(statistics.median(prices), 2) if prices else None,
        "duplicate_count": duplicate_count,
        "duplicate_ratio": _round(duplicate_count / len(records)) if records else None,
        "sources": dict(sorted(Counter(str(record.get("source", "unknown")) for record in records).items())),
    }
    return metrics, warnings, records


def opportunity_metrics(artifact: Mapping[str, Any], events: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], list[str], list[float], list[str]]:
    result = artifact.get("opportunity_scoring")
    records = _records_from_artifact_or_events(artifact, events, "candidate_scored")
    if isinstance(result, Mapping) and isinstance(result.get("scores"), list):
        records = [dict(item) for item in result.get("scores", []) if isinstance(item, Mapping)]
    scores = [_number(record.get("effective_score", record.get("composite_score"))) for record in records]
    confidences = [_number(record.get("confidence")) for record in records]
    scores = [value for value in scores if value is not None]
    confidences = [value for value in confidences if value is not None]
    ranked = next((dict(event.get("payload", {})) for event in events if event.get("event_type") == "opportunity_ranked"), {})
    ranking = [str(item) for item in ranked.get("ranking", [])]
    if not ranking and isinstance(result, Mapping):
        ranking = [str(item.get("candidate_id")) for item in result.get("scores", []) if isinstance(item, Mapping)]
    warnings = ["no_opportunity_scores"] if not records else []
    metrics = {
        "candidate_count": len(records),
        "score_distribution": {
            "min": _round(min(scores)) if scores else None,
            "max": _round(max(scores)) if scores else None,
            "mean": _round(statistics.fmean(scores)) if scores else None,
            "histogram": _confidence_histogram((value / 100 for value in scores)),
        },
        "confidence_distribution": {
            "min": _round(min(confidences)) if confidences else None,
            "max": _round(max(confidences)) if confidences else None,
            "mean": _round(statistics.fmean(confidences)) if confidences else None,
            "histogram": _confidence_histogram(confidences),
        },
        "high_confidence_count": sum(value >= 0.7 for value in confidences),
        "low_confidence_count": sum(value < 0.4 for value in confidences),
        "ranking": ranking,
        "ranking_stability": None,
    }
    return metrics, warnings, scores, ranking


def research_metrics(artifact: Mapping[str, Any], events: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    portfolio = artifact.get("product_research_portfolio")
    if not isinstance(portfolio, Mapping):
        portfolio = next((event.get("payload", {}) for event in events if event.get("event_type") == "research_portfolio_updated"), {})
    portfolio = portfolio if isinstance(portfolio, Mapping) else {}
    clusters = [item for item in portfolio.get("clusters", []) if isinstance(item, Mapping)]
    candidate_ids = [str(item) for item in portfolio.get("candidate_ids", [])]
    duplicate_groups = [item for item in portfolio.get("duplicate_groups", []) if isinstance(item, Mapping)]
    duplicate_groups_with_members = [item for item in duplicate_groups if len(item.get("member_ids", [])) > 1]
    representative_ids = {str(item.get("representative_id")) for item in duplicate_groups if item.get("representative_id")}
    duplicate_ratio = len(duplicate_groups_with_members) / len(candidate_ids) if candidate_ids else None
    canonicalization_rate = len(representative_ids) / len(candidate_ids) if candidate_ids else None
    cluster_confidences = [_number(item.get("confidence")) for item in clusters]
    cluster_confidences = [value for value in cluster_confidences if value is not None]
    movements = [event for event in events if event.get("event_type") == "ranking_changed"]
    warnings = ["no_research_portfolio"] if not portfolio else []
    metrics = {
        "candidate_count": len(candidate_ids),
        "cluster_count": int(portfolio.get("cluster_count", len(clusters))),
        "cluster_quality": _round(statistics.fmean(cluster_confidences)) if cluster_confidences else None,
        "duplicate_group_count": len(duplicate_groups_with_members),
        "duplicate_ratio": _round(duplicate_ratio),
        "canonicalization_rate": _round(canonicalization_rate),
        "portfolio_movement": len(movements),
        "bucket_counts": dict(sorted((portfolio.get("bucket_counts") or {}).items())),
    }
    return metrics, warnings


def margin_metrics(artifact: Mapping[str, Any], events: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    margin = artifact.get("margin_intelligence")
    if not isinstance(margin, Mapping):
        margin = next((event.get("payload", {}) for event in events if event.get("event_type") == "market_pricing_computed"), {})
    margin = margin if isinstance(margin, Mapping) else {}
    economics = next((event.get("payload", {}) for event in events if event.get("event_type") == "commerce_mvp_unit_economics_estimated"), {})
    assumptions = economics.get("assumptions", []) if isinstance(economics, Mapping) else []
    assumptions = [str(item) for item in assumptions] if isinstance(assumptions, list) else []
    warnings = [str(item) for item in margin.get("warnings", []) if item]
    if not margin:
        warnings.append("no_margin_intelligence")
    metrics = {
        "observed_gross_margin": margin.get("observed_gross_margin"),
        "observed_margin_low": margin.get("observed_margin_low"),
        "observed_margin_high": margin.get("observed_margin_high"),
        "observed_pricing_confidence": margin.get("observed_pricing_confidence"),
        "observed_margin_confidence": margin.get("observed_margin_confidence"),
        "provenance": dict(sorted((margin.get("provenance") or {}).items())),
        "assumption_count": len(assumptions),
        "assumption_percentage": _round(len(assumptions) / 6) if assumptions else (0.0 if margin else None),
        "assumptions": assumptions,
    }
    return metrics, list(dict.fromkeys(warnings))


def overall_metrics(engine_metrics: Mapping[str, Mapping[str, Any]], events: list[Mapping[str, Any]]) -> tuple[dict[str, Any], list[str], list[str]]:
    supplier = engine_metrics["supplier_evidence"]
    competition = engine_metrics["competition_intelligence"]
    opportunity = engine_metrics["opportunity_scoring"]
    research = engine_metrics["research_portfolio"]
    margin = engine_metrics["margin_intelligence"]
    confidence_values = [
        supplier.get("confidence_mean"),
        opportunity.get("confidence_distribution", {}).get("mean"),
        research.get("cluster_quality"),
        margin.get("observed_margin_confidence"),
    ]
    confidence_values = [float(value) for value in confidence_values if isinstance(value, (int, float))]
    completeness_values = [supplier.get("field_observation_rate"), competition.get("pricing_coverage")]
    completeness_values = [float(value) for value in completeness_values if isinstance(value, (int, float))]
    warnings: list[str] = []
    blockers: list[str] = []
    for engine, metrics in engine_metrics.items():
        if not metrics:
            blockers.append(f"missing_{engine}")
    evidence_completeness = _round(statistics.fmean(completeness_values)) if completeness_values else 0.0
    overall_confidence = _round(statistics.fmean(confidence_values)) if confidence_values else 0.0
    if evidence_completeness < 0.5:
        warnings.append("evidence_completeness_below_50_percent")
    run_quality = "high" if evidence_completeness >= 0.75 and overall_confidence >= 0.7 else "medium" if evidence_completeness >= 0.5 else "low"
    if not events:
        run_quality = "insufficient_evidence"
        blockers.append("no_canonical_events")
    metrics = {
        "signal_count": sum(event.get("event_type") == "public_signal_observed" for event in events),
        "event_count": len(events),
        "supplier_completeness": supplier.get("field_observation_rate"),
        "competition_completeness": competition.get("pricing_coverage"),
        "overall_evidence_completeness": evidence_completeness,
        "overall_confidence": overall_confidence,
        "assumption_percentage": margin.get("assumption_percentage"),
        "run_quality": run_quality,
        "engines_measured": sum(bool(metrics) for metrics in engine_metrics.values()),
        "engine_count": len(engine_metrics),
    }
    return metrics, warnings, blockers


def source_fingerprint(artifact: Mapping[str, Any], events: Iterable[Mapping[str, Any]]) -> str:
    payload = {"artifact": artifact, "events": list(events)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
