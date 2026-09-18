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
OFFER_APPROVAL_STATES = (
    "candidate",
    "contacted",
    "information_received",
    "quote_verified",
    "terms_verified",
    "sample_ordered",
    "sample_passed",
    "direct_ship_tested",
    "RMA_tested",
    "approved",
    "suspended",
    "rejected",
)
EVIDENCE_STATES = frozenset({"observed", "manual", "fixture", "assumed", "unavailable", "malformed", "blocked"})
OBSERVATION_KINDS = frozenset({"policy", "reviewed_url", "competition_observation", "social_observation", "catalog", "pdf_derived", "form"})
MARKET_LANE_FIELDS = (
    "origin_country",
    "ship_from_country",
    "warehouse",
    "destination_country",
    "destination_state_region",
    "postal_code_assumption",
    "currency",
    "tax_model",
    "duty_model",
    "brokerage_model",
    "shipping_model",
    "return_destination",
    "return_cost_payer",
    "payment_method",
    "compliance_requirements",
    "customer_support_language",
    "marketplace_eligibility",
    "delivery_promise",
    "evidence_state",
    "confidence",
)
OFFER_FIELDS = frozenset(
    {
        "offer_id",
        "supplier_offer_id",
        "candidate_id",
        "supplier",
        "supplier_product_id",
        "supplier_sku",
        "sku",
        "variant",
        "unit_cost",
        "price",
        "currency",
        "price_valid_until",
        "valid_until",
        "inventory_status",
        "inventory_quantity",
        "stock",
        "warehouse_region",
        "warehouse",
        "destination_region",
        "destination_country",
        "delivery_min_days",
        "delivery_max_days",
        "p50_delivery_days",
        "p95_delivery_days",
        "tracking_available",
        "tracking",
        "blind_shipping",
        "packaging",
        "return_address",
        "return_cost_payer",
        "warranty",
        "rma_process",
        "refund_sla_days",
        "support_owner",
        "support_response_sla_hours",
        "dropshipping_permission",
        "marketplace_permission",
        "sample_state",
        "contract_evidence",
        "policy_evidence",
        "backup_supplier",
        "approval_state",
        "evidence_state",
        "source_type",
        "source",
        "source_url",
        "source_reference",
        "document_reference",
        "extraction_method",
        "captured_at",
        "observed_at",
        "expires_at",
        "source_confidence",
        "confidence",
        "query",
        "supplier_title",
        "supplier_brand",
        "variant_count",
        "moq",
        "shipping_cost",
        "estimated_landed_cost",
        "fulfillment_method",
        "field_provenance",
        "warnings",
    }
)
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


def _reference_text(value: Any, field: str, *, required: bool = True, allow_url_query: bool = False) -> str:
    reference = _text(value, field, required=required)
    if not reference:
        return reference
    parsed = urlparse(reference)
    if parsed.scheme in {"http", "https"}:
        if not parsed.netloc or parsed.username or parsed.password:
            raise ResearchToDecisionError(f"{field} must be a safe reference")
        if (parsed.query or parsed.fragment) and not allow_url_query:
            raise ResearchToDecisionError(f"{field} must not contain a query or fragment")
        if allow_url_query:
            reference = parsed._replace(query="", fragment="").geturl()
    elif parsed.scheme:
        if "://" in reference or parsed.scheme not in {"fixture", "file", "manual"}:
            raise ResearchToDecisionError(f"{field} must be a safe reference")
    path = Path(parsed.path or reference)
    if path.is_absolute() or ".." in path.parts or any(char in reference for char in "<>\r\n"):
        raise ResearchToDecisionError(f"{field} must be a safe reference")
    return reference


def _evidence_reference(value: Any, field: str, *, allow_url_query: bool = False) -> str:
    reference = _reference_text(value, field, allow_url_query=allow_url_query)
    return f"evidence:{hashlib.sha256(reference.encode('utf-8')).hexdigest()[:16]}"


def _warning_values(value: Any, field: str) -> list[str]:
    if value in (None, ""):
        return []
    values = value if isinstance(value, list) else [value]
    if not all(isinstance(item, str) for item in values):
        raise ResearchToDecisionError(f"{field} must be a bounded list of strings")
    if len(values) > 12:
        raise ResearchToDecisionError(f"{field} has too many entries")
    return sorted({_text(item, field, required=True) for item in values})


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


def _number(value: Any, field: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ResearchToDecisionError(f"{field} must be numeric") from exc
    if minimum is not None and result < minimum or maximum is not None and result > maximum:
        raise ResearchToDecisionError(f"{field} is outside its allowed range")
    return result


def _text_list(value: Any, field: str, *, required: bool = False) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        values = []
    if required and not values:
        raise ResearchToDecisionError(f"{field} is required")
    if len(values) > 12 or not all(isinstance(item, str) for item in values):
        raise ResearchToDecisionError(f"{field} must be a bounded list of strings")
    return [_text(item, field) for item in values]


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


def _lane(manifest: Mapping[str, Any]) -> dict[str, Any]:
    lane = manifest.get("lane")
    if not isinstance(lane, Mapping):
        raise ResearchToDecisionError("lane is required")
    missing = [field for field in MARKET_LANE_FIELDS if field not in lane]
    if missing:
        raise ResearchToDecisionError(f"lane is missing required fields: {', '.join(missing)}")
    destination = _text(lane.get("destination_country"), "lane.destination_country", required=True)
    if destination.lower() in {"unknown", "unsupported", "n/a", "none"}:
        raise ResearchToDecisionError("lane.destination is unsupported")
    evidence_state = _text(lane.get("evidence_state"), "lane.evidence_state", required=True)
    if evidence_state not in EVIDENCE_STATES:
        raise ResearchToDecisionError(f"unsupported lane evidence_state: {evidence_state}")
    result: dict[str, Any] = {
        "origin_country": _text(lane.get("origin_country"), "lane.origin_country", required=True),
        "ship_from_country": _text(lane.get("ship_from_country"), "lane.ship_from_country", required=True),
        "warehouse": _text(lane.get("warehouse"), "lane.warehouse", required=True),
        "destination_country": destination,
        "destination_state_region": _text(lane.get("destination_state_region"), "lane.destination_state_region", required=True),
        "postal_code_assumption": _text(lane.get("postal_code_assumption"), "lane.postal_code_assumption", required=True),
        "currency": _currency(lane.get("currency")),
        "tax_model": _text(lane.get("tax_model"), "lane.tax_model", required=True),
        "duty_model": _text(lane.get("duty_model"), "lane.duty_model", required=True),
        "brokerage_model": _text(lane.get("brokerage_model"), "lane.brokerage_model", required=True),
        "shipping_model": _text(lane.get("shipping_model"), "lane.shipping_model", required=True),
        "return_destination": _text(lane.get("return_destination"), "lane.return_destination", required=True),
        "return_cost_payer": _text(lane.get("return_cost_payer"), "lane.return_cost_payer", required=True),
        "payment_method": _text(lane.get("payment_method"), "lane.payment_method", required=True),
        "compliance_requirements": _text_list(lane.get("compliance_requirements"), "lane.compliance_requirements", required=True),
        "customer_support_language": _text_list(lane.get("customer_support_language"), "lane.customer_support_language", required=True),
        "marketplace_eligibility": _text_list(lane.get("marketplace_eligibility"), "lane.marketplace_eligibility", required=True),
        "delivery_promise": _text(lane.get("delivery_promise"), "lane.delivery_promise", required=True),
        "evidence_state": evidence_state,
        "confidence": _number(lane.get("confidence"), "lane.confidence", minimum=0.0, maximum=1.0),
    }
    return result


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
        if set(item) - {"path", "label", "supplier", "source_type", "marketplace", "platform", "kind", "candidate_ids", "source_reference", "extraction_method", "warnings"}:
            raise ResearchToDecisionError(f"unknown fields in {key} entry")
        if "candidate_ids" in item and (not isinstance(item["candidate_ids"], list) or not all(isinstance(value, str) and value for value in item["candidate_ids"])):
            raise ResearchToDecisionError(f"{key}.candidate_ids must be a list of strings")
        if "source_reference" in item:
            _reference_text(item["source_reference"], f"{key}.source_reference")
        if "extraction_method" in item:
            _text(item["extraction_method"], f"{key}.extraction_method", required=True)
        _warning_values(item.get("warnings"), f"{key}.warnings")
        result.append(item)
    return result


def _check_lane(records: list[Any], lane: Mapping[str, Any], *, label: str) -> list[str]:
    warnings: list[str] = []
    for record in records:
        currency = str(getattr(record, "currency", "") or "").upper()
        if currency and currency != lane["currency"]:
            raise ResearchToDecisionError(f"currency mismatch in {label}: {currency} != {lane['currency']}")
        destination = str(getattr(record, "destination_region", "") or "").strip()
        if destination and destination.lower() != lane["destination_country"].lower():
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


def _row_value(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def _offer_text(row: Mapping[str, Any], names: tuple[str, ...], field: str, issues: list[str]) -> str:
    value = _row_value(row, *names)
    if value in (None, ""):
        issues.append(f"{field}_missing")
        return "unknown"
    return _text(value, f"supplier_offer.{field}")


def _offer_number(row: Mapping[str, Any], names: tuple[str, ...], field: str, issues: list[str]) -> float | None:
    value = _row_value(row, *names)
    if value in (None, ""):
        issues.append(f"{field}_missing")
        return None
    if isinstance(value, str) and value.strip().lower() in {"unknown", "unavailable", "n/a", "none"}:
        issues.append(f"{field}_unknown")
        return None
    return _number(value, f"supplier_offer.{field}", minimum=0.0)


def _normalize_supplier_offer(
    row: Mapping[str, Any],
    *,
    lane: Mapping[str, Any],
    captured_at: str,
    source_label: str,
    source_reference: Any = None,
    extraction_method: Any = None,
    input_warnings: Any = None,
) -> dict[str, Any]:
    candidate_id = _text(row.get("candidate_id"), "supplier_offer.candidate_id", required=True)
    offer_id = _row_value(row, "offer_id", "supplier_offer_id", "supplier_product_id")
    exact_sku = _row_value(row, "supplier_sku", "sku")
    if not offer_id or not exact_sku:
        raise ResearchToDecisionError("supplier offer identity requires offer_id and exact supplier_sku")
    malformed_nested = [key for key, value in row.items() if key in OFFER_FIELDS - {"field_provenance", "warnings"} and isinstance(value, (Mapping, list, tuple))]
    if malformed_nested:
        raise ResearchToDecisionError(f"malformed nested supplier offer fields: {', '.join(sorted(malformed_nested))}")
    issues: list[str] = []
    currency = _currency(_row_value(row, "currency", "price_currency"))
    if currency != lane["currency"]:
        raise ResearchToDecisionError(f"currency mismatch in supplier offer: {currency} != {lane['currency']}")
    destination = _offer_text(row, ("destination_region", "destination_country", "destination"), "destination", issues)
    if destination != "unknown" and destination.lower() != lane["destination_country"].lower():
        raise ResearchToDecisionError(f"destination mismatch in supplier offer: {destination}")
    observed_at = _parse_timezone(_row_value(row, "captured_at", "observed_at") or captured_at, "supplier_offer.captured_at")
    expires_value = _row_value(row, "price_valid_until", "valid_until", "expires_at")
    expires_at = _parse_timezone(expires_value, "supplier_offer.expires_at") if expires_value else None
    if expires_at and datetime.fromisoformat(expires_at.replace("Z", "+00:00")) < datetime.fromisoformat(observed_at.replace("Z", "+00:00")):
        issues.append("offer_expired")
    source = _offer_text(row, ("source_type", "source"), "source", issues) or source_label
    reference_value = _row_value(row, "source_reference", "document_reference") or source_reference or source_label
    reference_id = _evidence_reference(reference_value, "supplier_offer.source_reference")
    method_value = _row_value(row, "extraction_method") or extraction_method or "manual_import"
    method = _text(method_value, "supplier_offer.extraction_method", required=True)
    evidence_warnings = _warning_values(_row_value(row, "warnings") or input_warnings, "supplier_offer.warnings")
    evidence_state = _offer_text(row, ("evidence_state",), "evidence_state", issues)
    if evidence_state != "unknown" and evidence_state not in EVIDENCE_STATES:
        raise ResearchToDecisionError(f"unsupported supplier offer evidence_state: {evidence_state}")
    confidence_value = _row_value(row, "confidence", "source_confidence")
    confidence = 0.0 if confidence_value in (None, "") else _number(confidence_value, "supplier_offer.confidence", minimum=0.0, maximum=1.0)
    if confidence_value in (None, ""):
        issues.append("confidence_missing")
    price = _offer_number(row, ("unit_cost", "price", "supplier_price"), "price", issues)
    shipping_cost = _offer_number(row, ("shipping_cost", "shipping"), "shipping_cost", issues)
    inventory = _offer_text(row, ("inventory_status", "stock_status", "availability"), "stock", issues)
    p50 = _offer_number(row, ("p50_delivery_days", "delivery_min_days", "min_delivery_days"), "p50_delivery_days", issues)
    p95 = _offer_number(row, ("p95_delivery_days", "delivery_max_days", "max_delivery_days"), "p95_delivery_days", issues)
    approval_state = _offer_text(row, ("approval_state",), "approval_state", issues)
    if approval_state != "unknown" and approval_state not in OFFER_APPROVAL_STATES:
        raise ResearchToDecisionError(f"unsupported supplier offer approval_state: {approval_state}")
    offer = {
        "offer_id": _text(offer_id, "supplier_offer.offer_id", required=True),
        "candidate_id": candidate_id,
        "supplier": _offer_text(row, ("supplier", "provider"), "supplier", issues),
        "exact_sku": _text(exact_sku, "supplier_offer.exact_sku", required=True),
        "variant": _offer_text(row, ("variant", "variant_name"), "variant", issues),
        "price": {"amount": price, "currency": currency, "valid_until": expires_at},
        "shipping": {"cost": shipping_cost, "model": lane["shipping_model"]},
        "stock": {"status": inventory, "quantity": _row_value(row, "inventory_quantity", "stock")},
        "warehouse": _offer_text(row, ("warehouse_region", "warehouse"), "warehouse", issues),
        "destination": destination,
        "delivery": {"p50_days": p50, "p95_days": p95},
        "tracking": _offer_text(row, ("tracking_available", "tracking"), "tracking", issues),
        "blind_shipping": _offer_text(row, ("blind_shipping",), "blind_shipping", issues),
        "packaging": _offer_text(row, ("packaging",), "packaging", issues),
        "returns": {"address": _offer_text(row, ("return_address",), "return_address", issues), "cost_payer": _offer_text(row, ("return_cost_payer",), "return_cost_payer", issues)},
        "warranty": _offer_text(row, ("warranty",), "warranty", issues),
        "rma": _offer_text(row, ("rma_process", "rma"), "rma", issues),
        "refund_sla_days": _offer_number(row, ("refund_sla_days",), "refund_sla_days", issues),
        "support": {"owner": _offer_text(row, ("support_owner",), "support_owner", issues), "response_sla_hours": _offer_number(row, ("support_response_sla_hours",), "support_response_sla_hours", issues)},
        "permissions": {"dropshipping": _offer_text(row, ("dropshipping_permission",), "dropshipping_permission", issues), "marketplace": _offer_text(row, ("marketplace_permission",), "marketplace_permission", issues)},
        "sample_state": _offer_text(row, ("sample_state",), "sample_state", issues),
        "terms_evidence": _offer_text(row, ("contract_evidence", "terms_evidence"), "terms_evidence", issues),
        "policy_evidence": _offer_text(row, ("policy_evidence",), "policy_evidence", issues),
        "backup_supplier": _offer_text(row, ("backup_supplier",), "backup_supplier", issues),
        "approval_state": approval_state,
        "evidence": {"captured_at": observed_at, "expires_at": expires_at, "source": source, "reference_id": reference_id, "extraction_method": method, "state": evidence_state, "confidence": confidence, "warnings": evidence_warnings},
        "unknown_fields": sorted(set(row) - OFFER_FIELDS),
    }
    if approval_state == "approved" and any(offer[key] in {"unknown", None} for key in ("sample_state", "rma")):
        issues.append("approval_not_earned")
        offer["approval_state"] = "candidate"
    offer["status"] = "quarantined" if issues else "accepted"
    offer["issues"] = sorted(set(issues))
    return offer


def _load_import(path: Path, entry: Mapping[str, Any], role: str, *, lane: Mapping[str, Any], captured_at: str) -> tuple[list[Any], dict[str, Any]]:
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
    supplier_offers = []
    if role == "supplier":
        supplier_offers = [
            _normalize_supplier_offer(
                row,
                lane=lane,
                captured_at=captured_at,
                source_label=label,
                source_reference=entry.get("source_reference") or path.name,
                extraction_method=entry.get("extraction_method") or ("manual_csv_import" if fmt == "csv" else "manual_json_import"),
                input_warnings=entry.get("warnings"),
            )
            for row in rows
        ]
    selected = set(entry.get("candidate_ids", []))
    if selected:
        records = [record for record in records if getattr(record, "candidate_id", "") in selected]
        supplier_offers = [offer for offer in supplier_offers if offer["candidate_id"] in selected]
    selected_rows = rows if not selected else [row for row in rows if _candidate_id(row) in selected]
    candidate_evidence_refs: dict[str, list[str]] = {}
    if role == "supplier":
        for offer in supplier_offers:
            candidate_evidence_refs.setdefault(offer["candidate_id"], []).append(offer["evidence"]["reference_id"])
    else:
        default_reference = entry.get("source_reference") or path.name
        for row in selected_rows:
            candidate_id = _candidate_id(row)
            reference_value = row.get("source_reference") or row.get("document_reference") or row.get("source_url") or row.get("url") or default_reference
            reference_id = _evidence_reference(reference_value, f"{role}.source_reference", allow_url_query=bool(row.get("source_url") or row.get("url")))
            candidate_evidence_refs.setdefault(candidate_id, []).append(reference_id)
    return records, {
        "label": label,
        "role": role,
        "format": fmt,
        "records_seen": len(rows),
        "records_accepted": len(records),
        "supplier_offers_seen": len(supplier_offers),
        "supplier_offers_accepted": sum(offer["status"] == "accepted" for offer in supplier_offers),
        "supplier_offers_quarantined": sum(offer["status"] == "quarantined" for offer in supplier_offers),
        "supplier_offer_issues": sorted({issue for offer in supplier_offers for issue in offer["issues"]}),
        "supplier_offers": supplier_offers,
        "evidence_refs": sorted({ref for refs in candidate_evidence_refs.values() for ref in refs}),
        "extraction_methods": sorted({entry.get("extraction_method") or ("manual_csv_import" if fmt == "csv" else f"manual_{role}_import")}),
        "warnings": _warning_values(entry.get("warnings"), f"{role}.warnings"),
        "candidate_evidence_refs": {key: sorted(set(value)) for key, value in sorted(candidate_evidence_refs.items())},
        "status": "accepted" if records else "needs_evidence",
    }


def _load_observation(path: Path, entry: Mapping[str, Any]) -> dict[str, Any]:
    kind = _text(entry.get("kind"), "observation.kind", required=True)
    if kind not in OBSERVATION_KINDS:
        raise ResearchToDecisionError(f"unsupported observation kind: {kind}")
    rows, fmt = _raw_records(path)
    label = _text(entry.get("label") or path.name, "observation.label")
    _validate_rows(rows, label=label, role="observation")
    evidence_refs: set[str] = set()
    extraction_methods: set[str] = set()
    warnings: set[str] = set(_warning_values(entry.get("warnings"), "observation.warnings"))
    candidate_evidence_refs: dict[str, list[str]] = {}
    for row in rows:
        url = row.get("url") or row.get("source_url")
        if kind == "reviewed_url" and (not isinstance(url, str) or urlparse(url).scheme not in {"http", "https"} or not urlparse(url).netloc):
            raise ResearchToDecisionError(f"reviewed_url requires an http(s) URL: {label}")
        reference_value = row.get("source_reference") or row.get("document_reference") or (url if kind == "reviewed_url" else row.get("source")) or entry.get("source_reference") or label
        reference_id = _evidence_reference(reference_value, f"{kind}.source_reference", allow_url_query=kind == "reviewed_url")
        method = _text(row.get("extraction_method") or entry.get("extraction_method") or ("operator_reviewed_url" if kind == "reviewed_url" else "manual_document_review"), f"{kind}.extraction_method", required=True)
        row_warnings = _warning_values(row.get("warnings") or entry.get("warnings"), f"{kind}.warnings")
        warnings.update(row_warnings)
        evidence_refs.add(reference_id)
        extraction_methods.add(method)
        candidate_evidence_refs.setdefault(_candidate_id(row), []).append(reference_id)
        if kind in {"pdf_derived", "form"}:
            required = ("source", "captured_at", "expires_at", "evidence_state", "confidence", "terms", "returns", "warranty", "support", "delivery", "permissions")
            missing = [field for field in required if row.get(field) in (None, "")]
            if missing:
                raise ResearchToDecisionError(f"{kind} evidence is missing required fields: {', '.join(missing)}")
            _parse_timezone(row.get("captured_at"), f"{kind}.captured_at")
            _parse_timezone(row.get("expires_at"), f"{kind}.expires_at")
            evidence_state = _text(row.get("evidence_state"), f"{kind}.evidence_state")
            if evidence_state not in EVIDENCE_STATES:
                raise ResearchToDecisionError(f"unsupported {kind} evidence_state: {evidence_state}")
            _number(row.get("confidence"), f"{kind}.confidence", minimum=0.0, maximum=1.0)
    return {
        "label": label,
        "role": "observation",
        "kind": kind,
        "format": fmt,
        "records_seen": len(rows),
        "records_accepted": len(rows),
        "evidence_refs": sorted(evidence_refs),
        "extraction_methods": sorted(extraction_methods),
        "warnings": sorted(warnings),
        "candidate_evidence_refs": {key: sorted(set(value)) for key, value in sorted(candidate_evidence_refs.items())},
        "status": "accepted",
    }


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


def _candidate_audit(
    candidate_ids: set[str],
    metadata: Mapping[str, Mapping[str, Any]],
    marketplace: Mapping[str, Any],
    supplier: Mapping[str, Any],
    synthesis: Mapping[str, Any],
    lane: Mapping[str, Any],
    supplier_offers: Mapping[str, list[dict[str, Any]]],
    evidence_refs_by_candidate: Mapping[str, set[str]],
) -> list[dict[str, Any]]:
    rows = []
    synthesis_items = {item.get("candidate_id"): item for item in synthesis.get("candidates", [])}
    for candidate_id in sorted(candidate_ids):
        supplier_item = _best(supplier, candidate_id)
        market_item = _best(marketplace, candidate_id)
        supplier_score = supplier_item.get("score", {})
        market_score = market_item.get("score", {})
        meta = metadata.get(candidate_id, {})
        offers = sorted(supplier_offers.get(candidate_id, []), key=lambda item: item["offer_id"])
        offer_issues = sorted({issue for offer in offers for issue in offer["issues"]})
        hard_gates = ["manual_evidence_is_not_live_supplier_proof", "no_launch_or_spend_authority"]
        if not offers:
            hard_gates.append("supplier_offer_evidence_missing")
        if offer_issues:
            hard_gates.extend(f"supplier_offer:{issue}" for issue in offer_issues)
        evidence_refs = sorted(evidence_refs_by_candidate.get(candidate_id, set()))
        if any("offer_expired" in issue for issue in offer_issues):
            freshness = "expired"
        elif offers and all(offer["evidence"].get("expires_at") for offer in offers):
            freshness = "current"
        elif offers:
            freshness = "unknown"
        else:
            freshness = "unavailable"
        risk_state = "blocked" if any(gate.startswith("supplier_offer:") or gate == "supplier_offer_evidence_missing" for gate in hard_gates) else "hold"
        rows.append({
            "candidate_id": candidate_id,
            "title": meta.get("title", candidate_id),
            "lifecycle_state": meta.get("lifecycle_state", "evidence_collected"),
            "evidence_expiry": meta.get("evidence_expiry"),
            "lane": {"destination_country": lane["destination_country"], "currency": lane["currency"], "warehouse": lane["warehouse"]},
            "supplier_offers": offers,
            "economics": supplier_score.get("economics") or {},
            "observed_values": {"supplier_offer_count": len(offers), "marketplace_evidence_count": len(market_item.get("evidence", [])), "currency": lane["currency"], "destination_country": lane["destination_country"]},
            "assumptions": sorted({*supplier_score.get("reasons", []), *market_score.get("reasons", [])}),
            "missing_evidence": sorted({item for item in (supplier_score.get("reasons", []) + market_score.get("reasons", [])) if "missing" in item or "unknown" in item or "unavailable" in item}),
            "evidence_refs": evidence_refs,
            "extraction_methods": sorted({offer["evidence"].get("extraction_method", "") for offer in offers if offer["evidence"].get("extraction_method")}),
            "freshness": freshness,
            "conflicts": sorted({issue for issue in offer_issues if "conflict" in issue}),
            "risk_state": risk_state,
            "confidence": {"supplier": supplier_score.get("overall_supplier_feasibility", 0.0), "marketplace": market_score.get("overall_marketplace_opportunity", 0.0)},
            "decision": (synthesis_items.get(candidate_id) or {}).get("next_best_action", "hold_for_manual_review"),
            "next_action": (synthesis_items.get(candidate_id) or {}).get("next_best_action", "hold_for_manual_review"),
            "action": (synthesis_items.get(candidate_id) or {}).get("next_best_action", "hold_for_manual_review"),
            "hard_gates": sorted(set(hard_gates)),
            "safety_classification": "offline_manual_evidence_only",
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
    supplier_offers_by_candidate: dict[str, list[dict[str, Any]]] = {}
    evidence_refs_by_candidate: dict[str, set[str]] = {}
    warnings: list[str] = []
    candidate_ids = set(metadata)
    for key, role, destination in (("supplier_inputs", "supplier", supplier_records), ("marketplace_inputs", "marketplace", marketplace_records), ("consumer_attention_inputs", "consumer_attention", consumer_records)):
        for entry in _input_entries(manifest, key):
            path = _resolve(base, entry.get("path"), label=f"{key}.path")
            records, audit = _load_import(path, entry, role, lane=lane, captured_at=captured_at)
            _check_record_conflicts(records, role, seen_records)
            if role == "supplier":
                quarantined = {(offer["candidate_id"], offer["exact_sku"]) for offer in audit.get("supplier_offers", []) if offer["status"] == "quarantined"}
                original_count = len(records)
                records = [record for record in records if (getattr(record, "candidate_id", ""), getattr(record, "supplier_sku", "")) not in quarantined]
                audit["records_accepted"] = len(records)
                audit["records_quarantined"] = original_count - len(records)
            destination.extend(records)
            candidate_ids.update(getattr(record, "candidate_id", "") for record in records)
            if role == "supplier":
                for offer in audit.get("supplier_offers", []):
                    supplier_offers_by_candidate.setdefault(offer["candidate_id"], []).append(offer)
                warnings.extend(f"supplier_offer:{issue}" for issue in audit.get("supplier_offer_issues", []))
            for candidate_id, refs in audit.get("candidate_evidence_refs", {}).items():
                evidence_refs_by_candidate.setdefault(candidate_id, set()).update(refs)
            input_audit.append(audit)
            if not records:
                warnings.append(f"no_accepted_records:{audit['label']}")
            if role in {"supplier", "marketplace", "consumer_attention"}:
                warnings.extend(_check_lane(records, lane, label=audit["label"]))
    for entry in _input_entries(manifest, "observation_inputs"):
        audit = _load_observation(_resolve(base, entry.get("path"), label="observation_inputs.path"), entry)
        input_audit.append(audit)
        for candidate_id, refs in audit.get("candidate_evidence_refs", {}).items():
            evidence_refs_by_candidate.setdefault(candidate_id, set()).update(refs)

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
        "market_lane": lane,
        "lane": lane,
        "input_audit": sorted(input_audit, key=lambda item: (item["role"], item["label"])),
        "validation": {"status": "hold_for_manual_review" if validation_warnings else "ready_for_operator_review", "warnings": sorted(set(validation_warnings)), "read_only": True, "network_calls": False, "credentials_used": False, "provider_calls": False, "orders_or_spend": False},
        "supplier_offers": sorted((offer for offers in supplier_offers_by_candidate.values() for offer in offers), key=lambda item: (item["candidate_id"], item["offer_id"])),
        "candidate_audit": _candidate_audit(candidate_ids, metadata, marketplace_report, supplier_report, synthesis_report, lane, supplier_offers_by_candidate, evidence_refs_by_candidate),
        "client_safe_projection": {
            "version": "research-to-decision-client-safe-v1",
            "candidates": [],
            "read_only": True,
            "launch_authorized": False,
            "provider_calls": False,
            "network_calls": False,
            "mutated": False,
        },
        "integration_contract": {
            "authority": "scripts.research_to_decision.py",
            "cockpit": "appendix.client_safe_projection",
            "commerce_cycle_dry_run": "existing source_reports and economics",
            "report_export": "product-validation-report-v1",
            "replay": "appendix.replay_fingerprint",
        },
        "source_authorities": {"supplier": "evaluation.commerce.supplier_feasibility", "marketplace": "evaluation.commerce.marketplace_trends", "consumer_attention": "evaluation.commerce.consumer_attention", "synthesis": "evaluation.commerce.opportunity_synthesis", "packet": "evaluation.commerce.product_validation_report"},
    }
    appendix["client_safe_projection"]["candidates"] = [
        {
            "candidate_id": item["candidate_id"],
            "title": item["title"],
            "decision": item["decision"],
            "next_action": item["next_action"],
            "risk_state": item["risk_state"],
            "freshness": item["freshness"],
            "confidence": item["confidence"],
            "missing_evidence": item["missing_evidence"],
            "hard_gates": item["hard_gates"],
            "evidence_refs": item["evidence_refs"],
        }
        for item in appendix["candidate_audit"]
    ]
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
