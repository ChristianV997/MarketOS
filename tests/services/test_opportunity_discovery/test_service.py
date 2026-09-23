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
