"""Deterministic, fixture-only evaluation of Product Opportunity Synthesis.

Measures whether the existing synthesis makes evidence-grounded, appropriately
cautious decisions on synthetic packets. It adds no score, changes no
threshold, makes no network call, and writes nothing unless --output is given.

Expectations in a packet are safety policy written before the run. A failing
expectation is reported as a known gap only when the packet names that exact
scenario and check. Any other failure is unexpected and fails the run.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis  # noqa: E402

SCHEMA = "MarketOS.ProductOpportunityResearchEval.v1"
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
# Caution vocabulary is searched only in risk lists, blockers, threshold assumptions and alias
# notes. The band dictionary is excluded, because its "currency" key is not a caution.
CAUTION_TOKENS = {
    "currency": ("currency_unreconciled", "currency_mismatch", "currency_assumed", "currency_missing"),
    "identity": ("identity_conflict", "variant_mismatch", "query_mismatch", "correlated alias"),
    "freshness": ("stale", "future_dated", "freshness", "unavailable"),
    "price": ("price_band_conflict", "target_outside_band", "price_conflict"),
    # "_missing" alone matches "supplier_readonly_proof_missing", which every fixture-mode candidate carries,
    # so only field-level missing cautions the synthesis actually emits are searched.
    "incomplete": ("incomplete_evidence", "target_sell_price_missing", "estimated_landed_cost_missing", "evidence_field_missing"),
}


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
    return data


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
    if all(item == "unavailable" for item in statuses):
        return "unavailable"
    return "fresh"


def measure(reports: dict[str, dict[str, Any] | None]) -> dict[str, Any]:
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
        if len(present) > 1 and len({_norm(maps[pillar][candidate_id].get("query")) for pillar in present}) > 1:
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


def _flagged(strings: list[str], category: str) -> bool:
    return any(token in item for item in strings for token in CAUTION_TOKENS[category])


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
            checks.append(_check(f"{category}_flagged", _flagged(strings, category), f"{category} observations={count}"))
        else:
            checks.append(_check(f"{category}_flagged", None, "not_applicable"))
    if metrics["pillar_warnings"]:
        missing = [item for item in metrics["pillar_warnings"] if item.split(":", 1)[1] not in " ".join(strings)]
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
        before = copy.deepcopy(inputs)
        metrics = measure(inputs)
        result = build_product_opportunity_synthesis(copy.deepcopy(inputs["marketplace"]), copy.deepcopy(inputs["supplier"]), copy.deepcopy(inputs["consumer"])).to_dict()
        if inputs != before:
            raise RuntimeError(f"synthesis mutated inputs for {scenario['id']}")
        out = outcome(result)
        expect = scenario.get("expectations", {})
        checks = run_checks(expect, metrics, out, result)
        strings = _caution_strings(result)
        surfaced = [item for item in metrics["pillar_warnings"] if item.split(":", 1)[1] in " ".join(strings)]
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
                if gap_id:
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
    parser.add_argument("--scenario", action="append", default=[], help="limit to one scenario id (repeatable)")
    parser.add_argument("--output", type=Path, help="optional path to write the JSON report")
    args = parser.parse_args(argv)
    report = evaluate_packet(load_packet(args.packet), only=set(args.scenario) or None)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if report["checks"]["unexpected_fail"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
