from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from backend.commerce.owner_opportunity_read_model import (
    OwnerOpportunityReadModelError,
    build_owner_opportunity_read_model,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "opportunity_discovery"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def product_payload() -> dict:
    return load_fixture("product_complete.json")


def test_full_fixture_preserves_identity_evidence_and_canonical_ranking() -> None:
    report = build_owner_opportunity_read_model("evaluate", product_payload()).to_dict()

    assert report["candidate_count"] == 1
    assert report["ranked_candidate_ids"] == ["desk-lamp"]
    item = report["opportunities"][0]
    assert item["candidate_id"] == "desk-lamp"
    assert item["ranking"]["authority"].endswith("build_product_opportunity_synthesis")
    assert {evidence["area"] for evidence in item["evidence"]} == {"demand", "supply", "economics"}
    assert item["evidence"][1]["source_ref"].startswith("manual://")
    assert report["safety"]["launch_authorized"] is False
    assert report["snapshot_resolution"] == {
        "source": "input_payload",
        "persisted": False,
        "resolver": "unavailable",
    }


def test_partial_and_missing_evidence_remain_visible() -> None:
    payload = product_payload()
    payload["candidates"][0]["reports"].pop("consumer")
    partial = build_owner_opportunity_read_model("evaluate", payload).to_dict()
    item = partial["opportunities"][0]
    assert item["readiness"] != "ready"
    assert item["evidence_gaps"]

    missing = product_payload()
    missing["candidates"][0]["economics"].pop("product_cost")
    missing["candidates"][0]["economics"]["assumptions"].pop("supplier_shipping")
    result = build_owner_opportunity_read_model("evaluate", missing).to_dict()
    economics = result["opportunities"][0]["economics"]
    assert economics["status"] == "unavailable"
    assert "product_cost" in economics["missing_inputs"]
    assert "shipping" in economics["missing_inputs"]
    assert all("contribution_after_cac" not in scenario for scenario in economics["scenarios"].values())


def test_explicit_zero_is_not_collapsed_into_missing() -> None:
    payload = product_payload()
    assumptions = payload["candidates"][0]["economics"]["assumptions"]
    assumptions["supplier_shipping"]["amount"] = "0"
    result = build_owner_opportunity_read_model("evaluate", payload).to_dict()
    economics = result["opportunities"][0]["economics"]
    assert economics["status"] != "unavailable"
    assert "shipping" not in economics["missing_inputs"]
    assert economics["assumptions"]["supplier_shipping"]["amount"] == "0"


def test_stale_evidence_is_preserved_and_blocks_readiness() -> None:
    payload = product_payload()
    payload["candidates"][0]["evidence"][0]["freshness"] = "stale"
    result = build_owner_opportunity_read_model("evaluate", payload).to_dict()
    item = result["opportunities"][0]
    assert any(evidence["freshness"] == "stale" for evidence in item["evidence"])
    assert any("stale" in gap for gap in item["evidence_gaps"])
    assert item["readiness"] != "ready"


def test_mismatched_report_candidate_is_blocked_without_rebinding_identity() -> None:
    payload = product_payload()
    payload["candidates"][0]["reports"]["supplier"]["candidates"][0]["candidate_id"] = "other-candidate"
    result = build_owner_opportunity_read_model("evaluate", payload).to_dict()
    item = result["opportunities"][0]
    assert item["candidate_id"] == "desk-lamp"
    assert "report_candidate_identity_mismatch" in item["blockers"]
    assert result["ranked_candidate_ids"] == []


def test_projection_does_not_export_raw_reports_or_internal_formula_fields() -> None:
    payload = product_payload()
    first = build_owner_opportunity_read_model("evaluate", payload).to_dict()
    second = build_owner_opportunity_read_model("evaluate", copy.deepcopy(payload)).to_dict()
    encoded = json.dumps(first, sort_keys=True)

    assert first["fingerprint"] == second["fingerprint"]
    assert "reports" not in first["opportunities"][0]
    assert "prompt" not in encoded.lower()
    assert "formula" not in encoded.lower()
    assert "source_code" not in encoded.lower()


def test_projection_preserves_canonical_rank_order_before_unranked_candidates() -> None:
    payload = product_payload()
    second = copy.deepcopy(payload["candidates"][0])
    second["candidate_id"] = "aaa-lamp"
    for report in second["reports"].values():
        for report_candidate in report.get("candidates", []):
            report_candidate["candidate_id"] = "aaa-lamp"
    second["reports"]["marketplace"]["candidates"][0]["score"][
        "overall_marketplace_opportunity"
    ] = 0.7
    second["reports"]["supplier"]["candidates"][0]["score"][
        "overall_supplier_feasibility"
    ] = 0.7
    second["reports"]["consumer"]["candidates"][0]["score"][
        "overall_consumer_attention"
    ] = 0.7
    payload["candidates"].append(second)

    result = build_owner_opportunity_read_model("compare", payload).to_dict()

    assert result["ranked_candidate_ids"] == ["desk-lamp", "aaa-lamp"]
    assert [item["candidate_id"] for item in result["opportunities"]] == result[
        "ranked_candidate_ids"
    ]


@pytest.mark.parametrize(
    ("kwargs", "error_code"),
    [
        ({"workspace": object()}, "invalid_workspace"),
        ({"registry": object()}, "invalid_workspace_registry"),
    ],
)
def test_workspace_authorities_are_explicitly_typed(
    kwargs: dict[str, object], error_code: str
) -> None:
    with pytest.raises(OwnerOpportunityReadModelError, match=error_code):
        build_owner_opportunity_read_model("discover", {"candidates": []}, **kwargs)


def test_workspace_mismatch_is_rejected_before_discovery() -> None:
    from backend.workspaces.client_workspace import ClientWorkspace

    workspace = ClientWorkspace(workspace_id="workspace-owner", name="Owner")
    with pytest.raises(OwnerOpportunityReadModelError, match="workspace_mismatch"):
        build_owner_opportunity_read_model(
            "evaluate",
            {"workspace_id": "workspace-other", "candidates": []},
            workspace=workspace,
        )
