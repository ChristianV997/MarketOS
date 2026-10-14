"""Deterministic evaluation of Product Opportunity Synthesis inputs.

Measures whether the existing synthesis makes evidence-grounded, appropriately
cautious decisions on synthetic packets or already-collected sanitized receipts.
It adds no score, changes no threshold, makes no network call, and writes
nothing unless --output is given.

Expectations in a packet are safety policy written before the run. A failing
expectation is reported as a known gap only when the packet names that exact
scenario and check. Any other failure is unexpected and fails the run.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis  # noqa: E402

SCHEMA = "MarketOS.ProductOpportunityResearchEval.v1"
LIVE_SCHEMA = "MarketOS.ProductOpportunityLiveEvidence.v1"
PACKET_PATH = ROOT / "tests" / "fixtures" / "product_opportunity_eval" / "packet.json"
FIXTURE_PREFIX = "tests/fixtures/"
PILLARS = ("marketplace", "supplier", "consumer")
EVIDENCE_KEY = {"marketplace": "evidence", "supplier": "offers", "consumer": "evidence"}
REQUIRED_FIELDS = {
    "marketplace": ("marketplace", "price", "evidence_mode", "source_confidence"),
    "supplier": ("supplier", "unit_cost", "estimated_landed_cost", "delivery_max_days", "evidence_mode"),
    "consumer": ("platform", "evidence_mode"),
}
FRESHNESS_STATES = frozenset({"fresh", "stale", "future_dated", "unavailable"})
LIVE_RECEIPT_MODES = frozenset({"live_readonly", "actual_executed"})
LIVE_EVIDENCE_CLASSES = frozenset({"live", "actual_executed"})
LIVE_REQUIRED_RECEIPT_FIELDS = frozenset({
    "receipt_id", "provider_id", "source_type", "source_reference", "collected_at",
    "freshness", "geography", "language", "candidate_id", "variant_id",
    "evidence_class", "evidence_mode", "is_live", "currency",
})
LIVE_MAX_PACKET_BYTES = 256 * 1024
LIVE_MAX_RECEIPTS_PER_PILLAR = 32
LIVE_NOT_APPLICABLE_CURRENCY = "not_applicable"
LIVE_FORBIDDEN_KEYS = frozenset({
    "raw_payload", "raw_response", "raw_html", "response_body", "stack_trace",
    "payload", "raw", "html", "body", "response", "exception", "credential",
    "password", "access_token", "secret", "token",
})
SECRET_SHAPED = re.compile(r"(?i)(?:sk_(?:live|test)|gh[pous]_|github_pat_|xox[bap]-|bearer\s+)[A-Za-z0-9_.:/+-]{8,}")
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
GRADE_RANK = {"A_live_validated": 4, "B_multi_source_manual": 3, "C_fixture_or_partial": 2, "D_low_confidence": 1, "F_reject_or_missing": 0}
ADVANCE = "advance_to_launch_draft"
DRAFT_ACTION = "prepare_launch_draft_for_human_review"
NON_EXECUTING_ACTIONS = frozenset({
    "run_readonly_supplier_validation",
    "validate_supplier_first",
    "expand_marketplace_research",
    "expand_marketplace_research_before_testing",
    "expand_consumer_research",
    "expand_supplier_research",
    "review_supplier_risk",
    "review_supplier_cost_or_price_band",
    "operator_review_evidence_matrix",
    DRAFT_ACTION,
})
NON_ADVANCING_RECOMMENDATIONS = frozenset({ADVANCE, "ready"})
HARD_SAFETY_CHECKS = frozenset({
    "currency_safety_invariant",
    "identity_safety_invariant",
    "stale_evidence_safety_invariant",
    "price_safety_invariant",
    "incomplete_evidence_safety_invariant",
})
# A caution counts only when it is one of these exact codes. The synthesis emits none of the
# currency, identity, freshness, or price codes today, so those checks are known gaps. Matching is
# by equality, never substring: an unrelated code cannot satisfy a category by accident.
CAUTION_CODES = {
    "currency": frozenset({"currency_unreconciled", "currency_mismatch"}),
    "identity": frozenset({"identity_conflict", "variant_mismatch", "query_mismatch"}),
    "freshness": frozenset({"consumer_evidence_stale", "consumer_evidence_future_dated", "consumer_evidence_unavailable"}),
    "price": frozenset({"price_band_conflict", "target_outside_band"}),
    "incomplete": frozenset({"incomplete_evidence", "evidence_field_missing"}),
}
# The synthesis emits these when a supplier pillar is absent, which is a different condition from an
# incomplete item. They count as incomplete-evidence cautions only when a supplier pillar is present.
ECONOMICS_MISSING_CODES = frozenset({"target_sell_price_missing", "estimated_landed_cost_missing"})
EXPECTATION_KEYS = frozenset({
    "expected_coverage",
    "reported_coverage_matches_effective",
    "expected_recommendation",
    "must_not_advance",
    "max_grade",
    "required_blockers",
    "assumptions_must_include",
    "min_alias_notes",
    "retained_candidates",
    "expected_metrics",
})
METRIC_KEYS = frozenset({"currency_unreconciled", "identity_conflicts", "price_conflicts", "incomplete_items", "pillar_warnings"})
KNOWN_CHECKS = frozenset({
    "harness_metrics_match",
    "expected_coverage",
    "reported_coverage_matches_effective",
    "expected_recommendation",
    "must_not_advance",
    "advance_must_be_draft_only",
    "max_grade",
    "required_blockers",
    "assumptions_must_include",
    "min_alias_notes",
    "retained_candidates",
    "non_authorization",
    "currency_flagged",
    "identity_flagged",
    "freshness_flagged",
    "price_flagged",
    "incomplete_flagged",
    "pillar_warnings_surfaced",
})


def load_packet(path: Path = PACKET_PATH) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ValueError("unsupported packet schema")
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("packet has no scenarios")
    ids = [str(item.get("id", "")) for item in scenarios if isinstance(item, dict)]
    if len(ids) != len(scenarios) or not all(ids) or len(set(ids)) != len(ids):
        raise ValueError("scenario ids must be present and unique")
    for scenario in scenarios:
        expectations = scenario.get("expectations", {})
        unknown = sorted(set(expectations) - EXPECTATION_KEYS)
        if unknown:
            raise ValueError(f"unknown expectation keys in {scenario['id']}: {unknown}")
        metrics = expectations.get("expected_metrics", {})
        unknown_metrics = sorted(set(metrics) - METRIC_KEYS)
        if unknown_metrics:
            raise ValueError(f"unknown expected_metrics keys in {scenario['id']}: {unknown_metrics}")
        identity_query_context = scenario.get("identity_query_context")
        if identity_query_context is not None:
            if not isinstance(identity_query_context, dict) or not identity_query_context:
                raise ValueError(f"identity_query_context must be a non-empty object in {scenario['id']}")
            for candidate_id, queries in identity_query_context.items():
                if not isinstance(candidate_id, str) or not candidate_id.strip():
                    raise ValueError(f"identity_query_context candidate ids must be non-empty in {scenario['id']}")
                if not isinstance(queries, dict) or not queries or set(queries) - set(PILLARS):
                    raise ValueError(f"identity_query_context pillars must be valid in {scenario['id']}")
                if any(not isinstance(query, str) or not query.strip() for query in queries.values()):
                    raise ValueError(f"identity_query_context queries must be non-empty strings in {scenario['id']}")
    gap_ids = [gap.get("id") for gap in data.get("known_gaps", [])]
    if len(gap_ids) != len(set(gap_ids)) or not all(gap_ids):
        raise ValueError("known gap ids must be present and unique")
    for gap in data.get("known_gaps", []):
        if gap.get("scenario") not in ids:
            raise ValueError(f"known gap {gap.get('id')} names an unknown scenario")
        checks = gap.get("checks")
        if not isinstance(checks, list) or not checks or not set(checks) <= KNOWN_CHECKS:
            raise ValueError(f"known gap {gap.get('id')} names unknown checks")
        if not str(gap.get("reason", "")).strip():
            raise ValueError(f"known gap {gap.get('id')} needs a reason")
    return data


class _LiveInputError(ValueError):
    """Internal stable error code; raw input details never reach the report."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _has_forbidden_live_data(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).strip().lower() in LIVE_FORBIDDEN_KEYS:
                return True
            if _has_forbidden_live_data(item):
                return True
        return False
    if isinstance(value, list):
        return any(_has_forbidden_live_data(item) for item in value)
    return isinstance(value, str) and bool(SECRET_SHAPED.search(value))


def _safe_live_text(value: Any, *, limit: int = 256) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit and not CONTROL_CHARS.search(value)


def _live_timestamp(value: Any) -> bool:
    if not _safe_live_text(value):
        return False
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _live_currency(value: Any, pillar: str) -> bool:
    if pillar == "consumer":
        return value == LIVE_NOT_APPLICABLE_CURRENCY
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Z]{3}", value))


def _live_receipt_findings(receipt: Any, pillar: str, target: Mapping[str, Any], seen_ids: set[str]) -> set[str]:
    findings: set[str] = set()
    if not isinstance(receipt, Mapping):
        return {"malformed_receipt"}
    if _has_forbidden_live_data(receipt):
        findings.add("raw_or_secret_payload")
    missing = LIVE_REQUIRED_RECEIPT_FIELDS - set(receipt)
    if missing:
        findings.add("receipt_metadata_missing")
    for key in ("receipt_id", "provider_id", "source_type", "source_reference", "geography", "language", "candidate_id", "variant_id"):
        if not _safe_live_text(receipt.get(key)):
            findings.add("malformed_receipt")
    receipt_id = receipt.get("receipt_id")
    if isinstance(receipt_id, str):
        if receipt_id in seen_ids:
            findings.add("duplicate_receipt_id")
        seen_ids.add(receipt_id)
    if receipt.get("candidate_id") != target.get("candidate_id"):
        findings.add("candidate_binding_mismatch")
    if receipt.get("variant_id") != target.get("variant_id"):
        findings.add("variant_binding_mismatch")
    if receipt.get("geography") != target.get("geography") or receipt.get("language") != target.get("language"):
        findings.add("target_context_mismatch")
    source_markers = (str(receipt.get("provider_id", "")) + " " + str(receipt.get("source_type", ""))).lower()
    if any(marker in source_markers for marker in ("fixture", "manual", "simulated", "planned")):
        findings.add("non_live_receipt")
    if receipt.get("is_live") is not True or receipt.get("evidence_class") not in LIVE_EVIDENCE_CLASSES or receipt.get("evidence_mode") not in LIVE_RECEIPT_MODES:
        findings.add("non_live_receipt")
    freshness = receipt.get("freshness")
    if freshness not in FRESHNESS_STATES:
        findings.add("malformed_freshness")
    elif freshness != "fresh":
        findings.add(f"{freshness}_receipt")
    if not _live_timestamp(receipt.get("collected_at")):
        findings.add("collection_timestamp_missing_or_malformed")
    if not _live_currency(receipt.get("currency"), pillar):
        findings.add("currency_missing_or_malformed")
    return findings


def _live_report_findings(report: Any, pillar: str, target: Mapping[str, Any]) -> set[str]:
    findings: set[str] = set()
    if not isinstance(report, Mapping):
        return {f"missing_{pillar}_report"}
    if _has_forbidden_live_data(report):
        findings.add("raw_or_secret_payload")
    modes: set[str] = set()
    top_mode = report.get("evidence_mode")
    if top_mode is not None:
        modes.add(str(top_mode))
    raw_candidates = report.get("candidates")
    if not isinstance(raw_candidates, list):
        findings.add("malformed_report")
        return findings
    candidates = _candidates(dict(report))
    if not candidates:
        findings.add(f"missing_{pillar}_candidate")
    for candidate in candidates.values():
        candidate_mode = candidate.get("evidence_mode")
        if candidate_mode is not None:
            modes.add(str(candidate_mode))
        if candidate.get("candidate_id") != target.get("candidate_id"):
            findings.add("candidate_binding_mismatch")
        if "variant_id" in candidate and candidate.get("variant_id") != target.get("variant_id"):
            findings.add("variant_binding_mismatch")
        items = candidate.get(EVIDENCE_KEY[pillar], [])
        if not isinstance(items, list):
            findings.add("malformed_report")
            continue
        statuses = candidate.get("freshness_statuses", [])
        if not isinstance(statuses, list):
            findings.add("malformed_report")
        for item in items:
            if isinstance(item, Mapping) and item.get("evidence_mode") is not None:
                modes.add(str(item["evidence_mode"]))
    if not modes & LIVE_RECEIPT_MODES:
        findings.add(f"missing_{pillar}_live_mode")
    if any(mode in {"fixture", "fixture_demo", "manual", "manual_import", "manual_csv_import", "derived", "simulated", "planned"} for mode in modes):
        findings.add(f"non_live_{pillar}_evidence")
    return findings


def _read_live_packet(path: Path) -> dict[str, Any]:
    try:
        with Path(path).open("rb") as handle:
            raw = handle.read(LIVE_MAX_PACKET_BYTES + 1)
    except OSError as exc:
        raise _LiveInputError("live_input_unavailable") from exc
    if len(raw) > LIVE_MAX_PACKET_BYTES:
        raise _LiveInputError("live_input_oversized")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _LiveInputError("live_input_malformed") from exc
    if not isinstance(data, dict):
        raise _LiveInputError("live_input_malformed")
    return data


def load_live_packet(path: Path) -> dict[str, Any]:
    return _read_live_packet(path)


def _live_fingerprint(packet: Mapping[str, Any] | None) -> str | None:
    if packet is None or _has_forbidden_live_data(packet):
        return None
    try:
        encoded = json.dumps(packet, sort_keys=True).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def _live_blocked_report(blockers: set[str], *, packet: Mapping[str, Any] | None = None, counts: Mapping[str, int] | None = None) -> dict[str, Any]:
    return {
        "schema": LIVE_SCHEMA,
        "mode": "live_evidence",
        "input_sha256": _live_fingerprint(packet),
        "acceptance": {
            "accepted": False,
            "status": "blocked",
            "blockers": sorted(blockers),
            "required_pillars": list(PILLARS),
            "receipt_counts": dict(counts or {pillar: 0 for pillar in PILLARS}),
            "known_gaps_waived": False,
            "acceptance_basis": "sanitized_receipt_contract_only",
            "source_verified": False,
        },
        "diagnostic_outcome": None,
        "metrics": None,
        "read_only": True,
        "network_calls": False,
        "mutated": False,
        "provider_calls": False,
    }


def evaluate_live_packet(packet: Mapping[str, Any]) -> dict[str, Any]:
    blockers: set[str] = set()
    if not isinstance(packet, Mapping) or packet.get("schema") != LIVE_SCHEMA or packet.get("mode") != "live_evidence":
        return _live_blocked_report({"live_input_schema_mismatch"})
    if _has_forbidden_live_data(packet):
        return _live_blocked_report({"raw_or_secret_payload"})
    target = packet.get("target")
    if not isinstance(target, Mapping):
        return _live_blocked_report({"target_metadata_missing"}, packet=packet)
    required_target = ("candidate_id", "variant_id", "geography", "language")
    if any(not _safe_live_text(target.get(key)) for key in required_target):
        return _live_blocked_report({"target_metadata_missing_or_malformed"}, packet=packet)
    receipts = packet.get("receipts")
    reports = packet.get("reports")
    if not isinstance(receipts, Mapping) or not isinstance(reports, Mapping):
        return _live_blocked_report({"live_receipts_or_reports_missing"}, packet=packet)
    counts = {pillar: len(receipts.get(pillar, [])) if isinstance(receipts.get(pillar), list) else 0 for pillar in PILLARS}
    seen_ids: set[str] = set()
    for pillar in PILLARS:
        pillar_receipts = receipts.get(pillar)
        if not isinstance(pillar_receipts, list) or not pillar_receipts:
            blockers.add(f"missing_{pillar}_receipts")
            continue
        if len(pillar_receipts) > LIVE_MAX_RECEIPTS_PER_PILLAR:
            blockers.add("too_many_receipts")
        for receipt in pillar_receipts:
            blockers.update(_live_receipt_findings(receipt, pillar, target, seen_ids))
        blockers.update(_live_report_findings(reports.get(pillar), pillar, target))
    if blockers:
        return _live_blocked_report(blockers, packet=packet, counts=counts)

    inputs = {pillar: copy.deepcopy(reports[pillar]) for pillar in PILLARS}
    snapshot = copy.deepcopy(inputs)
    metrics = measure(inputs, identity_query_context=packet.get("identity_query_context"))
    if inputs != snapshot:
        raise RuntimeError("measure mutated live evidence inputs")
    result = build_product_opportunity_synthesis(inputs["marketplace"], inputs["supplier"], inputs["consumer"]).to_dict()
    if inputs != snapshot:
        raise RuntimeError("synthesis mutated live evidence inputs")
    out = outcome(result)
    if metrics["currency_unstated_items"]:
        blockers.add("currency_missing_or_malformed")
    if metrics["currency_unreconciled"]:
        blockers.add("currency_conflict")
    if metrics["identity_conflicts"]:
        blockers.add("identity_conflict")
    if metrics["price_conflicts"]:
        blockers.add("price_conflict")
    if metrics["incomplete_items"]:
        blockers.add("incomplete_viability_evidence")
    freshness_total = sum(metrics["freshness"][state] for state in ("stale", "future_dated", "unavailable"))
    if freshness_total:
        blockers.add("non_fresh_evidence")
    accepted = not blockers
    return {
        "schema": LIVE_SCHEMA,
        "mode": "live_evidence",
        "input_sha256": _live_fingerprint(packet),
        "acceptance": {
            "accepted": accepted,
            "status": "accepted" if accepted else "blocked",
            "blockers": sorted(blockers),
            "required_pillars": list(PILLARS),
            "receipt_counts": counts,
            "known_gaps_waived": False,
            "acceptance_basis": "sanitized_receipt_contract_only",
            "source_verified": False,
        },
        # This remains the canonical synthesis recommendation for diagnosis only; it does not
        # authorize a launch, supplier, payment, advertising, or other external action.
        "diagnostic_outcome": out,
        "metrics": metrics,
        "read_only": True,
        "network_calls": False,
        "mutated": False,
        "provider_calls": False,
    }


def evaluate_live_file(path: Path) -> dict[str, Any]:
    try:
        return evaluate_live_packet(load_live_packet(path))
    except _LiveInputError as exc:
        return _live_blocked_report({exc.code})


def _resolve_report(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        if not value.startswith(FIXTURE_PREFIX) or ".." in value or not value.endswith(".json"):
            raise ValueError("fixture references must be repository fixture JSON paths")
        return json.loads((ROOT / value).read_text(encoding="utf-8"))
    if isinstance(value, dict):
        return copy.deepcopy(value)
    raise ValueError("pillar must be null, a fixture path, or an inline object")


def _norm(text: Any) -> str:
    return " ".join(str(text or "").lower().split())


def _candidates(report: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(report, dict):
        return {}
    return {str(item["candidate_id"]): item for item in report.get("candidates", []) if isinstance(item, dict) and item.get("candidate_id")}


def _identity_conflict(
    candidate_id: str,
    present: list[str],
    maps: dict[str, dict[str, dict[str, Any]]],
    identity_query_context: Mapping[str, Mapping[str, str]] | None,
) -> bool:
    """Treat declared pillar-specific runner queries as context, not identity evidence.

    A brief-driven runner intentionally asks different queries for each evidence pillar. When
    the packet declares those exact planned queries, compare observed values to that context;
    an observed deviation remains a non-waivable identity conflict. Missing or partial context
    keeps the original conservative cross-pillar comparison.
    """
    observed = {pillar: _norm(maps[pillar][candidate_id].get("query")) for pillar in present}
    expected = (identity_query_context or {}).get(candidate_id)
    if isinstance(expected, Mapping) and all(pillar in expected for pillar in present):
        return any(observed[pillar] != _norm(expected[pillar]) for pillar in present)
    return len(set(observed.values())) > 1


def _economics(candidate: dict[str, Any] | None) -> dict[str, Any]:
    score = (candidate or {}).get("score", {})
    economics = score.get("economics", {}) if isinstance(score, dict) else {}
    return economics if isinstance(economics, dict) else {}


def _market_band(candidate: dict[str, Any] | None) -> tuple[float, float] | None:
    prices: list[float] = []
    for item in (candidate or {}).get("evidence", []):
        if not isinstance(item, dict):
            continue
        for key in ("price", "price_band_min", "price_band_max"):
            value = item.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
                prices.append(float(value))
    return (min(prices), max(prices)) if prices else None


def _freshness_class(statuses: list[str]) -> str:
    if not statuses:
        return "unrepresented"
    if "stale" in statuses:
        return "stale"
    if "future_dated" in statuses:
        return "future_dated"
    # Conservative: any unavailable observation means the source is not fully fresh.
    if "unavailable" in statuses:
        return "unavailable"
    return "fresh"


def measure(
    reports: dict[str, dict[str, Any] | None],
    *,
    identity_query_context: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    maps = {pillar: _candidates(reports.get(pillar)) for pillar in PILLARS}
    pillars_supplied = sum(1 for pillar in PILLARS if maps[pillar])
    effective_pillars = 0
    required_total = required_present = incomplete_items = 0
    currency_unstated = 0
    freshness = {"fresh": 0, "stale": 0, "future_dated": 0, "unavailable": 0, "unrepresented": 0}
    pillar_warnings: list[str] = []
    for pillar in PILLARS:
        report = reports.get(pillar) or {}
        pillar_warnings += [f"{pillar}:{item}" for item in report.get("warnings", []) if isinstance(item, str)]
        live = False
        for candidate in maps[pillar].values():
            pillar_warnings += [f"{pillar}:{item}" for item in candidate.get("warnings", []) if isinstance(item, str)]
            items = [item for item in candidate.get(EVIDENCE_KEY[pillar], []) if isinstance(item, dict)]
            for item in items:
                fields = REQUIRED_FIELDS[pillar]
                present = sum(1 for field in fields if item.get(field) not in (None, ""))
                required_total += len(fields)
                required_present += present
                if present < len(fields):
                    incomplete_items += 1
                if pillar != "consumer" and not item.get("currency"):
                    currency_unstated += 1
            if pillar == "consumer":
                status_class = _freshness_class([item for item in candidate.get("freshness_statuses", []) if item in FRESHNESS_STATES])
            else:
                status_class = "unrepresented"
            freshness[status_class] += 1
            if items and status_class != "unavailable":
                live = True
        if live:
            effective_pillars += 1

    identity_conflicts: list[str] = []
    currency_unreconciled: list[str] = []
    price_conflicts: list[str] = []
    all_ids = sorted(set().union(*(set(maps[pillar]) for pillar in PILLARS)))
    for candidate_id in all_ids:
        present = [pillar for pillar in PILLARS if candidate_id in maps[pillar]]
        if len(present) > 1 and _identity_conflict(candidate_id, present, maps, identity_query_context):
            identity_conflicts.append(candidate_id)
        currencies: set[str] = set()
        for pillar in ("marketplace", "supplier"):
            if candidate_id in maps[pillar]:
                for item in maps[pillar][candidate_id].get(EVIDENCE_KEY[pillar], []):
                    if isinstance(item, dict) and item.get("currency"):
                        currencies.add(str(item["currency"]).upper())
        if len(currencies) > 1:
            currency_unreconciled.append(candidate_id)
        band = _market_band(maps["marketplace"].get(candidate_id))
        target = _economics(maps["supplier"].get(candidate_id)).get("target_sell_price")
        if band and isinstance(target, (int, float)) and not isinstance(target, bool) and (target < band[0] or target > band[1]):
            price_conflicts.append(candidate_id)

    return {
        "pillars_supplied": pillars_supplied,
        "supplier_present": bool(maps["supplier"]),
        "effective_pillars": effective_pillars,
        "completeness": round(required_present / required_total, 4) if required_total else None,
        "incomplete_items": incomplete_items,
        "currency_unstated_items": currency_unstated,
        "currency_unreconciled": currency_unreconciled,
        "identity_conflicts": identity_conflicts,
        "price_conflicts": price_conflicts,
        "freshness": freshness,
        "pillar_warnings": sorted(pillar_warnings),
    }


def _caution_strings(result: dict[str, Any]) -> list[str]:
    strings: list[str] = []
    for candidate in result.get("candidates", []):
        risk = candidate["score"]["risk_profile"]
        for key in ("blockers", "supplier_risks", "marketplace_risks", "consumer_risks"):
            strings += list(risk.get(key, []))
        strings += list(candidate["decision_thresholds"].get("assumptions", []))
    strings += list(result.get("alias_notes", []))
    return [str(item) for item in strings]


def _flagged(strings: list[str], category: str, supplier_present: bool = False) -> bool:
    codes = CAUTION_CODES[category]
    if category == "incomplete" and supplier_present:
        codes = codes | ECONOMICS_MISSING_CODES
    return any(item in codes for item in strings)


def _surfaced(warning: str, strings: list[str]) -> bool:
    return warning.split(":", 1)[1] in strings


def outcome(result: dict[str, Any]) -> dict[str, Any]:
    top_risk = result.get("risk_profile", {})
    return {
        "overall_recommendation": result["overall_recommendation"],
        "confidence_grade": result["confidence_grade"],
        "next_best_action": result["next_best_action"],
        "candidate_count": result["candidate_count"],
        "candidate_ids": [item["candidate_id"] for item in result["candidates"]],
        "reported_pillars_supplied": sum(1 for key in ("marketplace", "supplier", "consumer_attention") if result["source_reports"].get(key) == "supplied"),
        "alias_notes": list(result["alias_notes"]),
        "top_blockers": list(top_risk.get("blockers", [])),
        "top_assumptions": list(result["decision_thresholds"].get("assumptions", [])),
        "read_only": result["read_only"],
        "network_calls": result["network_calls"],
        "mutated": result["mutated"],
    }


def _check(name: str, passed: bool | None, detail: str = "") -> dict[str, Any]:
    return {"name": name, "passed": passed, "detail": detail}


def run_checks(expect: dict[str, Any], metrics: dict[str, Any], out: dict[str, Any], result: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    strings = _caution_strings(result)
    if "expected_metrics" in expect:
        observed = {
            "currency_unreconciled": len(metrics["currency_unreconciled"]),
            "identity_conflicts": len(metrics["identity_conflicts"]),
            "price_conflicts": len(metrics["price_conflicts"]),
            "incomplete_items": metrics["incomplete_items"],
            "pillar_warnings": len(metrics["pillar_warnings"]),
        }
        mismatched = {key: (observed[key], value) for key, value in expect["expected_metrics"].items() if observed.get(key) != value}
        checks.append(_check("harness_metrics_match", not mismatched, json.dumps(mismatched, sort_keys=True) if mismatched else "matched"))
    if "expected_coverage" in expect:
        checks.append(_check("expected_coverage", metrics["pillars_supplied"] == expect["expected_coverage"], f"observed={metrics['pillars_supplied']} expected={expect['expected_coverage']}"))
    if expect.get("reported_coverage_matches_effective"):
        ok = out["reported_pillars_supplied"] == metrics["effective_pillars"]
        checks.append(_check("reported_coverage_matches_effective", ok, f"reported={out['reported_pillars_supplied']} effective={metrics['effective_pillars']}"))
    if "expected_recommendation" in expect:
        checks.append(_check("expected_recommendation", out["overall_recommendation"] == expect["expected_recommendation"], f"observed={out['overall_recommendation']}"))
    if expect.get("must_not_advance"):
        checks.append(_check("must_not_advance", out["overall_recommendation"] != ADVANCE, f"observed={out['overall_recommendation']}"))
    if out["overall_recommendation"] == ADVANCE:
        checks.append(_check("advance_must_be_draft_only", out["next_best_action"] == DRAFT_ACTION, f"next_action={out['next_best_action']}"))
    if "max_grade" in expect:
        ceiling = expect["max_grade"]
        checks.append(_check("max_grade", GRADE_RANK[out["confidence_grade"]] <= GRADE_RANK[ceiling], f"observed={out['confidence_grade']} ceiling={ceiling}"))
    if expect.get("required_blockers"):
        missing = sorted(set(expect["required_blockers"]) - set(out["top_blockers"]))
        checks.append(_check("required_blockers", not missing, f"missing={missing}" if missing else "present"))
    if expect.get("assumptions_must_include"):
        missing = sorted(set(expect["assumptions_must_include"]) - set(out["top_assumptions"]))
        checks.append(_check("assumptions_must_include", not missing, f"missing={missing}" if missing else "present"))
    if "min_alias_notes" in expect:
        checks.append(_check("min_alias_notes", len(out["alias_notes"]) >= expect["min_alias_notes"], f"observed={len(out['alias_notes'])}"))
    if "retained_candidates" in expect:
        missing = sorted(set(expect["retained_candidates"]) - set(out["candidate_ids"]))
        checks.append(_check("retained_candidates", not missing, f"missing={missing}" if missing else "retained"))
    checks.append(_check(
        "non_authorization",
        out["read_only"] is True and out["network_calls"] is False and out["mutated"] is False and out["next_best_action"] in NON_EXECUTING_ACTIONS,
        f"next_action={out['next_best_action']}",
    ))

    observed_counts = {
        "currency": len(metrics["currency_unreconciled"]),
        "identity": len(metrics["identity_conflicts"]),
        "freshness": metrics["freshness"]["stale"] + metrics["freshness"]["future_dated"] + metrics["freshness"]["unavailable"],
        "price": len(metrics["price_conflicts"]),
        "incomplete": metrics["incomplete_items"],
    }
    for category, count in observed_counts.items():
        if count:
            flagged = _flagged(strings, category, supplier_present=metrics["supplier_present"])
            checks.append(_check(f"{category}_flagged", flagged, f"{category} observations={count}"))
        else:
            checks.append(_check(f"{category}_flagged", None, "not_applicable"))
    if metrics["currency_unreconciled"]:
        checks.append(
            _check(
                "currency_safety_invariant",
                out["overall_recommendation"] not in NON_ADVANCING_RECOMMENDATIONS,
                f"currency_conflicts={metrics['currency_unreconciled']} recommendation={out['overall_recommendation']}",
            )
        )
    if metrics["identity_conflicts"]:
        checks.append(
            _check(
                "identity_safety_invariant",
                out["overall_recommendation"] not in NON_ADVANCING_RECOMMENDATIONS,
                f"identity_conflicts={metrics['identity_conflicts']} recommendation={out['overall_recommendation']}",
            )
        )
    if metrics["freshness"]["stale"]:
        checks.append(
            _check(
                "stale_evidence_safety_invariant",
                out["overall_recommendation"] not in NON_ADVANCING_RECOMMENDATIONS,
                f"stale_observations={metrics['freshness']['stale']} recommendation={out['overall_recommendation']}",
            )
        )
    if metrics["price_conflicts"]:
        checks.append(
            _check(
                "price_safety_invariant",
                out["overall_recommendation"] not in NON_ADVANCING_RECOMMENDATIONS,
                f"price_conflicts={metrics['price_conflicts']} recommendation={out['overall_recommendation']}",
            )
        )
    if metrics["incomplete_items"]:
        checks.append(
            _check(
                "incomplete_evidence_safety_invariant",
                out["overall_recommendation"] not in NON_ADVANCING_RECOMMENDATIONS,
                f"incomplete_items={metrics['incomplete_items']} recommendation={out['overall_recommendation']}",
            )
        )
    if metrics["pillar_warnings"]:
        missing = [item for item in metrics["pillar_warnings"] if not _surfaced(item, strings)]
        checks.append(_check("pillar_warnings_surfaced", not missing, f"unsurfaced={missing}" if missing else "surfaced"))
    else:
        checks.append(_check("pillar_warnings_surfaced", None, "not_applicable"))
    return checks


def _gap_index(packet: dict[str, Any]) -> dict[tuple[str, str], str]:
    index: dict[tuple[str, str], str] = {}
    for gap in packet.get("known_gaps", []):
        for check in gap.get("checks", []):
            key = (gap["scenario"], check)
            if key in index:
                raise ValueError(f"duplicate known gap for {key}")
            index[key] = gap["id"]
    return index


def evaluate_packet(packet: dict[str, Any], *, only: set[str] | None = None) -> dict[str, Any]:
    gaps = _gap_index(packet)
    all_ids = {scenario["id"] for scenario in packet["scenarios"]}
    if only:
        unknown = sorted(only - all_ids)
        if unknown:
            raise ValueError(f"unknown scenario ids: {unknown}")
    scenarios: list[dict[str, Any]] = []
    unexpected: list[str] = []
    tallies = {"total": 0, "pass": 0, "known_gap": 0, "unexpected_fail": 0, "not_applicable": 0}
    false_ready: list[str] = []
    false_confidence: list[str] = []
    coverage_sum = 0
    completeness_values: list[float] = []
    freshness_totals = {"fresh": 0, "stale": 0, "future_dated": 0, "unavailable": 0, "unrepresented": 0}
    totals = {"identity_conflicts": 0, "currency_unreconciled": 0, "price_conflicts": 0, "incomplete_items": 0, "pillar_warnings_input": 0, "pillar_warnings_surfaced": 0}
    for scenario in packet["scenarios"]:
        if only and scenario["id"] not in only:
            continue
        inputs = {pillar: _resolve_report(scenario.get(pillar)) for pillar in PILLARS}
        snapshot = copy.deepcopy(inputs)
        metrics = measure(inputs, identity_query_context=scenario.get("identity_query_context"))
        if inputs != snapshot:
            raise RuntimeError(f"measure mutated inputs for {scenario['id']}")
        # The synthesis receives the same objects the snapshot was taken from, so a mutating
        # synthesis is detected here rather than masked by copies.
        result = build_product_opportunity_synthesis(inputs["marketplace"], inputs["supplier"], inputs["consumer"]).to_dict()
        if inputs != snapshot:
            raise RuntimeError(f"synthesis mutated inputs for {scenario['id']}")
        out = outcome(result)
        expect = scenario.get("expectations", {})
        checks = run_checks(expect, metrics, out, result)
        strings = _caution_strings(result)
        surfaced = [item for item in metrics["pillar_warnings"] if _surfaced(item, strings)]
        scenario_checks = []
        for check in checks:
            entry = {"name": check["name"], "detail": check["detail"]}
            if check["passed"] is None:
                entry["status"] = "not_applicable"
                tallies["not_applicable"] += 1
            elif check["passed"]:
                entry["status"] = "pass"
                tallies["pass"] += 1
            else:
                gap_id = gaps.get((scenario["id"], check["name"]))
                if gap_id and check["name"] not in HARD_SAFETY_CHECKS:
                    entry["status"] = "known_gap"
                    entry["gap"] = gap_id
                    tallies["known_gap"] += 1
                else:
                    entry["status"] = "unexpected_fail"
                    tallies["unexpected_fail"] += 1
                    unexpected.append(f"{scenario['id']}:{check['name']}")
            if check["passed"] is not None:
                tallies["total"] += 1
            scenario_checks.append(entry)
        if expect.get("must_not_advance") and out["overall_recommendation"] == ADVANCE:
            false_ready.append(scenario["id"])
        if "max_grade" in expect and GRADE_RANK[out["confidence_grade"]] > GRADE_RANK[expect["max_grade"]]:
            false_confidence.append(scenario["id"])
        coverage_sum += metrics["pillars_supplied"]
        if metrics["completeness"] is not None:
            completeness_values.append(metrics["completeness"])
        for key, value in metrics["freshness"].items():
            freshness_totals[key] += value
        totals["identity_conflicts"] += len(metrics["identity_conflicts"])
        totals["currency_unreconciled"] += len(metrics["currency_unreconciled"])
        totals["price_conflicts"] += len(metrics["price_conflicts"])
        totals["incomplete_items"] += metrics["incomplete_items"]
        totals["pillar_warnings_input"] += len(metrics["pillar_warnings"])
        totals["pillar_warnings_surfaced"] += len(surfaced)
        scenarios.append({
            "id": scenario["id"],
            "category": scenario.get("category", ""),
            "metrics": metrics,
            "outcome": out,
            "checks": scenario_checks,
        })

    count = len(scenarios)
    digest = hashlib.sha256(json.dumps(packet, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "schema": SCHEMA,
        "packet_sha256": digest,
        "synthesis_report_version": "product-opportunity-synthesis-v1",
        "scenario_count": count,
        "checks": tallies,
        "aggregate": {
            "mean_pillars_supplied": round(coverage_sum / count, 4) if count else None,
            "mean_completeness": round(sum(completeness_values) / len(completeness_values), 4) if completeness_values else None,
            "freshness": freshness_totals,
            "totals": totals,
            "false_ready_scenarios": sorted(false_ready),
            "false_confidence_scenarios": sorted(false_confidence),
            "unexpected_failures": sorted(unexpected),
        },
        "known_gaps": [
            {"id": gap["id"], "scenario": gap["scenario"], "checks": list(gap["checks"]), "reason": gap["reason"]}
            for gap in packet.get("known_gaps", [])
        ],
        "scenarios": scenarios,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, default=PACKET_PATH, help="evaluation packet JSON")
    parser.add_argument("--mode", choices=("fixture", "live_evidence"), default="fixture", help="input acceptance mode")
    parser.add_argument("--scenario", action="append", default=[], help="limit to one scenario id (repeatable)")
    parser.add_argument("--output", type=Path, help="optional path to write the JSON report")
    args = parser.parse_args(argv)
    if args.mode == "live_evidence":
        if args.scenario:
            report = _live_blocked_report({"scenario_filter_not_supported_in_live_mode"})
        else:
            report = evaluate_live_file(args.packet)
    else:
        report = evaluate_packet(load_packet(args.packet), only=set(args.scenario) or None)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    if args.mode == "live_evidence":
        return 0 if report["acceptance"]["accepted"] else 2
    return 0 if report["checks"]["unexpected_fail"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
