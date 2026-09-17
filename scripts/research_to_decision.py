"""Build the existing client-safe validation report from bounded local evidence.

This is an offline/manual orchestration seam. It adapts sanitized local imports
into the repository's existing marketplace, supplier, consumer, benchmark, and
opportunity authorities; it does not add a scoring model or execution authority.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

# Allow direct ``python scripts/research_to_decision.py`` execution from any cwd.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.adapters.research.consumer_attention import (
    import_csv as import_consumer_csv,
    import_json as import_consumer_json,
)
from backend.adapters.research.marketplace_trends import (
    import_csv as import_marketplace_csv,
    import_json as import_marketplace_json,
)
from backend.adapters.research.supplier_feasibility import (
    import_csv as import_supplier_csv,
    import_json as import_supplier_json,
)
from evaluation.commerce.benchmark_matrix import BenchmarkCandidate, build_benchmark_matrix
from evaluation.commerce.consumer_attention import build_report as build_consumer_report
from evaluation.commerce.marketplace_trends import build_report as build_marketplace_report
from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis
from evaluation.commerce.product_validation_report import generate as generate_product_report
from evaluation.commerce.public_market_benchmark import (
    build_public_market_benchmark,
    load_public_market_seed,
)
from evaluation.commerce.readiness import build_phase1_readiness
from evaluation.commerce.supplier_feasibility import build_report as build_supplier_report

MAX_FILE_BYTES = 256 * 1024
MAX_MANIFEST_BYTES = 128 * 1024
MAX_RECORDS = 100
MAX_INPUT_FILES = 24
MAX_TEXT = 240
SUPPORTED_CURRENCIES = frozenset({"AUD", "CAD", "CNY", "EUR", "GBP", "JPY", "MXN", "USD"})
LIFECYCLE_STATES = frozenset({"candidate", "evidence_collected", "research_ready", "hold", "reject", "no_launch"})
OBSERVATION_KINDS = frozenset({"policy", "reviewed_url", "competition_observation", "social_observation", "catalog"})
SENSITIVE_KEY = re.compile(r"(api[_-]?key|authorization|body|cookie|header|html|password|payload|private[_-]?key|raw|secret|token|trace|log)", re.I)
SENSITIVE_VALUE = re.compile(r"(bearer\s+|sk_(?:live|test)_|gh[pousr]_?|xox[baprs]-|-----BEGIN)", re.I)


class ResearchToDecisionError(ValueError):
    """Raised when a local evidence packet cannot be accepted safely."""


def _text(value: Any, field: str, *, required: bool = False) -> str:
    result = " ".join(str(value or "").split())
    if required and not result:
        raise ResearchToDecisionError(f"{field} is required")
    if len(result) > MAX_TEXT:
        raise ResearchToDecisionError(f"{field} exceeds {MAX_TEXT} characters")
    return result


def _contains_secret(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(SENSITIVE_KEY.search(str(key)) or _contains_secret(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_secret(item) for item in value)
    return bool(SENSITIVE_VALUE.search(str(value))) if value is not None else False


def _reject_html(raw: str) -> None:
    if raw.lstrip().lower().startswith(("<", "<!doctype")):
        raise ResearchToDecisionError("HTML or raw page content is not accepted")


def _parse_timezone(value: Any, field: str) -> str:
    result = _text(value, field, required=True)
    try:
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResearchToDecisionError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ResearchToDecisionError(f"{field} must include a timezone")
    return result


def _parse_capture_time(value: Any) -> str:
    return _parse_timezone(value, "captured_at")


def _resolve(base_dir: Path, value: Any, *, label: str) -> Path:
    raw = _text(value, label, required=True)
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ResearchToDecisionError(f"{label} must remain relative to the manifest")
    resolved = (base_dir / candidate).resolve()
    if base_dir.resolve() not in resolved.parents:
        raise ResearchToDecisionError(f"{label} escapes the manifest directory")
    if not resolved.is_file():
        raise ResearchToDecisionError(f"{label} does not exist")
    return resolved


def _raw_records(path: Path) -> tuple[list[Mapping[str, Any]], str]:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ResearchToDecisionError(f"input exceeds {MAX_FILE_BYTES} bytes")
    raw_text = path.read_text(encoding="utf-8-sig")
    _reject_html(raw_text)
    if path.suffix.lower() == ".csv":
        rows = list(csv.DictReader(raw_text.splitlines()))
        return [row for row in rows if isinstance(row, Mapping)], "csv"
    try:
        value = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ResearchToDecisionError(f"malformed JSON input: {path.name}") from exc
    if _contains_secret(value):
        raise ResearchToDecisionError(f"secret-like input rejected: {path.name}")
    if isinstance(value, list):
        rows = value
    elif isinstance(value, Mapping):
        rows = next((value[key] for key in ("records", "items", "products", "offers", "results", "reviews", "comments", "ads") if isinstance(value.get(key), list)), [value])
    else:
        raise ResearchToDecisionError("JSON input must be an object or array")
    if not all(isinstance(row, Mapping) for row in rows):
        raise ResearchToDecisionError(f"input rows must be objects: {path.name}")
    return list(rows), "json"


def _candidate_id(row: Mapping[str, Any]) -> str:
    return _text(row.get("candidate_id") or row.get("product_id") or row.get("item_id") or row.get("sku"), "candidate_id")


def _validate_rows(rows: list[Mapping[str, Any]], *, label: str, role: str) -> None:
    if len(rows) > MAX_RECORDS:
        raise ResearchToDecisionError(f"{label} exceeds {MAX_RECORDS} records")
    seen: set[str] = set()
    for row in rows:
        if _contains_secret(row):
            raise ResearchToDecisionError(f"secret-like row rejected: {label}")
        candidate_id = _candidate_id(row)
        if not candidate_id:
            raise ResearchToDecisionError(f"missing candidate_id in {label}")
        discriminator = str(
            row.get("supplier_sku") or row.get("sku") or row.get("source_url") or row.get("url") or row.get("content_title") or row.get("hook") or row.get("price") or "row"
        )
        identity = f"{candidate_id}:{discriminator}" if role in {"supplier", "marketplace", "consumer_attention"} else json.dumps(row, sort_keys=True)
        if identity in seen:
            raise ResearchToDecisionError(f"duplicate evidence identity in {label}: {candidate_id}")
        seen.add(identity)


def _currency(value: Any) -> str:
    currency = _text(value, "lane.currency", required=True).upper()
    if currency not in SUPPORTED_CURRENCIES:
        raise ResearchToDecisionError(f"unsupported currency: {currency}")
    return currency


def _lane(manifest: Mapping[str, Any]) -> dict[str, str]:
    lane = manifest.get("lane")
    if not isinstance(lane, Mapping):
        raise ResearchToDecisionError("lane is required")
    origin = _text(lane.get("origin"), "lane.origin", required=True)
    destination = _text(lane.get("destination"), "lane.destination", required=True)
    if destination.lower() in {"unknown", "unsupported", "n/a", "none"}:
        raise ResearchToDecisionError("lane.destination is unsupported")
    return {"origin": origin, "destination": destination, "currency": _currency(lane.get("currency"))}


def _metadata(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    values = manifest.get("candidates", [])
    if not isinstance(values, list) or len(values) > MAX_RECORDS:
        raise ResearchToDecisionError("candidates must be a bounded list")
    result: dict[str, dict[str, Any]] = {}
    for item in values:
        if not isinstance(item, Mapping):
            raise ResearchToDecisionError("candidate metadata must be objects")
        if set(item) - {"candidate_id", "title", "category", "lifecycle_state", "target_sell_price", "retailer_penalty", "evidence_expiry"}:
            raise ResearchToDecisionError("unknown candidate metadata field")
        candidate_id = _text(item.get("candidate_id"), "candidate.candidate_id", required=True)
        if candidate_id in result:
            raise ResearchToDecisionError(f"duplicate candidate metadata: {candidate_id}")
        lifecycle = _text(item.get("lifecycle_state") or "evidence_collected", "candidate.lifecycle_state")
        if lifecycle not in LIFECYCLE_STATES:
            raise ResearchToDecisionError(f"unsupported lifecycle_state: {lifecycle}")
        expiry = item.get("evidence_expiry")
        result[candidate_id] = {
            "title": _text(item.get("title") or candidate_id, "candidate.title"),
            "category": _text(item.get("category") or "unknown", "candidate.category"),
            "lifecycle_state": lifecycle,
            "target_sell_price": item.get("target_sell_price"),
            "retailer_penalty": item.get("retailer_penalty"),
            "evidence_expiry": _parse_timezone(expiry, "candidate.evidence_expiry") if expiry else None,
        }
    return result


def _validate_manifest(manifest: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, dict[str, Any]], str]:
    if not isinstance(manifest, Mapping):
        raise ResearchToDecisionError("manifest root must be an object")
    allowed = {"captured_at", "client_name", "lane", "candidates", "supplier_inputs", "marketplace_inputs", "consumer_attention_inputs", "public_market_seed", "observation_inputs"}
    unknown = sorted(set(manifest) - allowed)
    if unknown:
        raise ResearchToDecisionError(f"unknown manifest fields: {unknown}")
    return _lane(manifest), _metadata(manifest), _parse_capture_time(manifest.get("captured_at"))


def _input_entries(manifest: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    values = manifest.get(key, [])
    if not isinstance(values, list):
        raise ResearchToDecisionError(f"{key} must be a list")
    result = []
    for item in values:
        if not isinstance(item, Mapping):
            raise ResearchToDecisionError(f"{key} entries must be objects")
        if set(item) - {"path", "label", "supplier", "source_type", "marketplace", "platform", "kind", "candidate_ids"}:
            raise ResearchToDecisionError(f"unknown fields in {key} entry")
        if "candidate_ids" in item and (not isinstance(item["candidate_ids"], list) or not all(isinstance(value, str) and value for value in item["candidate_ids"])):
            raise ResearchToDecisionError(f"{key}.candidate_ids must be a list of strings")
        result.append(item)
    return result


def _check_lane(records: list[Any], lane: Mapping[str, str], *, label: str) -> list[str]:
    warnings: list[str] = []
    for record in records:
        currency = str(getattr(record, "currency", "") or "").upper()
        if currency and currency != lane["currency"]:
            raise ResearchToDecisionError(f"currency mismatch in {label}: {currency} != {lane['currency']}")
        destination = str(getattr(record, "destination_region", "") or "").strip()
        if destination and destination.lower() != lane["destination"].lower():
            raise ResearchToDecisionError(f"destination mismatch in {label}: {destination}")
        if not destination and hasattr(record, "destination_region"):
            warnings.append(f"destination_missing:{label}")
        source_url = str(getattr(record, "source_url", "") or "")
        if source_url:
            parsed = urlparse(source_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
                raise ResearchToDecisionError(f"unsafe source_url in {label}")
    return sorted(set(warnings))


def _check_record_conflicts(records: list[Any], role: str, seen: dict[tuple[str, ...], str]) -> None:
    for record in records:
        candidate_id = str(getattr(record, "candidate_id", ""))
        if role == "supplier":
            key = (role, candidate_id, str(getattr(record, "supplier", "")), str(getattr(record, "supplier_product_id", "") or getattr(record, "source_url", "")))
            value = json.dumps({"unit_cost": getattr(record, "unit_cost", None), "shipping_cost": getattr(record, "shipping_cost", None), "currency": getattr(record, "currency", ""), "destination": getattr(record, "destination_region", "")}, sort_keys=True)
        elif role == "marketplace":
            key = (role, candidate_id, str(getattr(record, "marketplace", "")), str(getattr(record, "source_type", "")), str(getattr(record, "source_url", "")))
            value = json.dumps({"price": getattr(record, "price", None), "currency": getattr(record, "currency", ""), "availability": getattr(record, "availability", "")}, sort_keys=True)
        else:
            key = (role, candidate_id, str(getattr(record, "platform", "")), str(getattr(record, "source", "")), str(getattr(record, "content_title", "") or getattr(record, "hook", "")))
            value = json.dumps({"content": getattr(record, "content_text_excerpt", ""), "objection": getattr(record, "objection", "")}, sort_keys=True)
        previous = seen.get(key)
        if previous is not None and previous != value:
            raise ResearchToDecisionError(f"conflicting duplicate evidence: {candidate_id}")
        seen[key] = value


def _load_import(path: Path, entry: Mapping[str, Any], role: str) -> tuple[list[Any], dict[str, Any]]:
    rows, fmt = _raw_records(path)
    label = _text(entry.get("label") or path.name, f"{role}.label")
    _validate_rows(rows, label=label, role=role)
    if role == "supplier":
        supplier = _text(entry.get("supplier") or ("manual" if fmt == "csv" else "cj"), "supplier")
        source_type = _text(entry.get("source_type") or ("manual_csv_import" if fmt == "csv" else "fixture_demo"), "source_type")
        records = import_supplier_csv(path, supplier=supplier, source_type=source_type) if fmt == "csv" else import_supplier_json(path, supplier=supplier, source_type=source_type)
    elif role == "marketplace":
        marketplace = _text(entry.get("marketplace") or "amazon", "marketplace")
        records = import_marketplace_csv(path, marketplace=marketplace) if fmt == "csv" else import_marketplace_json(path, marketplace=marketplace, source_type=entry.get("source_type"))
    elif role == "consumer_attention":
        platform = _text(entry.get("platform") or ("manual" if fmt == "csv" else "manual"), "platform")
        source_type = _text(entry.get("source_type") or ("manual_csv_import" if fmt == "csv" else "fixture_demo"), "source_type")
        records = import_consumer_csv(path, platform=platform, source_type=source_type) if fmt == "csv" else import_consumer_json(path, platform=platform, source_type=source_type)
    else:
        raise ResearchToDecisionError(f"unsupported import role: {role}")
    selected = set(entry.get("candidate_ids", []))
    if selected:
        records = [record for record in records if getattr(record, "candidate_id", "") in selected]
    return records, {"label": label, "role": role, "format": fmt, "records_seen": len(rows), "records_accepted": len(records), "status": "accepted" if records else "needs_evidence"}


def _load_observation(path: Path, entry: Mapping[str, Any]) -> dict[str, Any]:
    kind = _text(entry.get("kind"), "observation.kind", required=True)
    if kind not in OBSERVATION_KINDS:
        raise ResearchToDecisionError(f"unsupported observation kind: {kind}")
    rows, fmt = _raw_records(path)
    label = _text(entry.get("label") or path.name, "observation.label")
    _validate_rows(rows, label=label, role="observation")
    for row in rows:
        url = row.get("url") or row.get("source_url")
        if kind == "reviewed_url" and (not isinstance(url, str) or urlparse(url).scheme not in {"http", "https"} or not urlparse(url).netloc):
            raise ResearchToDecisionError(f"reviewed_url requires an http(s) URL: {label}")
    return {"label": label, "role": "observation", "kind": kind, "format": fmt, "records_seen": len(rows), "records_accepted": len(rows), "status": "accepted"}


def _best(mapping: Mapping[str, Any], candidate_id: str) -> Mapping[str, Any]:
    return next((item for item in mapping.get("candidates", []) if item.get("candidate_id") == candidate_id), {})


def _benchmark_candidates(
    candidate_ids: set[str], metadata: Mapping[str, Mapping[str, Any]], marketplace: Mapping[str, Any], supplier: Mapping[str, Any], lane: Mapping[str, str]
) -> list[BenchmarkCandidate]:
    values: list[BenchmarkCandidate] = []
    for candidate_id in sorted(candidate_ids):
        market = _best(marketplace, candidate_id)
        supplier_item = _best(supplier, candidate_id)
        market_score = market.get("score", {})
        supplier_score = supplier_item.get("score", {})
        offers = supplier_item.get("offers", [])
        market_evidence = market.get("evidence", [])
        observed_fields = []
        if offers:
            first = offers[0]
            observed_fields = [
                name for name, value in (("price", first.get("unit_cost")), ("sku", first.get("supplier_sku")), ("inventory", first.get("inventory_status")), ("variant", first.get("variant_count")), ("shipping", first.get("shipping_cost")), ("delivery", first.get("delivery_max_days"))) if value not in (None, "")
            ]
        economics = supplier_score.get("economics") or {}
        assumptions = sorted({name for name in ("price", "sku", "inventory", "variant", "shipping", "delivery") if name not in observed_fields})
        meta = metadata.get(candidate_id, {})
        values.append(BenchmarkCandidate(
            candidate_id=candidate_id,
            title=str(meta.get("title") or market.get("query") or supplier_item.get("query") or candidate_id),
            query=str(market.get("query") or supplier_item.get("query") or candidate_id),
            category=str(meta.get("category") or "unknown"),
            source="manual_import",
            supplier_evidence={"source_type": (offers[0].get("source_type") if offers else "unavailable"), "observed_fields": observed_fields, "confidence": supplier_score.get("overall_supplier_feasibility", 0.0), "credential_status": "not_configured"},
            competition_evidence={"observed_offers": len(market_evidence), "pricing_coverage": market.get("score", {}).get("price_confidence", 0.0), "sources": sorted({item.get("marketplace", "") for item in market_evidence if item.get("marketplace")}), "availability_observed": any(item.get("availability") for item in market_evidence), "reviews_observed": any(item.get("review_count") is not None for item in market_evidence), "confidence": market_score.get("overall_marketplace_opportunity", 0.0)},
            opportunity_score=market_score.get("overall_marketplace_opportunity", 0.0),
            commerce_run={"gross_margin": (float(economics["gross_margin_percent"]) / 100 if economics.get("gross_margin_percent") is not None else None), "assumption_ratio": len(assumptions) / 6},
            assumptions=tuple(assumptions),
            warnings=(f"lane_currency:{lane['currency']}",),
        ))
    return values


def _candidate_audit(candidate_ids: set[str], metadata: Mapping[str, Mapping[str, Any]], marketplace: Mapping[str, Any], supplier: Mapping[str, Any], synthesis: Mapping[str, Any], lane: Mapping[str, str]) -> list[dict[str, Any]]:
    rows = []
    synthesis_items = {item.get("candidate_id"): item for item in synthesis.get("candidates", [])}
    for candidate_id in sorted(candidate_ids):
        supplier_item = _best(supplier, candidate_id)
        market_item = _best(marketplace, candidate_id)
        supplier_score = supplier_item.get("score", {})
        market_score = market_item.get("score", {})
        meta = metadata.get(candidate_id, {})
        rows.append({
            "candidate_id": candidate_id,
            "lifecycle_state": meta.get("lifecycle_state", "evidence_collected"),
            "evidence_expiry": meta.get("evidence_expiry"),
            "lane": {"destination": lane["destination"], "currency": lane["currency"]},
            "economics": supplier_score.get("economics") or {},
            "assumptions": sorted({*supplier_score.get("reasons", []), *market_score.get("reasons", [])}),
            "missing_evidence": sorted({item for item in (supplier_score.get("reasons", []) + market_score.get("reasons", [])) if "missing" in item or "unknown" in item or "unavailable" in item}),
            "confidence": {"supplier": supplier_score.get("overall_supplier_feasibility", 0.0), "marketplace": market_score.get("overall_marketplace_opportunity", 0.0)},
            "action": (synthesis_items.get(candidate_id) or {}).get("next_best_action", "hold_for_manual_review"),
            "retailer_penalty": meta.get("retailer_penalty"),
            "comparability": "comparable" if market_item and supplier_item else "incomplete",
        })
    return rows


def build_research_to_decision(manifest: Mapping[str, Any], *, base_dir: str | Path) -> dict[str, Any]:
    lane, metadata, captured_at = _validate_manifest(manifest)
    base = Path(base_dir).resolve()
    entries_total = sum(len(manifest.get(key, []) or []) for key in ("supplier_inputs", "marketplace_inputs", "consumer_attention_inputs", "observation_inputs")) + (1 if manifest.get("public_market_seed") else 0)
    if entries_total > MAX_INPUT_FILES:
        raise ResearchToDecisionError(f"manifest exceeds {MAX_INPUT_FILES} input files")
    supplier_records: list[Any] = []
    marketplace_records: list[Any] = []
    consumer_records: list[Any] = []
    seen_records: dict[tuple[str, ...], str] = {}
    input_audit: list[dict[str, Any]] = []
    warnings: list[str] = []
    candidate_ids = set(metadata)
    for key, role, destination in (("supplier_inputs", "supplier", supplier_records), ("marketplace_inputs", "marketplace", marketplace_records), ("consumer_attention_inputs", "consumer_attention", consumer_records)):
        for entry in _input_entries(manifest, key):
            path = _resolve(base, entry.get("path"), label=f"{key}.path")
            records, audit = _load_import(path, entry, role)
            destination.extend(records)
            _check_record_conflicts(records, role, seen_records)
            candidate_ids.update(getattr(record, "candidate_id", "") for record in records)
            input_audit.append(audit)
            if not records:
                warnings.append(f"no_accepted_records:{audit['label']}")
            if role in {"supplier", "marketplace", "consumer_attention"}:
                warnings.extend(_check_lane(records, lane, label=audit["label"]))
    for entry in _input_entries(manifest, "observation_inputs"):
        input_audit.append(_load_observation(_resolve(base, entry.get("path"), label="observation_inputs.path"), entry))

    public_market_report: dict[str, Any] = {}
    if manifest.get("public_market_seed"):
        path = _resolve(base, manifest.get("public_market_seed"), label="public_market_seed")
        rows, _ = _raw_records(path)
        if len(rows) > MAX_RECORDS:
            raise ResearchToDecisionError("public_market_seed exceeds the record cap")
        candidates, seed_warnings = load_public_market_seed(path)
        public_market_report = build_public_market_benchmark(candidates, allow_network=False).to_dict()
        warnings.extend(seed_warnings)
        input_audit.append({"label": path.name, "role": "public_market_seed", "format": "json", "records_seen": len(candidates), "records_accepted": len(candidates), "status": "accepted" if candidates else "needs_evidence"})

    supplier_report = build_supplier_report(supplier_records, evidence_mode="manual_import", target_sell_prices={key: value.get("target_sell_price") for key, value in metadata.items() if value.get("target_sell_price") is not None}).to_dict()
    marketplace_report = build_marketplace_report(marketplace_records, evidence_mode="manual_import").to_dict()
    consumer_report = build_consumer_report(consumer_records, evidence_mode="manual_import", supplier_proof_by_candidate={key: bool(_best(supplier_report, key)) for key in candidate_ids}).to_dict()
    benchmark_candidates = _benchmark_candidates(candidate_ids, metadata, marketplace_report, supplier_report, lane)
    benchmark_report = build_benchmark_matrix(candidates=benchmark_candidates).to_dict()
    synthesis_report = build_product_opportunity_synthesis(marketplace_report, supplier_report, consumer_report).to_dict()
    readiness_report = build_phase1_readiness(benchmark_report=benchmark_report, public_market_benchmark_report=public_market_report, generated_at="deterministic", environ={}).to_dict()
    report = generate_product_report(
        client_name=_text(manifest.get("client_name") or "", "client_name"),
        benchmark=benchmark_report,
        public_market=public_market_report,
        readiness=readiness_report,
        marketplace_trends=marketplace_report,
        supplier_feasibility=supplier_report,
        consumer_attention=consumer_report,
        opportunity_synthesis=synthesis_report,
    ).to_dict()
    validation_warnings = sorted(set(warnings + ["manual_evidence_is_not_live_supplier_proof", "no_launch_or_spend_authority"]))
    if not supplier_records:
        validation_warnings.append("supplier_evidence_missing")
    if not marketplace_records:
        validation_warnings.append("marketplace_evidence_missing")
    if not consumer_records:
        validation_warnings.append("consumer_attention_evidence_missing")
    if report.get("overall_recommendation") == "advance_to_launch_draft":
        report["overall_recommendation"] = "hold_for_manual_review"
        validation_warnings.append("manual_evidence_cannot_authorize_launch")
    appendix = {
        "research_to_decision_version": "v1",
        "captured_at": captured_at,
        "lane": lane,
        "input_audit": sorted(input_audit, key=lambda item: (item["role"], item["label"])),
        "validation": {"status": "hold_for_manual_review" if validation_warnings else "ready_for_operator_review", "warnings": sorted(set(validation_warnings)), "read_only": True, "network_calls": False, "credentials_used": False, "provider_calls": False, "orders_or_spend": False},
        "candidate_audit": _candidate_audit(candidate_ids, metadata, marketplace_report, supplier_report, synthesis_report, lane),
        "source_authorities": {"supplier": "evaluation.commerce.supplier_feasibility", "marketplace": "evaluation.commerce.marketplace_trends", "consumer_attention": "evaluation.commerce.consumer_attention", "synthesis": "evaluation.commerce.opportunity_synthesis", "packet": "evaluation.commerce.product_validation_report"},
    }
    fingerprint_input = {"report": report, "appendix": appendix}
    appendix["replay_fingerprint"] = hashlib.sha256(json.dumps(fingerprint_input, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    report["appendix"] = appendix
    report["source_reports"] = {**report.get("source_reports", {}), "research_to_decision": "supplied"}
    report["overall_recommendation"] = "hold_for_manual_review" if validation_warnings else report.get("overall_recommendation", "hold_for_manual_review")
    return report


def load_manifest(path: str | Path) -> tuple[dict[str, Any], Path]:
    candidate = Path(path)
    if candidate.stat().st_size > MAX_MANIFEST_BYTES:
        raise ResearchToDecisionError(f"manifest exceeds {MAX_MANIFEST_BYTES} bytes")
    raw = candidate.read_text(encoding="utf-8")
    _reject_html(raw)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ResearchToDecisionError("malformed manifest JSON") from exc
    if _contains_secret(value):
        raise ResearchToDecisionError("secret-like manifest rejected")
    if not isinstance(value, Mapping):
        raise ResearchToDecisionError("manifest root must be an object")
    return dict(value), candidate.resolve().parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="relative-input manifest JSON")
    parser.add_argument("--json", action="store_true", help="emit the existing report as JSON")
    parser.add_argument("--output", help="optional output file; no file is written by default")
    args = parser.parse_args(argv)
    try:
        manifest, base_dir = load_manifest(args.manifest)
        report = build_research_to_decision(manifest, base_dir=base_dir)
    except (OSError, ResearchToDecisionError) as exc:
        print(json.dumps({"status": "rejected", "error": str(exc)}, sort_keys=True))
        return 2
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n" if args.json else json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        target = Path(args.output)
        target.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
