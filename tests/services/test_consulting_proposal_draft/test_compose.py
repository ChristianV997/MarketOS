from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import backend.core.persistence as persistence
import pytest
from backend.organization.commercial_report import CommercialReport
from backend.organization.report_registry import ReportRegistry
from backend.workspaces.artifact_store import ArtifactStore
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry
from evaluation.trustos.client_workspace_isolation import check_workspace_leakage

from services.consulting_proposal_draft import (
    ConsultingProposalDraftError,
    build_consulting_proposal_draft,
    render_consulting_proposal_markdown,
)
from services.consulting_proposal_draft.compose import _catalog_package_price
from services.consulting_offers import get_offer_definition

WORKSPACE_ID = "fixture-consulting-client"
FOREIGN = "workspace-other-client"
ROOT = Path(__file__).parents[2]
ECONOMICS = json.loads((ROOT / "fixtures" / "consulting_economics" / "project_complete.json").read_text(encoding="utf-8"))


def _request() -> dict:
    return {
        "client_id": "fixture-client-alpha",
        "workspace_id": WORKSPACE_ID,
        "client_objective": "Assess a product opportunity before choosing a validation path.",
        "geography": "Mexico",
        "language": "es-MX",
        "scope": "Product research and evidence-gap review.",
        "offering_kind": "product",
        "selected_offer_ids": ["diagnostic-audit"],
        "selected_deliverables": ["product_research", "customer_intelligence", "client_safe_export"],
        "pricing_currency": "USD",
        "evidence": [{
            "evidence_id": "market-brief-1",
            "evidence_class": "manual",
            "state": "available",
            "source_ref": "manual://consulting-proposal-draft/market",
            "summary": "Sanitized market brief",
        }],
        "assumptions": ["Turnaround is a planning estimate."],
        "conflicts": [],
        "missing_information": ["Returns policy is unknown."],
        "linked_component_report_ids": ["report_fixture_product"],
        "optional_upsell_offer_ids": ["unit-service-economics"],
        "economics": {
            key: ECONOMICS[key]
            for key in ECONOMICS
            if key not in {"service_id", "offering_name", "currency", "package_price", "source_ref", "evidence_id"}
        },
    }


@pytest.fixture()
def authorities(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "STATE_DIR", str(tmp_path / "state"))
    workspace_registry = WorkspaceRegistry(str(tmp_path / "workspaces.json"))
    workspace = workspace_registry.register(ClientWorkspace(
        workspace_id=WORKSPACE_ID,
        name="fixture consulting client",
        workspace_type="client_service",
        mode="client_service",
        dry_run_default=True,
    ))
    report_registry = ReportRegistry(str(tmp_path / "reports.json"))
    report_registry.register(CommercialReport(
        report_id="report_fixture_product",
        workspace_id=workspace.workspace_id,
        proposal_id="proposal-fixture",
        experiment_id="experiment-fixture",
        service_name="product_research",
        title="Fixture product report",
        summary="A bounded fixture report.",
        status="completed",
        created_at=0.0,
    ))
    return workspace_registry, report_registry, workspace, ArtifactStore(workspace, workspace_registry)


def _build(request, authorities):
    workspace_registry, report_registry, workspace, artifact_store = authorities
    return build_consulting_proposal_draft(
        request,
        workspace=workspace,
        artifact_store=artifact_store,
        workspace_registry=workspace_registry,
        report_registry=report_registry,
    )


def test_draft_links_scope_evidence_and_economics_without_approval(authorities):
    draft = _build(_request(), authorities)
    assert draft["status"] == "blocked"
    assert "evidence_missing" in draft["blockers"]
    assert draft["authority"] == {
        "human_approved": False,
        "contract": False,
        "invoice": False,
        "work_authorized": False,
        "payment_authorized": False,
        "provider_calls": False,
    }
    assert draft["scope"]["inclusions"]
    assert draft["scope"]["exclusions"]
    assert "Turnaround is a planning estimate." in draft["scope"]["assumptions"]
    assert "Returns policy is unknown." in draft["scope"]["unknowns"]
    assert draft["evidence"]["report_refs"][0]["report_id"] == "report_fixture_product"
    assert draft["economics"]["currency"] == "USD"
    assert draft["economics"]["fingerprint"]
    assert draft["engagement"]["fingerprint"]
    assert draft["offer"]["fingerprint"]
    exported = draft["client_export"]
    assert exported["export_version"] == "client-workspace-evidence-export-v1"
    assert check_workspace_leakage(exported["payload"]) == ()
    assert exported["payload"]["workspace_id"] == WORKSPACE_ID
    text = render_consulting_proposal_markdown(draft)
    assert "Not an approval" in text
    assert "human_approved" not in json.dumps(draft["authority"]) or draft["authority"]["human_approved"] is False
    again = _build(_request(), authorities)
    assert again["fingerprint"] == draft["fingerprint"]


def test_caller_metadata_is_not_mutated(authorities):
    request = _request()
    snapshot = json.loads(json.dumps(request))
    nested = request["economics"]
    _build(request, authorities)
    assert request == snapshot
    assert request["economics"] is nested


def test_foreign_workspace_evidence_is_not_exported(authorities):
    request = _request()
    request["component_reports"] = [{
        "report_id": "report_fixture_product",
        "fingerprint": "abc123fixture",
        "service_name": "product_research",
        "workspace_id": WORKSPACE_ID,
        "status": "completed",
    }, {
        "report_id": "foreign-report",
        "fingerprint": "abc123foreign",
        "service_name": "product_research",
        "workspace_id": FOREIGN,
        "status": "completed",
    }]
    draft = _build(request, authorities)
    blob = json.dumps(draft)
    assert FOREIGN not in blob
    assert "foreign-report" not in blob
    assert "evidence_register_rejected" in draft["blockers"]


def test_same_workspace_forged_component_report_is_rejected(authorities):
    request = _request()
    request["component_reports"] = [{
        "report_id": "report_fixture_product",
        "fingerprint": "forged-fingerprint",
        "service_name": "product_research",
        "workspace_id": WORKSPACE_ID,
        "status": "completed",
    }]

    draft = _build(request, authorities)

    assert "evidence_register_rejected" in draft["blockers"]


def test_live_economics_mode_is_blocked_without_raising(authorities):
    request = _request()
    request["economics"]["evidence_mode"] = "live"

    draft = _build(request, authorities)

    assert draft["economics"]["recommendation"] == "blocked"
    assert "economics_incomplete" in draft["blockers"]


def test_multi_offer_catalog_price_is_aggregate(authorities):
    del authorities
    first = get_offer_definition("diagnostic-audit").price_range.minimum
    second = get_offer_definition("unit-service-economics").price_range.minimum

    price = _catalog_package_price(("diagnostic-audit", "unit-service-economics"), "USD")

    assert price is not None
    assert price["amount"] == str(first + second)


def test_currency_mismatch_does_not_invent_a_kernel_result(authorities):
    request = _request()
    request["economics"] = {"currency": "MXN", "package_price": {"amount": "10", "currency": "MXN"}}
    draft = _build(request, authorities)
    assert "currency_mismatch" in draft["blockers"]
    assert draft["economics"]["recommendation"] == "blocked"
    assert draft["economics"]["fingerprint"] == ""
    assert draft["authority"]["payment_authorized"] is False


def test_secret_marker_is_rejected_without_echo(authorities):
    request = _request()
    request["assumptions"] = ["password=do-not-echo"]
    with pytest.raises(ConsultingProposalDraftError) as caught:
        _build(request, authorities)
    assert "password" not in str(caught.value)
    assert "do-not-echo" not in str(caught.value)


def test_cli_prints_the_same_draft(authorities):
    del authorities
    payload = json.dumps(_request())
    completed = subprocess.run(
        [sys.executable, "scripts/consulting_proposal_draft.py"],
        input=payload,
        text=True,
        capture_output=True,
        cwd=Path(__file__).parents[3],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[3])},
    )
    assert completed.returncode == 0, completed.stderr
    draft = json.loads(completed.stdout)
    assert draft["workspace_id"] == WORKSPACE_ID
    assert draft["authority"]["human_approved"] is False
    assert FOREIGN not in completed.stdout
