from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import backend.core.persistence as persistence
import backend.workspaces.registry as registry_module
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry
from services.client_safe_product_opportunity_report import (
    ClientSafeProductOpportunityReportError,
    build_client_safe_product_opportunity_report,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "opportunity_discovery" / "product_complete.json"


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(persistence, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(registry_module, "_registry", None)


def payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def registered_workspace(tmp_path: Path) -> tuple[ClientWorkspace, WorkspaceRegistry]:
    registry = WorkspaceRegistry(str(tmp_path / "workspaces.json"))
    workspace = registry.register(ClientWorkspace(workspace_id="client-alpha", name="Client Alpha", workspace_type="client_service"))
    return workspace, registry


def test_projection_uses_canonical_synthesis_and_exports_allowlisted_evidence() -> None:
    workspace, registry = registered_workspace(Path(persistence.STATE_DIR))
    source = payload()
    source["candidates"][0]["evidence"].append(
        {
            "evidence_id": "desk-attention",
            "area": "consumer_attention",
            "status": "observed_fact",
            "evidence_class": "manual",
            "source_type": "operator",
            "source_ref": "manual://attention/desk-lamp",
            "freshness": "stale",
        }
    )

    result = build_client_safe_product_opportunity_report("evaluate", source, workspace=workspace, registry=registry)
    body = result.to_dict()
    candidate = body["candidates"][0]

    assert candidate["candidate_id"] == "desk-lamp"
    assert candidate["evidence_by_pillar"]["marketplace"][0]["source_ref"] == "fixture://market/desk-lamp"
    assert candidate["evidence_by_pillar"]["supplier"][0]["source_ref"] == "manual://supplier/desk-lamp"
    assert candidate["evidence_by_pillar"]["consumer_attention"][0]["evidence_age"] == "stale"
    assert candidate["evidence_classes"] == ["derived", "fixture", "manual"]
    assert candidate["economics"]["currency_boundaries"] == {
        "currencies": ["MXN"],
        "mixed_currency": False,
        "conversion_applied": False,
    }
    assert body["authorities"]["synthesis"].endswith("build_product_opportunity_synthesis")
    assert candidate["ranking"]["authority"].endswith("build_product_opportunity_synthesis")
    assert candidate["economics"]["scenarios"]
    assert set(result.export.payload) == {
        "workspace_id", "status", "blockers", "evidence_required", "approvals_required", "next_actions",
    }
    assert result.export.payload["workspace_id"] == workspace.workspace_id
    assert result.export.evidence_state == "requires_review"

    encoded = json.dumps(body, sort_keys=True).lower()
    assert "reports" not in encoded
    assert "prompt" not in encoded
    assert "formula" not in encoded
    assert "raw payload" not in encoded
    assert '"credentials_present": false' in encoded
    assert "sk_live_" not in encoded
    assert "bearer " not in encoded


def test_missing_cost_remains_unknown_while_explicit_zero_remains_present(tmp_path: Path) -> None:
    workspace, registry = registered_workspace(tmp_path)
    missing = payload()
    missing["candidates"][0]["economics"]["product_cost"] = None
    missing_result = build_client_safe_product_opportunity_report("evaluate", missing, workspace=workspace, registry=registry)
    missing_economics = missing_result.to_dict()["candidates"][0]["economics"]
    assert "product_cost" in missing_economics["missing_inputs"]

    explicit_zero = payload()
    explicit_zero["candidates"][0]["economics"]["product_cost"] = {
        "amount": "0",
        "currency": "MXN",
        "source": "manual",
        "provenance": "manual",
        "evidence_state": "observed",
    }
    explicit_zero["candidates"][0]["economics"]["assumptions"]["supplier_shipping"]["amount"] = "0"
    zero_result = build_client_safe_product_opportunity_report("evaluate", explicit_zero, workspace=workspace, registry=registry)
    zero_economics = zero_result.to_dict()["candidates"][0]["economics"]
    assert "product_cost" not in zero_economics["missing_inputs"]
    assert zero_economics["assumptions"]["supplier_shipping"]["amount"] == "0"


def test_foreign_workspace_and_payload_selector_fail_closed(tmp_path: Path) -> None:
    workspace, registry = registered_workspace(tmp_path)
    forged = ClientWorkspace(workspace_id=workspace.workspace_id, name="Forged", workspace_type="client_service")
    with pytest.raises(ClientSafeProductOpportunityReportError, match="identity_rejected"):
        build_client_safe_product_opportunity_report("evaluate", payload(), workspace=forged, registry=registry)

    mismatched = payload()
    mismatched["workspace_id"] = "client-other"
    with pytest.raises(ClientSafeProductOpportunityReportError, match="workspace_mismatch"):
        build_client_safe_product_opportunity_report("evaluate", mismatched, workspace=workspace, registry=registry)


def test_raw_internal_canary_is_rejected_without_reflection(tmp_path: Path) -> None:
    workspace, registry = registered_workspace(tmp_path)
    unsafe = payload()
    unsafe["candidates"][0]["metadata"]["prompt"] = "do not expose this canary"
    with pytest.raises(ClientSafeProductOpportunityReportError) as exc_info:
        build_client_safe_product_opportunity_report("evaluate", unsafe, workspace=workspace, registry=registry)
    assert exc_info.value.code == "sensitive_field_rejected"
    assert "do not expose" not in str(exc_info.value)


def test_secret_shaped_candidate_values_do_not_reach_the_report(tmp_path: Path) -> None:
    workspace, registry = registered_workspace(tmp_path)
    unsafe = payload()
    unsafe["candidates"][0]["name"] = "sk_live_not_a_keyword_shape"
    with pytest.raises(ClientSafeProductOpportunityReportError) as exc_info:
        build_client_safe_product_opportunity_report("evaluate", unsafe, workspace=workspace, registry=registry)
    assert exc_info.value.code == "sensitive_value_rejected"
    assert "sk_live_not_a_keyword_shape" not in str(exc_info.value)


def test_report_and_markdown_are_deterministic(tmp_path: Path) -> None:
    workspace, registry = registered_workspace(tmp_path)
    first = build_client_safe_product_opportunity_report("evaluate", payload(), workspace=workspace, registry=registry)
    second = build_client_safe_product_opportunity_report("evaluate", copy.deepcopy(payload()), workspace=workspace, registry=registry)
    assert first.to_dict() == second.to_dict()
    assert first.markdown == second.markdown
