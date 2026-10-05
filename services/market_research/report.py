"""services.market_research.report — build_market_research_report.

Thin, additive composition over the existing offline evidence authorities.
This module never scores, ranks, grants launch authority, or invents a
second promotion gate: `evaluation.commerce.opportunity_synthesis.
build_product_opportunity_synthesis` remains the single fusion/ranking
authority it always was. This service only re-presents that authority's
output, plus the raw pillar reports it was built from, as one bounded,
consulting-ready Market Research report.

Not legal, tax, customs, supplier, or launch advice. Fixture/manual
evidence is never presented as live proof; a supplier claim is never
presented as validation; consumer attention is never presented as
supplier proof; marketplace trends are never presented as launch
authorization; a missing cost/shipping figure is never presented as zero.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from decimal import Decimal
from typing import Any, Mapping

from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis
from evaluation.trustos.client_workspace_isolation import check_workspace_leakage
from services.reporting.render import json_safe, render_markdown_report
from services.market_research_evidence import build_evidence_integrity_report
from services.market_research_evidence.freshness import classify_freshness
from services.market_research_evidence.identity import validate_binding, validate_candidate_id

from .schemas import (
    FIXTURE_LIKE_EVIDENCE_MODES,
    OFFERING_KINDS,
    EvidenceMatrixRow,
    MarketResearchRequest,
    MarketResearchResult,
    ValidationStep,
)

REPORT_VERSION = "market-research-service-v1"
TITLE = "MarketOS Market Research Report"

# Requirement-family-style freshness window, matching this repository's
# existing 180-day convention for other evidence-freshness checks
# (evaluation.trustos.mexico_product_compliance's citation_freshness_days).
DEFAULT_FRESHNESS_DAYS = 180
MAX_INPUT_NODES = 5_000
MAX_INPUT_DEPTH = 12
MAX_INPUT_STRING_BYTES = 8_192
MAX_REPORT_BYTES = 128 * 1024

_PILLAR_REPORT_FIELDS = (
    ("marketplace", "marketplace_report"),
    ("supplier", "supplier_report"),
    ("consumer_attention", "consumer_report"),
    ("public_market_benchmark", "public_market_benchmark_report"),
    ("product_validation", "product_validation_report"),
)

_UNSAFE_KEYS = frozenset({
    "api_key", "apikey", "access_token", "authorization", "cookie", "credential",
    "client_secret", "password", "private_key", "secret", "token", "raw_html",
    "raw_payload", "provider_payload", "provider_response", "raw_response", "internal_prompt", "formula", "source_code",
    "filesystem_path",
})
_UNSAFE_VALUE_MARKERS = (
    "<html", "<script", "-----begin", "ghp_", "github_pat_", "bearer ",
    "api_key", "access_token", "raw_payload", "provider_payload", "internal_prompt",
    "provider_response", "raw_response", "source_code", "pricing formula", "internal pricing",
    "formula", "heuristic", "strategy", "other_client", "cross_client", ".env",
)
_ABSOLUTE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|/(?:etc|home|tmp|Users)/)")
_UNSAFE_HTML_TAG = re.compile(r"</?[A-Za-z][^>]{0,256}>")
_UNSAFE_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{8,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\b"),
)
_SK_PREFIX = re.compile(r"(?<![a-z0-9])sk-|(?<=%[0-9a-f]{2})sk-|(?<=\\[nrt])sk-")


def _validate_safe_inputs(value: Any, *, depth: int = 0, nodes: list[int] | None = None) -> None:
    """Reject unsafe evidence before either authority sees the payload."""
    nodes = nodes if nodes is not None else [0]
    nodes[0] += 1
    if nodes[0] > MAX_INPUT_NODES or depth > MAX_INPUT_DEPTH:
        raise ValueError("evidence_input_bounds_exceeded")
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("malformed_evidence_input")
            key_text = str(key).casefold().replace("-", "_").replace(" ", "_")
            if key_text in _UNSAFE_KEYS or any(marker in key_text for marker in ("raw_payload", "provider_payload")):
                raise ValueError("unsafe_evidence_input")
            _validate_safe_inputs(child, depth=depth + 1, nodes=nodes)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _validate_safe_inputs(child, depth=depth + 1, nodes=nodes)
        return
    if isinstance(value, str):
        if len(value.encode("utf-8")) > MAX_INPUT_STRING_BYTES:
            raise ValueError("evidence_input_bounds_exceeded")
        lowered = value.casefold()
        if (
            _SK_PREFIX.search(lowered) is not None
            or any(marker in lowered for marker in _UNSAFE_VALUE_MARKERS)
            or _UNSAFE_HTML_TAG.search(value)
            or any(pattern.search(value) for pattern in _UNSAFE_SECRET_PATTERNS)
            or _ABSOLUTE_PATH.match(value)
        ):
            raise ValueError("unsafe_evidence_input")
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("malformed_evidence_input")
    if isinstance(value, Decimal) and not value.is_finite():
        raise ValueError("malformed_evidence_input")


def _validate_workspace_claims(value: Any, workspace_id: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).casefold() == "workspace_id" and child not in (None, ""):
                if not workspace_id:
                    raise ValueError("workspace_identity_required")
                if child != workspace_id:
                    raise ValueError("workspace_mismatch")
            _validate_workspace_claims(child, workspace_id)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _validate_workspace_claims(child, workspace_id)


def _validate_report_shape(report: Mapping[str, Any] | None) -> None:
    if not report:
        return
    seen_candidate_ids: set[str] = set()
    for key in ("candidates", "candidate_results"):
        if key not in report:
            continue
        values = report[key]
        if not isinstance(values, list) or any(not isinstance(item, Mapping) for item in values):
            raise ValueError("malformed_evidence_input")
        for item in values:
            candidate_id = item.get("candidate_id")
            if not isinstance(candidate_id, str) or not candidate_id.strip():
                raise ValueError("malformed_evidence_input")
            validate_candidate_id(candidate_id)
            if candidate_id in seen_candidate_ids:
                raise ValueError("ambiguous_candidate_identity")
            seen_candidate_ids.add(candidate_id)
            _validate_candidate_payload(item)


def _validate_candidate_payload(item: Mapping[str, Any]) -> None:
    """Reject shapes that would raise AttributeError or TypeError inside synthesis."""
    for key in ("offers", "evidence", "assumptions"):
        if key in item and item[key] is not None and (
            isinstance(item[key], str) or not isinstance(item[key], (list, tuple))
        ):
            raise ValueError("malformed_evidence_input")
    if "score" not in item or item.get("score") is None:
        return
    score = item.get("score")
    if not isinstance(score, Mapping):
        raise ValueError("malformed_evidence_input")
    for key in ("risk_flags", "assumptions", "creative_hooks", "recommended_ad_angles"):
        if key not in score:
            continue
        value = score[key]
        if value is None or isinstance(value, str) or not isinstance(value, (list, tuple)):
            raise ValueError("malformed_evidence_input")
    if "economics" in score and score["economics"] is not None and not isinstance(score["economics"], Mapping):
        raise ValueError("malformed_evidence_input")


def _validate_bound_request(request: MarketResearchRequest) -> str:
    if not isinstance(request.candidate_id, str):
        raise ValueError("invalid candidate_id")
    validate_candidate_id(request.candidate_id)
    if request.workspace_id not in (None, "") and not isinstance(request.workspace_id, str):
        raise ValueError("invalid workspace_id")
    workspace_id = request.workspace_id or ""
    for report in (
        request.marketplace_report,
        request.supplier_report,
        request.consumer_report,
        request.product_validation_report,
        request.public_market_benchmark_report,
        request.client_context,
    ):
        if report is not None and not isinstance(report, Mapping):
            raise ValueError("malformed_evidence_input")
        _validate_safe_inputs(report)
        if isinstance(report, Mapping):
            _validate_report_shape(report)
        _validate_workspace_claims(report, workspace_id)
    if not workspace_id:
        return ""
    validate_binding(request.candidate_id, workspace_id)
    return workspace_id


def _bound_integrity(
    request: MarketResearchRequest,
    workspace_id: str,
    synthesis: Mapping[str, Any],
) -> dict[str, Any] | None:
    if not workspace_id:
        return None
    integrity = build_evidence_integrity_report(
        candidate_id=request.candidate_id,
        workspace_id=workspace_id,
        as_of=request.as_of,
        marketplace_report=request.marketplace_report,
        supplier_report=request.supplier_report,
        consumer_report=request.consumer_report,
        public_market_benchmark_report=request.public_market_benchmark_report,
        product_validation_report=request.product_validation_report,
        synthesis=synthesis,
    )
    return integrity.to_dict()


def _evidence_class(integrity: Mapping[str, Any] | None) -> str:
    if not integrity:
        return "unbound"
    modes = sorted({str(item.get("evidence_mode")) for item in integrity.get("provenance_records", ())})
    if not modes or modes == ["missing"]:
        return "missing"
    if len(modes) == 1:
        return modes[0]
    return "mixed"


def _freshness_rows(integrity: Mapping[str, Any] | None) -> tuple[dict[str, Any], ...]:
    if not integrity:
        return ()
    rows = []
    for item in integrity.get("provenance_records", ()):
        observation = item.get("observation", {})
        source = item.get("source", {})
        rows.append({
            "field": observation.get("field", ""),
            "pillar": item.get("pillar", ""),
            "status": item.get("freshness_status", "missing"),
            "observed_at": item.get("observed_at", "missing"),
            "source_ref": source.get("source_ref", ""),
        })
    return tuple(sorted(rows, key=lambda row: (row["field"], row["pillar"], row["source_ref"])))


def _next_research_actions(
    *,
    follow_up_modules: list[str],
    missing_data: tuple[str, ...],
    freshness: tuple[dict[str, Any], ...],
    conflicts: tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    actions = list(follow_up_modules)
    actions.extend(f"obtain_evidence:{item}" for item in missing_data)
    actions.extend(
        f"reconcile_conflict:{item['field']}"
        for item in conflicts
        if item.get("field")
    )
    if any(item.get("status") in {"stale", "future", "unknown"} for item in freshness):
        actions.append("refresh_or_reject_temporally_invalid_evidence")
    return tuple(dict.fromkeys(sorted(actions)))


def _score_mapping(matched: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """A present score must be an object. A list or scalar is malformed, not a miss."""
    if not matched:
        return {}
    score = matched.get("score", {})
    if score is None:
        return {}
    if not isinstance(score, Mapping):
        raise ValueError("malformed_evidence_input")
    return score


def _economics_mapping(score: Mapping[str, Any]) -> Mapping[str, Any]:
    economics = score.get("economics", {})
    if economics is None:
        return {}
    if not isinstance(economics, Mapping):
        raise ValueError("malformed_evidence_input")
    return economics


def _string_items(value: Any) -> list[str]:
    """A missing key should be passed as []. An explicit null or scalar is malformed."""
    if value is None or isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ValueError("malformed_evidence_input")
    return [str(item) for item in value]


def _alias_notes_for_candidate(notes: Any, candidate_id: str) -> tuple[str, ...]:
    """Keep alias notes that name this candidate. Notes about other rows do not cross over."""
    if notes is None:
        return ()
    if isinstance(notes, str) or not isinstance(notes, (list, tuple)):
        raise ValueError("malformed_evidence_input")
    token = f"'{candidate_id}'"
    return tuple(str(note) for note in notes if token in str(note))


def _product_validation_ids(report: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    report_candidate_id = report.get("candidate_id")
    if isinstance(report_candidate_id, str) and report_candidate_id.strip():
        ids.add(report_candidate_id)
    for key in ("top_candidates", "candidate_rankings"):
        rows = report.get(key)
        if rows is None:
            continue
        if not isinstance(rows, list) or any(not isinstance(item, Mapping) for item in rows):
            raise ValueError("malformed_evidence_input")
        for row in rows:
            nested = row.get("candidate")
            if nested is not None and not isinstance(nested, Mapping):
                raise ValueError("malformed_evidence_input")
            if isinstance(nested, Mapping):
                nested_id = nested.get("candidate_id")
                if isinstance(nested_id, str) and nested_id.strip():
                    ids.add(nested_id)
            row_id = row.get("candidate_id")
            if isinstance(row_id, str) and row_id.strip():
                ids.add(row_id)
    return ids


def _recognized_offering_kind(raw: Any) -> tuple[str, bool]:
    if raw in (None, ""):
        return "unknown", True
    value = str(raw).strip().lower()
    if value in OFFERING_KINDS:
        return value, True
    return "unknown", False


def _matched_candidate(report: Mapping[str, Any] | None, candidate_id: str) -> Mapping[str, Any] | None:
    if not report:
        return None
    for key in ("candidates", "candidate_results"):
        values = report.get(key, [])
        if values is None:
            continue
        if not isinstance(values, list):
            raise ValueError("malformed_evidence_input")
        for item in values:
            if isinstance(item, Mapping) and str(item.get("candidate_id")) == candidate_id:
                return item
    return None


def _candidate_scoped_report(report: Mapping[str, Any] | None, candidate_id: str) -> Mapping[str, Any] | None:
    """Keep the canonical synthesis authority scoped to the requested ID."""
    if not report:
        return report
    scoped = dict(report)
    for key in ("candidates", "candidate_results"):
        if key in report and isinstance(report[key], list):
            scoped[key] = [item for item in report[key] if isinstance(item, Mapping) and str(item.get("candidate_id")) == candidate_id]
    return scoped


def _candidate_observed_at(matched: Mapping[str, Any] | None) -> str | None:
    if not matched:
        return None
    for key in ("observed_at", "as_of"):
        if matched.get(key):
            return str(matched[key])
    score = _score_mapping(matched)
    for key in ("observed_at", "as_of"):
        if score.get(key):
            return str(score[key])
    return None


def _product_validation_candidate(report: Mapping[str, Any], candidate_id: str) -> Mapping[str, Any] | None:
    """Return a ProductValidation row only when it carries candidate identity.

    ProductValidationReport is normally an aggregate presentation report. Its
    top-candidate title, risks, and open questions must not become evidence for
    a different candidate merely because the report was supplied alongside it.
    """
    report_candidate_id = report.get("candidate_id")
    if report_candidate_id == candidate_id:
        return report
    for key in ("top_candidates", "candidate_rankings"):
        rows = report.get(key)
        if rows is None:
            continue
        if not isinstance(rows, list) or any(not isinstance(item, Mapping) for item in rows):
            raise ValueError("malformed_evidence_input")
        for row in rows:
            nested = row.get("candidate")
            if isinstance(nested, Mapping) and nested.get("candidate_id") == candidate_id:
                return row
            if row.get("candidate_id") == candidate_id:
                return row
    return None


def _pillar_row(name: str, report: Mapping[str, Any] | None, *, candidate_id: str, as_of: str) -> EvidenceMatrixRow:
    if not report:
        return EvidenceMatrixRow(name, "missing", None, None, (f"{name}_not_supplied",))
    evidence_mode = report.get("evidence_mode")
    evidence_mode = str(evidence_mode) if evidence_mode not in (None, "") else None
    notes: list[str] = []
    if evidence_mode in FIXTURE_LIKE_EVIDENCE_MODES:
        notes.append(f"{name}_evidence_mode_is_{evidence_mode}_not_live_proof")
    matched = (
        _product_validation_candidate(report, candidate_id)
        if name == "product_validation"
        else _matched_candidate(report, candidate_id)
    )
    if matched is None:
        note = "candidate_not_bound" if name == "product_validation" else "candidate_not_matched"
        notes.append(f"{name}_{note}:{candidate_id}")
        return EvidenceMatrixRow(name, "missing", evidence_mode, None, tuple(notes))
    observed_at = _candidate_observed_at(matched)
    status = "supplied"
    # Delegates to the one canonical freshness classifier
    # (services.market_research_evidence.freshness.classify_freshness)
    # instead of re-deriving the same day-diff/threshold logic here, so
    # the unbound evidence-matrix view and the bound evidence-integrity
    # view can never silently diverge on what counts as stale/future.
    freshness_status = classify_freshness(observed_at, as_of, freshness_days=DEFAULT_FRESHNESS_DAYS)
    if freshness_status == "future":
        status = "future"
        notes.append(f"{name}_observed_at_is_after_as_of")
    elif freshness_status == "stale":
        status = "stale"
        notes.append(f"{name}_observed_at_exceeds_{DEFAULT_FRESHNESS_DAYS}_day_freshness_window")
    elif freshness_status == "unknown":
        notes.append(f"{name}_observed_at_is_not_a_real_timestamp:{observed_at}")
    return EvidenceMatrixRow(name, status, evidence_mode, observed_at, tuple(notes))


def _observed_list(report: Mapping[str, Any] | None, *field_names: str) -> list[str]:
    if not report:
        return []
    for field_name in field_names:
        value = report.get(field_name)
        if isinstance(value, (list, tuple)) and value:
            return [str(item) for item in value]
    return []


def _demand_and_customer_evidence(consumer_report: Mapping[str, Any] | None, matched: Mapping[str, Any] | None) -> dict[str, Any]:
    if not consumer_report:
        return {"status": "consumer_attention_not_supplied"}
    if matched is None:
        return {"status": "candidate_not_matched", "warning": "consumer_attention_for_another_candidate_is_not_evidence_for_this_candidate"}
    score = _score_mapping(matched)
    return {
        "status": "supplied",
        "platforms_observed": _observed_list(consumer_report, "platforms_observed"),
        "overall_consumer_attention": score.get("overall_consumer_attention"),
        "voice_of_customer": score.get("voice_of_customer", {}),
        "recommendation": score.get("recommendation"),
        "warning": "consumer_attention_is_not_supplier_proof",
    }


def _competitor_and_substitute_evidence(marketplace_report: Mapping[str, Any] | None, matched: Mapping[str, Any] | None) -> dict[str, Any]:
    if not marketplace_report:
        return {"status": "marketplace_trends_not_supplied"}
    if matched is None:
        return {"status": "candidate_not_matched", "warning": "marketplace_evidence_for_another_candidate_is_not_evidence_for_this_candidate"}
    score = _score_mapping(matched)
    return {
        "status": "supplied",
        "marketplaces_observed": _observed_list(marketplace_report, "marketplaces_observed", "platforms_observed"),
        "overall_marketplace_opportunity": score.get("overall_marketplace_opportunity"),
        "saturation_score": score.get("saturation_score"),
        "warning": "marketplace_trends_are_demand_and_competition_evidence_only_not_launch_authorization",
    }


def _marketplace_and_public_signals(public_market_report: Mapping[str, Any] | None, matched: Mapping[str, Any] | None) -> dict[str, Any]:
    if not public_market_report:
        return {"status": "public_market_benchmark_not_supplied"}
    if matched is None:
        return {"status": "candidate_not_matched", "warning": "public_market_evidence_for_another_candidate_is_not_evidence_for_this_candidate"}
    return {
        "status": "supplied",
        "pricing_coverage": public_market_report.get("pricing_coverage"),
        "pages_observed": (
            public_market_report.get("pages_observed")
            if public_market_report.get("pages_observed") is not None
            else public_market_report.get("pages_attempted")
        ),
        "candidate_count": public_market_report.get("candidate_count"),
    }


def _supplier_feasibility_section(supplier_report: Mapping[str, Any] | None, matched: Mapping[str, Any] | None) -> dict[str, Any]:
    if not supplier_report:
        return {"status": "supplier_feasibility_not_relevant_or_not_supplied"}
    if matched is None:
        return {"status": "candidate_not_matched", "warning": "supplier_evidence_for_another_candidate_is_not_evidence_for_this_candidate"}
    score = _score_mapping(matched)
    return {
        "status": "supplied",
        "overall_supplier_feasibility": score.get("overall_supplier_feasibility"),
        "recommendation": score.get("recommendation"),
        "risk_flags": _string_items(score.get("risk_flags", [])),
        "economics": _economics_mapping(score),
        "warning": "a_supplier_claim_is_not_validation_until_observed_or_verified",
    }


def _delivery_and_logistics_feasibility(supplier_report: Mapping[str, Any] | None, matched: Mapping[str, Any] | None) -> dict[str, Any]:
    if not supplier_report:
        return {"status": "supplier_feasibility_not_relevant_or_not_supplied"}
    if matched is None:
        return {"status": "candidate_not_matched"}
    score = _score_mapping(matched)
    economics = _economics_mapping(score)
    shipping_cost = economics.get("shipping_cost")
    shipping_speed_score = economics.get("shipping_speed_score")
    moq = economics.get("moq")
    result: dict[str, Any] = {"status": "supplied"}
    # An absent key and an explicit `null` both mean "we don't know" here --
    # neither is ever a real 0/false value for these fields, so both are
    # normalized to the same "missing" sentinel rather than letting an
    # explicit null slip through as JSON `null` while an absent key becomes
    # the string "missing".
    result["shipping_cost"] = shipping_cost if shipping_cost is not None else "missing"
    result["shipping_speed_score"] = shipping_speed_score if shipping_speed_score is not None else "missing"
    result["moq"] = moq if moq is not None else "missing"
    if shipping_cost is None:
        result["note"] = "shipping_cost_missing_is_not_the_same_as_zero_cost"
    return result


def _pricing_and_willingness_to_pay(synthesis_dict: Mapping[str, Any]) -> dict[str, Any]:
    band = synthesis_dict.get("recommended_price_band") or {}
    if not isinstance(band, Mapping):
        band = {}
    return {
        "recommended_price_band": band,
        "status": band.get("status", "unavailable"),
        "note": "derived from the existing opportunity-synthesis authority's own price-band logic; not a willingness-to-pay study",
    }


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(json_safe(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_market_research_report(request: MarketResearchRequest) -> MarketResearchResult:
    offering_kind, offering_recognized = _recognized_offering_kind(request.offering_kind)
    workspace_id = _validate_bound_request(request)

    synthesis = build_product_opportunity_synthesis(
        _candidate_scoped_report(request.marketplace_report, request.candidate_id),
        _candidate_scoped_report(request.supplier_report, request.candidate_id),
        _candidate_scoped_report(request.consumer_report, request.candidate_id),
        product_validation_report=request.product_validation_report,
        client_context=request.client_context,
    ).to_dict()
    alias_notes = _alias_notes_for_candidate(
        build_product_opportunity_synthesis(
            request.marketplace_report,
            request.supplier_report,
            request.consumer_report,
            product_validation_report=request.product_validation_report,
            client_context=request.client_context,
        ).to_dict().get("alias_notes", ()),
        request.candidate_id,
    )
    integrity = _bound_integrity(request, workspace_id, synthesis)

    candidate_id = request.candidate_id
    matched_marketplace = _matched_candidate(request.marketplace_report, candidate_id)
    matched_supplier = _matched_candidate(request.supplier_report, candidate_id)
    matched_consumer = _matched_candidate(request.consumer_report, candidate_id)
    matched_public_market = _matched_candidate(request.public_market_benchmark_report, candidate_id)

    evidence_matrix = tuple(
        _pillar_row(name, getattr(request, field_name), candidate_id=candidate_id, as_of=request.as_of)
        for name, field_name in _PILLAR_REPORT_FIELDS
    )
    source_reports = {name: ("supplied" if getattr(request, field_name) else "missing") for name, field_name in _PILLAR_REPORT_FIELDS}

    assumptions: list[str] = []
    observed_facts: list[str] = []
    product_validation_candidate = (
        _product_validation_candidate(request.product_validation_report, request.candidate_id)
        if request.product_validation_report
        else None
    )
    if (
        product_validation_candidate
        and request.product_validation_report is not None
        and _product_validation_ids(request.product_validation_report) == {request.candidate_id}
    ):
        assumptions.extend(_string_items(request.product_validation_report.get("open_questions", [])))
        observed_facts.extend(_string_items(request.product_validation_report.get("risk_flags", [])))
    if matched_supplier:
        supplier_score = _score_mapping(matched_supplier)
        raw_assumptions = matched_supplier.get("assumptions")
        if not raw_assumptions:
            raw_assumptions = supplier_score.get("assumptions", [])
        assumptions.extend(_string_items(raw_assumptions))
    if matched_marketplace:
        observed_facts.extend(_observed_list(request.marketplace_report, "marketplaces_observed"))
    if matched_consumer:
        observed_facts.extend(_observed_list(request.consumer_report, "platforms_observed"))
    assumptions = sorted(dict.fromkeys(assumptions))
    observed_facts = sorted(dict.fromkeys(observed_facts))

    risk_profile = synthesis.get("risk_profile") or {}
    if not isinstance(risk_profile, Mapping):
        risk_profile = {}
    blockers = tuple(dict.fromkeys(risk_profile.get("blockers", [])))
    risks = tuple(dict.fromkeys(
        list(risk_profile.get("supplier_risks", []))
        + list(risk_profile.get("marketplace_risks", []))
        + list(risk_profile.get("consumer_risks", []))
    ))
    integrity_conflicts = tuple(integrity.get("deterministic_conflicts", ())) if integrity else ()
    source_conflicts = tuple(dict.fromkeys(
        list(alias_notes)
        + [str(item.get("note", "unresolved_evidence_conflict")) for item in integrity_conflicts]
    ))

    validation_plan = tuple(
        ValidationStep(str(item.get("window", "")), str(item.get("task", "")))
        for item in synthesis.get("fourteen_day_validation_plan", [])
    )
    if not validation_plan:
        validation_plan = (ValidationStep("unscheduled", "validation_plan_not_supplied_by_the_synthesis_authority"),)

    follow_up_modules: list[str] = []
    if not request.supplier_report:
        follow_up_modules.append("supplier_feasibility")
    if not request.consumer_report:
        follow_up_modules.append("consumer_attention")
    if not request.public_market_benchmark_report:
        follow_up_modules.append("public_market_benchmark")
    if offering_kind in {"service", "hybrid"}:
        follow_up_modules.append("service_delivery_feasibility_when_a_canonical_evaluator_exists")

    evidence_matrix_missing = tuple(
        f"{row.pillar}.report" for row in evidence_matrix if row.status == "missing"
    )
    missing_data = tuple(dict.fromkeys(
        (list(integrity.get("missing_fields", ())) if integrity else []) + list(evidence_matrix_missing)
    ))
    freshness = _freshness_rows(integrity)
    if not integrity:
        freshness = tuple(
            {"field": row.pillar, "pillar": row.pillar, "status": row.status, "observed_at": row.observed_at, "source_ref": ""}
            for row in evidence_matrix
            if row.status in {"stale", "future", "unknown"}
        )
    observation_source_identity = tuple(
        {
            "observation": item.get("observation", {}),
            "source": item.get("source", {}),
        }
        for item in (integrity.get("provenance_records", ()) if integrity else ())
    )
    source_provenance = tuple(integrity.get("provenance_records", ())) if integrity else ()
    evidence_class = _evidence_class(integrity)
    if integrity:
        if integrity.get("deterministic_conflict_detected"):
            blockers = tuple(dict.fromkeys(list(blockers) + ["evidence_conflict"]))
        if integrity.get("missing_fields"):
            blockers = tuple(dict.fromkeys(list(blockers) + ["evidence_missing"]))
        if any(item.get("freshness_status") in {"stale", "future", "unknown"} for item in source_provenance):
            blockers = tuple(dict.fromkeys(list(blockers) + ["evidence_freshness_unresolved"]))
    else:
        blockers = tuple(dict.fromkeys(list(blockers) + ["workspace_identity_unavailable"]))
    if any(row.status == "missing" for row in evidence_matrix):
        blockers = tuple(dict.fromkeys(list(blockers) + ["evidence_missing"]))
    if any(row.status in {"stale", "future", "unknown"} for row in evidence_matrix):
        blockers = tuple(dict.fromkeys(list(blockers) + ["evidence_freshness_unresolved"]))
    if request.product_validation_report and product_validation_candidate is None:
        blockers = tuple(dict.fromkeys(list(blockers) + ["product_validation_candidate_binding_unavailable"]))

    conflict_findings = tuple(integrity_conflicts)
    next_research_actions = _next_research_actions(
        follow_up_modules=follow_up_modules,
        missing_data=missing_data,
        freshness=freshness,
        conflicts=conflict_findings,
    )

    client_safe_projection = {
        "candidate_id": request.candidate_id,
        "workspace_id": workspace_id,
        "offering_kind": offering_kind,
        "geography": request.geography,
        "language": request.language,
        "evidence_class": evidence_class,
        "freshness": list(freshness),
        "conflict_findings": [
            {"field": item.get("field", ""), "delta": item.get("delta", 0), "note": item.get("note", "")}
            for item in conflict_findings
        ],
        "missing_data": list(missing_data),
        "blockers": list(blockers),
        "next_research_actions": list(next_research_actions),
        "live_proof": False,
        "external_actions_authorized": False,
    }
    leakage_findings = check_workspace_leakage(client_safe_projection, client_safe=True)
    client_safe_export_status = (
        "blocked_identity_unavailable" if not workspace_id
        else "blocked_leakage" if leakage_findings
        else "ready_for_trustos_review"
    )
    if client_safe_export_status != "ready_for_trustos_review":
        blockers = tuple(dict.fromkeys(list(blockers) + ["client_safe_export_blocked"]))
        client_safe_projection["blockers"] = list(blockers)
    next_research_actions = _next_research_actions(
        follow_up_modules=follow_up_modules,
        missing_data=missing_data,
        freshness=freshness,
        conflicts=conflict_findings,
    )

    supplied_pillars = any(getattr(request, field_name) for _, field_name in _PILLAR_REPORT_FIELDS)
    combined_opportunity_score = synthesis.get("combined_opportunity_score")
    # The synthesis authority returns 0.0 when it has no candidate row. That
    # fallback is not an explicit zero for the requested candidate.
    if not supplied_pillars or str(synthesis.get("top_candidate_id") or "") != candidate_id:
        combined_opportunity_score = "missing"
    executive_summary = {
        "headline": synthesis.get("client_summary", ""),
        "operator_summary": synthesis.get("operator_summary", ""),
        "overall_recommendation": synthesis.get("overall_recommendation", "hold_for_manual_review"),
        "combined_opportunity_score": combined_opportunity_score if combined_opportunity_score is not None else "missing",
        "confidence_grade": synthesis.get("confidence_grade", "F_reject_or_missing"),
    }

    limitations = [
        "offline_composition_only_no_live_provider_calls_performed_by_this_service",
        "attention_is_not_supplier_proof",
        "trends_are_not_launch_authorization",
        "a_supplier_claim_is_not_validation",
        "fixture_or_manual_evidence_is_not_live_proof",
    ]
    if not offering_recognized:
        limitations.append(f"offering_kind '{request.offering_kind}' was not recognized and was treated as unknown")
    if offering_kind == "unknown":
        limitations.append("offering_kind_unknown_no_applicability_determination_made")

    candidate_title = None
    for matched in (matched_marketplace, matched_supplier, matched_consumer, matched_public_market):
        if matched and matched.get("title"):
            candidate_title = matched["title"]
            break
    if candidate_title is None and str(synthesis.get("top_candidate_id")) == candidate_id:
        candidate_title = synthesis.get("top_candidate_title")
    candidate_title = candidate_title or candidate_id

    fingerprint_payload = {
        "report_version": REPORT_VERSION,
        "candidate_id": candidate_id,
        "workspace_id": workspace_id,
        "offering_kind": offering_kind,
        "geography": request.geography,
        "language": request.language,
        "evidence_matrix": [row.to_dict() for row in evidence_matrix],
        "executive_summary": executive_summary,
        "blockers": list(blockers),
        "risks": list(risks),
        "observation_source_identity": list(observation_source_identity),
        "freshness": list(freshness),
        "conflict_findings": list(conflict_findings),
        "evidence_class": evidence_class,
        "source_provenance": list(source_provenance),
        "missing_data": list(missing_data),
        "client_safe_export_status": client_safe_export_status,
        "client_safe_projection": client_safe_projection,
        "next_research_actions": list(next_research_actions),
        "evidence_integrity_fingerprint": integrity.get("fingerprint", "") if integrity else "",
    }

    result = MarketResearchResult(
        report_version=REPORT_VERSION,
        candidate_id=candidate_id,
        workspace_id=workspace_id,
        candidate_title=str(candidate_title),
        offering_kind=offering_kind,
        offering_kind_recognized=offering_recognized,
        geography=request.geography,
        language=request.language,
        executive_summary=executive_summary,
        evidence_matrix=evidence_matrix,
        demand_and_customer_evidence=_demand_and_customer_evidence(request.consumer_report, matched_consumer),
        competitor_and_substitute_evidence=_competitor_and_substitute_evidence(request.marketplace_report, matched_marketplace),
        marketplace_and_public_signals=_marketplace_and_public_signals(request.public_market_benchmark_report, matched_public_market),
        supplier_feasibility=_supplier_feasibility_section(request.supplier_report, matched_supplier),
        delivery_and_logistics_feasibility=_delivery_and_logistics_feasibility(request.supplier_report, matched_supplier),
        pricing_and_willingness_to_pay=_pricing_and_willingness_to_pay(synthesis),
        assumptions=tuple(assumptions),
        observed_facts=tuple(observed_facts),
        source_conflicts=source_conflicts,
        confidence_grade=synthesis.get("confidence_grade", "F_reject_or_missing"),
        limitations=tuple(limitations),
        blockers=blockers,
        risks=risks,
        next_action=synthesis.get("next_best_action", "hold_for_manual_review"),
        validation_plan=validation_plan,
        follow_up_modules=tuple(dict.fromkeys(follow_up_modules)),
        fingerprint=_fingerprint(fingerprint_payload),
        source_reports=source_reports,
        observation_source_identity=observation_source_identity,
        freshness=freshness,
        conflict_findings=conflict_findings,
        evidence_class=evidence_class,
        source_provenance=source_provenance,
        missing_data=missing_data,
        client_safe_export_status=client_safe_export_status,
        client_safe_projection=client_safe_projection,
        next_research_actions=next_research_actions,
        evidence_integrity_fingerprint=integrity.get("fingerprint", "") if integrity else "",
    )
    try:
        encoded = json.dumps(json_safe(result.to_dict()), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("malformed_market_research_output") from exc
    if len(encoded) > MAX_REPORT_BYTES:
        raise ValueError("market_research_output_bounds_exceeded")
    return result


def render_market_research_markdown(result: MarketResearchResult) -> str:
    data = result.to_dict()
    sections = [
        {"heading": "Candidate & Workspace Identity", "body": {"candidate_id": data["candidate_id"], "workspace_id": data["workspace_id"], "offering_kind": data["offering_kind"]}},
        {"heading": "Executive Decision Summary", "body": data["executive_summary"]},
        {"heading": "Evidence Matrix", "body": data["evidence_matrix"]},
        {"heading": "Observation & Source Provenance", "body": data["observation_source_identity"] or ["none recorded"]},
        {"heading": "Freshness", "body": data["freshness"] or ["none recorded"]},
        {"heading": "Demand & Customer Evidence", "body": data["demand_and_customer_evidence"]},
        {"heading": "Competitor & Substitute Evidence", "body": data["competitor_and_substitute_evidence"]},
        {"heading": "Marketplace & Public-Market Signals", "body": data["marketplace_and_public_signals"]},
        {"heading": "Supplier Feasibility", "body": data["supplier_feasibility"]},
        {"heading": "Delivery & Logistics Feasibility", "body": data["delivery_and_logistics_feasibility"]},
        {"heading": "Pricing & Willingness-to-Pay Hypotheses", "body": data["pricing_and_willingness_to_pay"]},
        {"heading": "Assumptions (not yet observed)", "body": data["assumptions"] or ["none recorded"]},
        {"heading": "Observed Facts", "body": data["observed_facts"] or ["none recorded"]},
        {"heading": "Source Conflicts", "body": data["source_conflicts"] or ["none detected"]},
        {"heading": "Deterministic Conflict Findings", "body": data["conflict_findings"] or ["none detected"]},
        {"heading": "Missing Data", "body": data["missing_data"] or ["none recorded"]},
        {"heading": "Confidence & Limitations", "body": {"confidence_grade": data["confidence_grade"], "limitations": data["limitations"]}},
        {"heading": "Blockers", "body": list(data["blockers"]) or ["none recorded"]},
        {"heading": "Risks", "body": list(data["risks"]) or ["none recorded"]},
        {"heading": "Prioritized Next Action", "body": data["next_action"]},
        {"heading": "Next Research Actions", "body": data["next_research_actions"] or ["none recorded"]},
        {"heading": "Client-Safe Export Status", "body": data["client_safe_export_status"]},
        {"heading": "Bounded Validation Plan", "body": data["validation_plan"]},
        {"heading": "Optional Follow-Up Modules", "body": list(data["follow_up_modules"]) or ["none recommended"]},
        {"heading": "Report Fingerprint", "body": data["fingerprint"]},
        {"heading": "Disclaimer", "body": data["disclaimer"]},
    ]
    return render_markdown_report(TITLE, sections, dry_run=data["dry_run"], generated_at=data["generated_at"])


__all__ = ["REPORT_VERSION", "TITLE", "build_market_research_report", "render_market_research_markdown"]
