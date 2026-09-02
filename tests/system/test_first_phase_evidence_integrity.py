"""Adversarial first-phase evidence integrity suite.

Owns market → consumer → supplier → synthesis contracts plus optional
assertions for PR #225 and PR #228 when those files exist. Does not edit
implementation files owned by other lanes.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis
from evaluation.commerce.product_validation_report import generate as generate_product_validation
from evaluation.companyos.resource_execution_governor import (
    ExecutionDecisionRequest,
    evaluate_execution_request,
)
from evaluation.trustos.gate_runner import evaluate_action as evaluate_trustos_action

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "first_phase_evidence_integrity"
RUNNER = ROOT / "scripts" / "operators" / "run_first_phase_intelligence.ps1"
SECRET_MARKERS = (
    "sk-",
    "api_key",
    "bearer ",
    "raw operator prompt",
    "ghp_",
    "begin private",
    "sk-nested-synthetic-must-not-leak",
    "internal prompt nested",
    "nested-raw",
)
TRUSTOS_ACTIONS = (
    "public_beta_launch",
    "publish_site",
    "launch_ad",
    "client_workspace_export",
)


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf8"))


def aligned_pillars() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return (
        load("aligned_marketplace.json"),
        load("aligned_supplier.json"),
        load("aligned_consumer.json"),
    )


def fingerprint(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf8")
    return hashlib.sha256(blob).hexdigest()


def cycle_module():
    try:
        return import_module("evaluation.commerce.commerce_operations_cycle")
    except ModuleNotFoundError:
        return None


def test_fixture_pack_is_sanitized():
    allow_secret_files = {
        "secret_like_input.json",
        "nested_secret_marketplace.json",
    }
    for path in FIXTURES.iterdir():
        if path.suffix != ".json" or path.name in allow_secret_files:
            continue
        text = path.read_text(encoding="utf8").lower()
        assert "sk-" not in text
        assert "bearer " not in text


def test_stable_candidate_identity_across_pillars():
    report = build_product_opportunity_synthesis(*aligned_pillars()).to_dict()
    assert {item["candidate_id"] for item in report["candidates"]} == {"desk-clamp-lamp"}
    assert report["top_candidate_id"] == "desk-clamp-lamp"
    matrix = report["candidates"][0]["evidence_matrix"]
    assert matrix["marketplace"]["status"] == "supplied"
    assert matrix["supplier"]["status"] == "supplied"
    assert matrix["consumer"]["status"] == "supplied"


def test_duplicate_candidate_id_in_one_pillar_is_collapsed():
    market = load("duplicate_ids_marketplace.json")
    _, supplier, consumer = aligned_pillars()
    report = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    assert report["candidate_count"] == 1
    assert [item["candidate_id"] for item in report["candidates"]] == ["desk-clamp-lamp"]


def test_source_family_aliases_are_still_double_counted():
    """Documents SYN-ALIAS-NO-COLLAPSE. Do not patch synthesis in this PR."""
    market = load("correlated_alias_marketplace.json")
    _, supplier, consumer = aligned_pillars()
    report = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    ids = {item["candidate_id"] for item in report["candidates"]}
    assert "desk-clamp-lamp" in ids
    assert "desk-clamp-lamp-amazon-mirror" in ids
    assert report["candidate_count"] == 2


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECT SYN-ALIAS-NO-COLLAPSE owner=opportunity-synthesis; "
        "same query+source_family should not mint a second scored candidate"
    ),
)
def test_source_family_aliases_should_collapse_to_one_candidate():
    market = load("correlated_alias_marketplace.json")
    _, supplier, consumer = aligned_pillars()
    report = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    assert report["candidate_count"] == 1


def test_market_evidence_is_not_supplier_proof():
    market, _, consumer = aligned_pillars()
    report = build_product_opportunity_synthesis(market, None, consumer).to_dict()
    assert report["source_reports"]["supplier"] == "missing"
    assert report["overall_recommendation"] == "validate_supplier_first"
    assert "supplier_proof_missing" in report["risk_profile"]["blockers"]
    assert "order_created" not in json.dumps(report)
    assert report["confidence_grade"] != "A_live_validated"


def test_consumer_attention_is_not_ad_authorization():
    report = build_product_opportunity_synthesis(*aligned_pillars()).to_dict()
    assert report["top_ad_angles"]
    assert report["overall_recommendation"] != "launch_ad"
    assert "ad_authorized" not in json.dumps(report)


def test_supplier_evidence_is_not_order_or_fulfillment_authority():
    report = build_product_opportunity_synthesis(*aligned_pillars()).to_dict()
    blob = json.dumps(report)
    assert "fulfillment_authorized" not in blob
    assert "order_created" not in blob
    assert report["decision_thresholds"]["supplier_validation_required"] is True


def test_missing_provenance_does_not_upgrade_grade():
    _, supplier, consumer = aligned_pillars()
    report = build_product_opportunity_synthesis(
        load("missing_provenance_marketplace.json"), supplier, consumer
    ).to_dict()
    assert report["confidence_grade"] != "A_live_validated"
    assert report["evidence_mode"] == "fixture_demo"


def test_malformed_missing_candidate_id_is_ignored_not_invented():
    _, supplier, consumer = aligned_pillars()
    report = build_product_opportunity_synthesis(
        load("malformed_missing_candidate_id.json"), supplier, consumer
    ).to_dict()
    assert report["top_candidate_id"] == "desk-clamp-lamp"
    assert all(item.get("candidate_id") for item in report["candidates"])


def test_conflicting_economics_block_advance():
    market, _, consumer = aligned_pillars()
    report = build_product_opportunity_synthesis(
        market, load("conflicting_supplier.json"), consumer
    ).to_dict()
    assert report["overall_recommendation"] == "reject_poor_margin"
    assert report["confidence_grade"] == "F_reject_or_missing"


def test_stale_evidence_is_not_live_validated():
    _, supplier, consumer = aligned_pillars()
    report = build_product_opportunity_synthesis(
        load("stale_marketplace.json"), supplier, consumer
    ).to_dict()
    assert report["confidence_grade"] != "A_live_validated"
    assert report["evidence_mode"] == "fixture_demo"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECT SYN-GRADE-LIVE-LABEL owner=opportunity-synthesis; "
        "_grade promotes live_readonly fixture labels to A_live_validated"
    ),
)
def test_live_labeled_fixture_must_not_become_professional_authorization():
    market = load("live_labeled_marketplace.json")
    _, supplier, consumer = aligned_pillars()
    report = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    assert report["confidence_grade"] != "A_live_validated"


def test_provider_terms_block_is_visible_in_risks():
    market, _, consumer = aligned_pillars()
    report = build_product_opportunity_synthesis(
        market, load("terms_blocked_supplier.json"), consumer
    ).to_dict()
    assert "provider_terms_or_privacy_block" in report["risk_profile"]["blockers"]
    assert report["overall_recommendation"] != "advance_to_launch_draft"


def test_trustos_blockers_recur_across_external_actions():
    decisions = {}
    for action in TRUSTOS_ACTIONS:
        payload = evaluate_trustos_action(action, generated_at="deterministic").to_dict()
        decisions[action] = payload["decision"]
        assert payload["decision"] != "allow"
    second = evaluate_trustos_action("launch_ad", generated_at="deterministic").to_dict()
    assert second["decision"] == decisions["launch_ad"]


def test_governor_blocks_frontier_spend_and_portfolio_pressure():
    spend = evaluate_execution_request(
        ExecutionDecisionRequest(
            request_id="first-phase-spend",
            action_type="launch_ad",
            domain="advertising",
            owner_department="growth",
            workspace_id="internal-companyos",
            requested_amount=250.0,
            resource_type="ad_spend",
            model_tier="frontier",
            opportunity_score=0.2,
            supplier_score=0.1,
            attention_score=0.1,
            evidence_score=0.1,
            unit_economics_score=0.0,
            supplier_proof=False,
            approval_state="not_requested",
            trustos_decision="blocked",
            workspace_decision="allow",
        )
    ).to_dict()
    model = evaluate_execution_request(
        ExecutionDecisionRequest(
            request_id="first-phase-model",
            action_type="run_provider_readonly_call",
            domain="intelligence",
            owner_department="intelligence",
            workspace_id="internal-companyos",
            requested_amount=0.0,
            resource_type="model_inference_quota",
            model_tier="frontier",
            opportunity_score=0.2,
            supplier_score=0.1,
            attention_score=0.1,
            evidence_score=0.1,
            unit_economics_score=0.0,
            supplier_proof=False,
            approval_state="not_requested",
            trustos_decision="blocked",
            workspace_decision="allow",
        )
    ).to_dict()
    assert spend["outcome"] != "allow"
    assert model["outcome"] != "allow"


def test_secret_like_values_must_not_appear_in_synthesis_output():
    _, supplier, consumer = aligned_pillars()
    report = build_product_opportunity_synthesis(
        load("secret_like_input.json"), supplier, consumer
    ).to_dict()
    blob = json.dumps(report).lower()
    assert "sk-synthetic-must-not-leak" not in blob
    assert "raw operator prompt must not persist" not in blob


def test_nested_secret_like_values_must_not_appear_in_synthesis_output():
    _, supplier, consumer = aligned_pillars()
    report = build_product_opportunity_synthesis(
        load("nested_secret_marketplace.json"), supplier, consumer
    ).to_dict()
    blob = json.dumps(report).lower()
    assert "sk-nested-synthetic-must-not-leak" not in blob
    assert "internal prompt nested" not in blob
    assert "nested-raw" not in blob


def test_generate_without_stubs_reaches_phase1_builders(monkeypatch):
    called = {"benchmark": False, "readiness": False}

    def _mark_benchmark(*_args, **_kwargs):
        called["benchmark"] = True

        class _Obj:
            def to_dict(self):
                return {"candidates": [], "evidence_mode": "fixture_demo"}

        return _Obj()

    def _mark_readiness(*_args, **_kwargs):
        called["readiness"] = True

        class _Obj:
            def to_dict(self):
                return {
                    "overall_status": "blocked",
                    "supplier_readiness": {"status": "unknown"},
                    "blocking_gates": ["harness"],
                    "next_best_action": "set_cj_credentials_and_run_validation_pack",
                }

        return _Obj()

    import evaluation.commerce.product_validation_report as pvr

    monkeypatch.setattr(pvr, "build_benchmark_from_paths", _mark_benchmark)
    monkeypatch.setattr(pvr, "build_from_paths", _mark_readiness)
    report = generate_product_validation().to_dict()
    assert called["benchmark"] is True
    assert called["readiness"] is True
    assert "cj" in " ".join(report.get("recommended_next_actions") or []).lower() or called["readiness"]


def test_generate_with_blocked_stubs_does_not_call_path_builders(monkeypatch):
    stubs = load("blocked_validation_stubs.json")

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("phase-1 path builder must not run when stubs are supplied")

    import evaluation.commerce.product_validation_report as pvr

    monkeypatch.setattr(pvr, "build_benchmark_from_paths", _forbidden)
    monkeypatch.setattr(pvr, "build_from_paths", _forbidden)
    monkeypatch.setattr(pvr, "build_readiness", _forbidden)
    market, supplier, consumer = aligned_pillars()
    synthesis = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    report = generate_product_validation(
        benchmark=stubs["benchmark"],
        readiness=stubs["readiness"],
        deployment=stubs["deployment"],
        marketplace_trends=market,
        supplier_feasibility=supplier,
        consumer_attention=consumer,
        opportunity_synthesis=synthesis,
    ).to_dict()
    assert report["source_reports"]["benchmark"] == "supplied"
    assert "set_cj_credentials" not in json.dumps(report).lower()
    assert report["overall_recommendation"] == synthesis["overall_recommendation"]


def test_replay_fingerprint_is_stable_across_repeated_runs():
    first = build_product_opportunity_synthesis(*aligned_pillars()).to_dict()
    second = build_product_opportunity_synthesis(*aligned_pillars()).to_dict()
    third = build_product_opportunity_synthesis(*aligned_pillars()).to_dict()
    assert fingerprint(first) == fingerprint(second) == fingerprint(third)
    assert first["generated_at"] == "deterministic"
    assert first["network_calls"] is False
    assert first["mutated"] is False


def test_draft_outputs_do_not_claim_external_mutation():
    report = build_product_opportunity_synthesis(*aligned_pillars()).to_dict()
    assert report["read_only"] is True
    assert report["network_calls"] is False
    assert report["mutated"] is False


def test_runner_summary_fixture_must_not_be_labeled_actual():
    summary = load("runner_summary_fixture_demo.json")
    assert summary["evidence_mode"] == "fixture_demo"
    assert summary["mutated"] is False
    assert summary["network_calls"] is False
    required = {"fixture_evidence", "fixture_demo", "simulated", "simulated_or_planned"}
    if summary["overall_classification"] == "actual":
        pytest.xfail(
            "DEFECT RUN-228-ACTUAL-ON-FIXTURE owner=windows-operator; "
            "captured #228-shaped summary labels fixture exit 0 as actual"
        )
    assert summary["overall_classification"] in required


@pytest.mark.skipif(not RUNNER.exists(), reason="PR #228 runner not present on this SHA")
@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECT RUN-228-ACTUAL-ON-FIXTURE owner=windows-operator; "
        "Get-StageClassification returns actual on exit 0 for fixture_demo"
    ),
)
def test_228_runner_source_must_not_map_fixture_success_to_actual():
    text = RUNNER.read_text(encoding="utf8")
    function = re.search(
        r"function Get-StageClassification \{[\s\S]*?\n\}",
        text,
    )
    assert function, "Get-StageClassification missing"
    body = function.group(0)
    assert "actual" not in body or "evidence_mode" in body
    assert 'return "actual"' not in body


@pytest.mark.skipif(cycle_module() is None, reason="PR #225 commerce cycle not present on this SHA")
def test_cycle_when_present_stays_plan_only_and_delegates_scores():
    cycle = cycle_module()
    market, supplier, consumer = aligned_pillars()
    expected = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    report = cycle.build_commerce_operations_cycle(market, supplier, consumer).to_dict()
    assert report["synthesis"]["combined_opportunity_score"] == expected["combined_opportunity_score"]
    assert report["live_validated"] is False
    assert report["governor"].get("live_go") is not True
    assert report["approval_ledger"].get("live_approval_granted") is not True
    assert report["launch_draft_readiness"].get("packs_written") is not True
    assert report["mutated"] is False
    assert report["network_calls"] is False


@pytest.mark.skipif(cycle_module() is None, reason="PR #225 commerce cycle not present on this SHA")
def test_cycle_when_present_rejects_secret_like_and_nested_secret_input():
    cycle = cycle_module()
    with pytest.raises(ValueError, match="secret-like or raw payload"):
        cycle.build_commerce_operations_cycle(load("secret_like_input.json"), None, None)
    with pytest.raises(ValueError, match="secret-like or raw payload"):
        cycle.build_commerce_operations_cycle(load("nested_secret_marketplace.json"), None, None)


@pytest.mark.skipif(cycle_module() is None, reason="PR #225 commerce cycle not present on this SHA")
def test_cycle_when_present_does_not_invoke_cj_path_builders(monkeypatch):
    cycle = cycle_module()
    import evaluation.commerce.product_validation_report as pvr

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("#225 must keep generate() on blocked stubs")

    monkeypatch.setattr(pvr, "build_benchmark_from_paths", _forbidden)
    monkeypatch.setattr(pvr, "build_from_paths", _forbidden)
    monkeypatch.setattr(pvr, "build_readiness", _forbidden)
    report = cycle.build_commerce_operations_cycle(*aligned_pillars()).to_dict()
    assert report["product_validation"]["status"] != "unavailable"
    assert report["product_validation"].get("live_go") is not True


def test_owned_suite_has_no_network_imports():
    tree = ast.parse(
        Path(__file__).read_text(encoding="utf8"),
        filename=str(Path(__file__)),
    )
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint({"httpx", "requests", "openai", "anthropic", "socket"})
    assert SECRET_MARKERS
