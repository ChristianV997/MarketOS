from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry
from services.opportunity_discovery import OpportunityDiscoveryError, load_payload, render_markdown, run_discovery


ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "opportunity_discovery"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def product() -> dict:
    return fixture("product_complete.json")


def ready_product() -> dict:
    payload = product()
    assumptions = payload["candidates"][0]["economics"]["assumptions"]
    for key in ("affiliate_fee_rate", "brokerage_fee", "cac", "domestic_shipping", "international_shipping", "payment_fee_fixed", "platform_fee_fixed"):
        assumptions[key] = {"amount": "0", "currency": "MXN"} if key in {"brokerage_fee", "cac", "domestic_shipping", "international_shipping", "payment_fee_fixed", "platform_fee_fixed"} else "0"
    return payload


def test_product_delegates_scoring_and_produces_stable_report() -> None:
    first = run_discovery("evaluate", product())
    second = run_discovery("evaluate", product())

    assert first.fingerprint == second.fingerprint
    assert first.execution_classification == "actual_executed"
    assert first.decisions[0].synthesis["authority"].endswith("build_product_opportunity_synthesis")
    assert set(first.decisions[0].scenarios) == {"best", "base", "worst"}
    assert first.safety["launch_authorized"] is False


def test_high_attention_negative_margin_is_blocked_before_synthesis_can_help() -> None:
    payload = product()
    payload["candidates"][0]["economics"]["product_cost"]["amount"] = "2000"

    report = run_discovery("evaluate", payload)

    assert report.decisions[0].recommendation == "blocked"
    assert "structurally_negative_economics" in report.decisions[0].fatal_gates


def test_missing_supplier_evidence_is_not_invented() -> None:
    payload = product()
    candidate = payload["candidates"][0]
    candidate["evidence"] = [item for item in candidate["evidence"] if item["area"] != "supply"]
    candidate["reports"].pop("supplier")

    report = run_discovery("evaluate", payload)

    assert "supply_unproven" in report.decisions[0].fatal_gates
    assert "supplier_evidence_unavailable" in report.decisions[0].evidence_gaps


def test_unavailable_freight_is_a_gap_not_zero_cost() -> None:
    payload = product()
    payload["candidates"][0]["economics"]["assumptions"].pop("supplier_shipping")

    report = run_discovery("evaluate", payload)
    decision = report.decisions[0]

    assert decision.recommendation == "needs_evidence"
    assert "shipping" in decision.evidence_gaps
    assert decision.scenarios["base"]["status"] == "unavailable"


def test_explicit_zero_shipping_is_distinct_from_missing_shipping() -> None:
    payload = product()
    payload["candidates"][0]["economics"]["assumptions"]["supplier_shipping"]["amount"] = "0"

    report = run_discovery("evaluate", payload)
    decision = report.decisions[0]

    assert "shipping" not in decision.evidence_gaps
    assert decision.scenarios["base"]["supplier_shipping"]["amount"] == "0"


def test_supplier_claim_cannot_become_verification() -> None:
    candidate = fixture("adversarial_cases.json")["candidates"][0]
    report = run_discovery("evaluate", {"candidates": [candidate]})

    assert "supplier_claim_not_verification" in report.decisions[0].fatal_gates
    assert "supplier_claim_not_verification" in report.decisions[0].blockers


def test_stale_and_conflicting_evidence_are_preserved_as_blockers() -> None:
    payload = product()
    payload["candidates"][0]["evidence"].append({
        "evidence_id": "stale-competition",
        "area": "competition",
        "status": "observed_fact",
        "evidence_class": "observed",
        "source_type": "operator",
        "source_ref": "manual://competition",
        "freshness": "stale",
        "conflicting": True,
    })

    decision = run_discovery("evaluate", payload).decisions[0]

    assert "competition_evidence_stale" in decision.evidence_gaps
    assert "conflicting_competition_evidence" in decision.blockers


def test_future_evidence_is_not_treated_as_current() -> None:
    payload = product()
    payload["candidates"][0]["evidence"][0]["freshness"] = "future"

    decision = run_discovery("evaluate", payload).decisions[0]

    assert "demand_evidence_future" in decision.evidence_gaps
    assert "future_dated_evidence" in decision.blockers
    assert decision.readiness == "not_ready"


def test_synthesis_rejects_a_report_bound_to_another_candidate() -> None:
    payload = product()
    payload["candidates"][0]["reports"]["marketplace"]["candidates"][0]["candidate_id"] = "different-candidate"

    decision = run_discovery("evaluate", payload).decisions[0]

    assert decision.recommendation == "blocked"
    assert "report_candidate_identity_mismatch" in decision.fatal_gates
    assert "malformed_synthesis_report" in decision.evidence_gaps


def test_discover_ranks_multiple_candidates_by_canonical_synthesis_score() -> None:
    first = ready_product()["candidates"][0]
    second = copy.deepcopy(first)
    second["candidate_id"] = "higher-scoring-lamp"
    second["name"] = "Higher scoring lamp"
    for report in second["reports"].values():
        for item in report["candidates"]:
            item["candidate_id"] = "higher-scoring-lamp"
    second["reports"]["marketplace"]["candidates"][0]["score"]["overall_marketplace_opportunity"] = 0.95
    second["reports"]["supplier"]["candidates"][0]["score"]["overall_supplier_feasibility"] = 0.95
    second["reports"]["consumer"]["candidates"][0]["score"]["overall_consumer_attention"] = 0.95

    report = run_discovery("discover", {"candidates": [first, second]})

    assert report.ranked_candidate_ids == ("higher-scoring-lamp", "desk-lamp")
    assert report.decisions[0].metrics["synthesis_score"] != report.decisions[1].metrics["synthesis_score"]


def test_service_missing_cost_is_unavailable_but_explicit_zero_is_preserved() -> None:
    missing = fixture("service_complete.json")
    missing["candidates"][0]["economics"]["scenarios"]["base"].pop("delivery_cost")
    missing_decision = run_discovery("evaluate", missing).decisions[0]

    assert missing_decision.scenarios["base"]["status"] == "unavailable"
    assert "base.delivery_cost" in missing_decision.evidence_gaps

    explicit_zero = fixture("service_complete.json")
    explicit_zero["candidates"][0]["economics"]["scenarios"]["base"]["delivery_cost"]["amount"] = "0"
    zero_decision = run_discovery("evaluate", explicit_zero).decisions[0]

    assert zero_decision.scenarios["base"]["delivery_cost"]["amount"] == "0"
    assert "base.delivery_cost" not in zero_decision.evidence_gaps


def test_non_finite_numeric_input_is_rejected() -> None:
    payload = product()
    payload["candidates"][0]["economics"]["price"]["amount"] = float("nan")

    with pytest.raises(OpportunityDiscoveryError, match="invalid_numeric_value"):
        run_discovery("evaluate", payload)


@pytest.mark.parametrize("offering_kind", ["product", "service", "hybrid", "unknown"])
def test_offering_kinds_are_product_agnostic(offering_kind: str) -> None:
    if offering_kind == "service":
        payload = fixture("service_complete.json")
    else:
        payload = product()
        payload["candidates"][0]["offering_kind"] = offering_kind
        if offering_kind == "hybrid":
            payload["candidates"][0]["economics"]["scenarios"] = fixture("service_complete.json")["candidates"][0]["economics"]["scenarios"]

    report = run_discovery("evaluate", payload)

    assert report.decisions[0].metrics["offering_kind"] == offering_kind


def test_service_uses_canonical_service_economics_and_preserves_scenarios() -> None:
    report = run_discovery("evaluate", fixture("service_complete.json"))
    decision = report.decisions[0]

    assert decision.recommendation in {"acceptable", "attractive"}
    assert decision.scenarios["base"]["contribution"]["amount"] == "11600"
    assert decision.scenarios["base"]["maximum_simultaneous_clients"] == "5"


def test_compare_validate_and_review_modes_have_explicit_contracts() -> None:
    first = product()["candidates"][0]
    second = copy.deepcopy(first)
    second["candidate_id"] = "desk-lamp-alt"
    compare = run_discovery("compare", {"candidates": [first, second]})
    assert len(compare.decisions) == 2
    validate = run_discovery("validate", {"candidates": [first]})
    review = run_discovery("review-results", {"candidates": [{**first, "metadata": {"review_results": {"result": "pending"}}}]})
    assert validate.mode == "validate"
    assert review.decisions[0].review_results == {"result": "pending"}


def test_non_product_candidates_are_not_ranked_without_canonical_synthesis() -> None:
    report = run_discovery("discover", fixture("service_complete.json"))

    assert report.decisions[0].synthesis["status"] == "not_applicable"
    assert report.ranked_candidate_ids == ()


@pytest.mark.parametrize("mode", ["discover", "evaluate", "compare", "validate", "review-results"])
def test_no_candidates_degrades_to_unavailable_for_every_mode(mode: str) -> None:
    report = run_discovery(mode, {"candidates": []})

    assert report.status == "unavailable"
    assert report.decisions == ()
    assert report.ranked_candidate_ids == ()


def test_discover_does_not_invent_candidates() -> None:
    report = run_discovery("discover", {"candidates": []})

    assert report.status == "unavailable"
    assert report.ranked_candidate_ids == ()


def test_discover_can_only_seed_candidates_from_supplied_evidence() -> None:
    candidate = product()["candidates"][0]
    report = run_discovery("discover", {"evidence_candidates": [candidate]})

    assert report.candidates[0].candidate_id == "desk-lamp"
    assert report.execution_classification == "actual_executed"


def test_malformed_and_secret_shaped_input_fails_closed() -> None:
    with pytest.raises(OpportunityDiscoveryError, match="sensitive_field_rejected"):
        run_discovery("discover", {"candidates": [], "api_key": "not allowed"})
    with pytest.raises(OpportunityDiscoveryError, match="duplicate_input_key"):
        load_payload('{"candidates": [], "candidates": []}')

    with pytest.raises(OpportunityDiscoveryError, match="root_must_be_object"):
        run_discovery("discover", [])


def test_non_finite_numeric_text_in_nested_reports_is_rejected() -> None:
    payload = product()
    payload["candidates"][0]["reports"]["marketplace"]["candidates"][0]["score"]["overall_marketplace_opportunity"] = "NaN"

    with pytest.raises(OpportunityDiscoveryError, match="invalid_numeric_value"):
        run_discovery("evaluate", payload)


@pytest.mark.parametrize("report_name, field_name", [
    ("marketplace", "overall_marketplace_opportunity"),
    ("supplier", "overall_supplier_feasibility"),
    ("consumer", "overall_consumer_attention"),
])
def test_malformed_pillar_score_is_blocked_instead_of_clamped_to_zero(report_name: str, field_name: str) -> None:
    payload = ready_product()
    payload["candidates"][0]["reports"][report_name]["candidates"][0]["score"][field_name] = "not-a-number"

    decision = run_discovery("evaluate", payload).decisions[0]

    assert decision.recommendation == "blocked"
    assert f"malformed_{report_name}_report" in decision.fatal_gates
    assert decision.synthesis["status"] == "malformed"


def test_malformed_pillar_report_is_blocked_without_reflecting_adapter_errors() -> None:
    payload = product()
    payload["candidates"][0]["reports"]["marketplace"] = {"candidates": "not-a-list"}

    decision = run_discovery("evaluate", payload).decisions[0]

    assert decision.recommendation == "blocked"
    assert "malformed_marketplace_report" in decision.fatal_gates
    assert "AttributeError" not in str(decision.to_dict())


def test_current_conflicting_evidence_blocks_a_ready_product() -> None:
    payload = ready_product()
    payload["candidates"][0]["evidence"].append({
        "evidence_id": "current-conflict",
        "area": "competition",
        "status": "observed_fact",
        "evidence_class": "observed",
        "source_type": "operator",
        "source_ref": "manual://conflict",
        "freshness": "current",
        "conflicting": True,
    })

    decision = run_discovery("evaluate", payload).decisions[0]

    assert decision.recommendation == "blocked"
    assert "conflicting_competition_evidence" in decision.fatal_gates


def test_mixed_service_scenario_currency_is_blocked() -> None:
    payload = fixture("service_complete.json")
    payload["candidates"][0]["economics"]["scenarios"]["worst"]["currency"] = "USD"
    payload["candidates"][0]["economics"]["scenarios"]["worst"]["service_fee"]["currency"] = "USD"

    decision = run_discovery("evaluate", payload).decisions[0]

    assert decision.recommendation == "blocked"
    assert "currency_mismatch" in decision.fatal_gates
    assert all(item.get("status") == "malformed" for item in decision.scenarios.values())


def test_product_currency_mismatch_is_a_bounded_blocked_result() -> None:
    payload = product()
    payload["candidates"][0]["economics"]["assumptions"]["supplier_shipping"]["currency"] = "USD"

    decision = run_discovery("evaluate", payload).decisions[0]

    assert decision.scenarios["base"]["status"] == "malformed"
    assert "economics_unavailable" in decision.blockers


def test_markdown_rejects_unsafe_mapping_values() -> None:
    with pytest.raises(OpportunityDiscoveryError, match="sensitive_value_rejected"):
        render_markdown({"decisions": [{"candidate_id": "candidate-1", "blockers": ["system prompt"]}]})


@pytest.mark.parametrize("payload, error", [
    ({"candidates": [], "note": "<div>unsafe</div>"}, "sensitive_value_rejected"),
    ({"candidates": [], "note": "Authorization: Bearer synthetic-token"}, "sensitive_value_rejected"),
    ({"candidates": [], "source_path": "..\\private"}, "unsafe_path_field"),
])
def test_unsafe_html_secret_and_path_inputs_fail_closed(payload: dict, error: str) -> None:
    with pytest.raises(OpportunityDiscoveryError, match=error):
        run_discovery("discover", payload)


@pytest.mark.parametrize("source_ref", ["manual://../../private", "/private/artifact", "C:\\private\\artifact", "C:..\\private"])
def test_path_escape_source_reference_is_rejected(source_ref: str) -> None:
    payload = product()
    payload["candidates"][0]["evidence"][0]["source_ref"] = source_ref

    with pytest.raises(OpportunityDiscoveryError, match="unsafe_source_ref"):
        run_discovery("evaluate", payload)


@pytest.mark.parametrize("report", [
    {"decisions": "not-a-list"},
    {"decisions": ["not-a-decision"]},
    {"decisions": [{"candidate_id": "../escape", "blockers": []}]},
    {"decisions": [{"candidate_id": "candidate-1", "blockers": [{"unsafe": True}]}]},
])
def test_markdown_rejects_malformed_decision_shape(report: dict) -> None:
    with pytest.raises(OpportunityDiscoveryError):
        render_markdown(report)


def test_live_claim_is_downgraded_and_does_not_upgrade_evidence() -> None:
    payload = product()
    payload["candidates"][0]["evidence"][0]["evidence_class"] = "live_validated"

    decision = run_discovery("evaluate", payload).decisions[0]

    assert "unavailable" in decision.evidence_classes
    assert any("live_validation_not_available" in item for item in decision.blockers)


def test_trustos_export_requires_registered_workspace_and_validates_when_injected(tmp_path: Path) -> None:
    workspace = ClientWorkspace(name="opportunity-discovery-test")
    registry = WorkspaceRegistry(path=str(tmp_path / "workspaces.json"))
    registry.register(workspace)

    report = run_discovery("evaluate", product(), workspace=workspace, registry=registry)
    export = report.decisions[0].trustos_export

    assert export["status"] == "validated"
    assert "fingerprint" in export
    assert report.safety["database_writes"] is False


def test_markdown_is_bounded_and_deterministic() -> None:
    report = run_discovery("evaluate", product())

    assert render_markdown(report) == render_markdown(report)
    assert len(render_markdown(report).encode("utf-8")) < 16 * 1024


def test_cli_smoke_is_json_and_does_not_claim_live_validation(tmp_path: Path) -> None:
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(product()), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "scripts/run_opportunity_discovery.py", "--mode", "evaluate", "--input", str(input_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output["execution_classification"] == "actual_executed"
    assert output["safety"]["launch_authorized"] is False


@pytest.mark.parametrize("mode", ["discover", "evaluate", "compare", "validate", "review-results"])
def test_cli_executes_every_discovery_mode_with_deterministic_json(mode: str, tmp_path: Path) -> None:
    payload = product()
    if mode == "compare":
        first = payload["candidates"][0]
        second = copy.deepcopy(first)
        second["candidate_id"] = "desk-lamp-alt"
        second["name"] = "Desk lamp alternative"
        for report in second["reports"].values():
            for item in report["candidates"]:
                item["candidate_id"] = "desk-lamp-alt"
        payload["candidates"].append(second)
    if mode == "review-results":
        payload["candidates"][0]["metadata"] = {"review_results": {"result": "pending"}}
    input_path = tmp_path / f"{mode}.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/run_opportunity_discovery.py", "--mode", mode, "--input", str(input_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["mode"] == mode
    assert output["execution_classification"] == "actual_executed"
    assert len(output["fingerprint"]) == 64
    assert output["safety"]["launch_authorized"] is False
