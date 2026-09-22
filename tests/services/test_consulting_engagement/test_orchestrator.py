from __future__ import annotations

import json
from pathlib import Path

import backend.core.persistence as persistence
import pytest
from backend.organization.commercial_report import CommercialReport
from backend.organization.report_registry import ReportRegistry
from backend.organization.service_contract import ServiceContractRegistry
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry
from services.consulting_engagement import (
    ConsultingEngagementError,
    ConsultingEngagementRequest,
    EvidenceInput,
    build_consulting_engagement,
)

FIXTURE_DIR = Path(__file__).parents[2] / "fixtures" / "consulting_engagement"


@pytest.fixture()
def authorities(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "STATE_DIR", str(tmp_path / "state"))
    workspace_registry = WorkspaceRegistry(str(tmp_path / "workspaces.json"))
    workspace = workspace_registry.register(
        ClientWorkspace(
            workspace_id="fixture-consulting-client",
            name="fixture consulting client",
            workspace_type="client_service",
            mode="client_service",
            dry_run_default=True,
        )
    )
    report_registry = ReportRegistry(str(tmp_path / "reports.json"))
    report_registry.register(
        CommercialReport(
            report_id="report_fixture_product",
            workspace_id=workspace.workspace_id,
            proposal_id="proposal-fixture",
            experiment_id="experiment-fixture",
            service_name="product_research",
            title="Fixture product report",
            summary="A bounded fixture report.",
            status="completed",
        )
    )
    return workspace_registry, report_registry, workspace


def load_request(name: str) -> ConsultingEngagementRequest:
    return ConsultingEngagementRequest.from_mapping(json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8")))


def build_fixture(name: str, authorities):
    workspace_registry, report_registry, workspace = authorities
    return build_consulting_engagement(
        load_request(name),
        workspace=workspace,
        workspace_registry=workspace_registry,
        report_registry=report_registry,
    )


def test_complete_product_is_ready_for_review_and_references_component_report(authorities):
    result = build_fixture("complete_product.json", authorities)

    assert result.status == "ready_for_review"
    assert result.offering_kind == "product"
    assert result.component_reports[0].report_id == "report_fixture_product"
    assert result.component_reports[0].service_name == "product_research"
    assert result.evidence_summary["evidence_ceiling"] == "fixture_manual_simulated_or_planned"
    assert result.evidence_summary["launch_authorized"] is False
    assert result.trustos_export["redaction_status"] == "validated_no_sensitive_fields"
    assert result.trustos_export["payload"]["workspace_id"] == result.workspace_id


def test_partial_service_preserves_missing_information_and_does_not_zero_fill(authorities):
    result = build_fixture("partial_service.json", authorities)

    assert result.offering_kind == "service"
    assert result.status == "blocked"
    assert "missing_information:authoritative_customer_evidence" in result.blockers
    serialized = result.to_dict()
    assert "economics" not in serialized
    assert "economics" not in json.dumps(serialized, sort_keys=True)
    assert result.client_safe_projection["missing_information"]


def test_hybrid_conflict_blocks_without_collapsing_evidence(authorities):
    result = build_fixture("hybrid_conflicting.json", authorities)

    assert result.offering_kind == "hybrid"
    assert result.status == "blocked"
    assert "evidence_conflict" in result.blockers
    assert "evidence_not_current" in result.blockers
    assert result.evidence_summary["state_counts"] == {"available": 1, "conflicting": 1}


def test_unknown_offering_is_supported_but_fail_closed(authorities):
    result = build_fixture("unknown_offering.json", authorities)

    assert result.status == "blocked"
    assert result.blockers == ("offering_kind_unknown", "missing_information:offering_kind_confirmation")
    assert result.execution_plan == ()
    assert result.client_safe_projection["offering_kind"] == "unknown"


def test_stale_evidence_is_not_launch_authorization(authorities):
    result = build_fixture("stale_evidence.json", authorities)

    assert result.status == "blocked"
    assert "evidence_not_current" in result.blockers
    assert result.evidence_summary["live_authoritative_evidence"] is False
    assert result.evidence_summary["launch_authorized"] is False


def test_product_service_and_hybrid_module_selection_is_deterministic(authorities):
    workspace_registry, report_registry, workspace = authorities
    for offering_kind, expected in {
        "product": {"product_research", "customer_intelligence", "trustos_export"},
        "service": {"service_engagement", "customer_intelligence", "trustos_export"},
        "hybrid": {"product_research", "service_engagement", "customer_intelligence", "trustos_export"},
    }.items():
        request = load_request("complete_product.json")
        selected = {
            "product": ("product_research", "customer_intelligence", "client_safe_export"),
            "service": ("service_engagement", "customer_intelligence", "client_safe_export"),
            "hybrid": ("product_research", "service_engagement", "customer_intelligence", "client_safe_export"),
        }[offering_kind]
        request = ConsultingEngagementRequest.from_mapping(
            {**request.to_dict(), "offering_kind": offering_kind, "selected_deliverables": selected, "linked_component_report_ids": ()}
        )
        result = build_consulting_engagement(
            request,
            workspace=workspace,
            workspace_registry=workspace_registry,
            report_registry=report_registry,
        )
        assert {item.service_name for item in result.execution_plan} == expected - {"trustos_export"}
        assert "client_safe_export" in result.selected_deliverables


def test_same_request_has_stable_identity_fingerprint_and_markdown(authorities):
    first = build_fixture("complete_product.json", authorities)
    second = build_fixture("complete_product.json", authorities)

    assert first.engagement_id == second.engagement_id
    assert first.fingerprint == second.fingerprint
    assert first.to_dict() == second.to_dict()
    assert first.to_markdown() == second.to_markdown()
    assert "DRY RUN" in first.to_markdown()
    assert "launch authorization" in first.to_markdown().casefold()


def test_workspace_identity_mismatch_is_rejected(authorities):
    workspace_registry, report_registry, workspace = authorities
    request = load_request("complete_product.json")
    forged = ClientWorkspace(
        workspace_id="fixture-other-client",
        name="forged workspace",
        workspace_type="client_service",
        mode="client_service",
    )

    with pytest.raises(ConsultingEngagementError, match="workspace_identity_mismatch"):
        build_consulting_engagement(
            request,
            workspace=forged,
            workspace_registry=workspace_registry,
            report_registry=report_registry,
        )


def test_unregistered_workspace_is_rejected(authorities):
    workspace_registry, report_registry, _ = authorities
    request = load_request("complete_product.json")
    unknown = ClientWorkspace(
        workspace_id="fixture-unknown-client",
        name="unknown workspace",
        workspace_type="client_service",
        mode="client_service",
    )
    request = ConsultingEngagementRequest.from_mapping({**request.to_dict(), "workspace_id": unknown.workspace_id})

    with pytest.raises(ConsultingEngagementError, match="workspace_identity_rejected"):
        build_consulting_engagement(
            request,
            workspace=unknown,
            workspace_registry=workspace_registry,
            report_registry=report_registry,
        )


def test_cross_workspace_component_report_is_rejected(authorities):
    workspace_registry, report_registry, workspace = authorities
    other = workspace_registry.register(
        ClientWorkspace(
            workspace_id="fixture-other-report-client",
            name="other report client",
            workspace_type="client_service",
            mode="client_service",
        )
    )
    report_registry.register(
        CommercialReport(
            report_id="report_other_workspace",
            workspace_id=other.workspace_id,
            proposal_id="proposal-other",
            experiment_id="experiment-other",
            service_name="product_research",
            title="Other workspace report",
            summary="Must not cross the boundary.",
        )
    )
    request = load_request("complete_product.json")
    request = ConsultingEngagementRequest.from_mapping(
        {**request.to_dict(), "linked_component_report_ids": ("report_other_workspace",)}
    )

    with pytest.raises(ConsultingEngagementError, match="component_report_workspace_mismatch"):
        build_consulting_engagement(
            request,
            workspace=workspace,
            workspace_registry=workspace_registry,
            report_registry=report_registry,
        )


def test_secret_shaped_request_is_rejected_before_orchestration(authorities):
    workspace_registry, report_registry, workspace = authorities
    with pytest.raises(ConsultingEngagementError, match="unsafe scope"):
        build_consulting_engagement(
            {
                **load_request("complete_product.json").to_dict(),
                "scope": "review bearer fixture-token",
            },
            workspace=workspace,
            workspace_registry=workspace_registry,
            report_registry=report_registry,
        )


def test_optional_capability_degrades_without_raw_internals(authorities):
    workspace_registry, report_registry, workspace = authorities
    request = load_request("complete_product.json")
    request = ConsultingEngagementRequest.from_mapping(
        {**request.to_dict(), "selected_deliverables": ("unit_economics", "client_safe_export"), "linked_component_report_ids": ()}
    )
    result = build_consulting_engagement(
        request,
        workspace=workspace,
        workspace_registry=workspace_registry,
        report_registry=report_registry,
        service_contract_registry=ServiceContractRegistry([]),
    )

    assert result.status == "blocked"
    assert result.blockers == ("deliverable_unavailable:unit_economics",)
    assert "module_path" not in result.client_safe_projection
    assert "services.unit_economics" not in json.dumps(result.client_safe_projection)


def test_client_safe_projection_contains_no_internal_or_raw_component_payload(authorities):
    result = build_fixture("complete_product.json", authorities)
    projection = result.client_safe_projection

    assert "findings" not in projection
    assert "raw_payload" not in json.dumps(projection).casefold()
    assert "module_path" not in projection
    assert projection["component_reports"] == [
        {
            "report_id": "report_fixture_product",
            "service_name": "product_research",
            "status": "completed",
            "workspace_id": "fixture-consulting-client",
            "experiment_id": "experiment-fixture",
        }
    ]


def test_invalid_offering_and_control_characters_fail_closed():
    with pytest.raises(ValueError, match="invalid offering kind"):
        ConsultingEngagementRequest(
            client_id="client",
            workspace_id="workspace",
            client_objective="objective",
            geography="Mexico",
            language="es-MX",
            scope="scope",
            offering_kind="other",
        )
    with pytest.raises(ValueError, match="invalid language"):
        ConsultingEngagementRequest(
            client_id="client",
            workspace_id="workspace",
            client_objective="objective",
            geography="Mexico",
            language="es\nMX",
            scope="scope",
            offering_kind="product",
        )


def test_evidence_classes_and_authority_are_preserved(authorities):
    workspace_registry, report_registry, workspace = authorities
    request = load_request("complete_product.json")
    request = ConsultingEngagementRequest(
        **{
            **request.to_dict(),
            "evidence": [
                EvidenceInput("live-but-unverified", "live", authoritative=False),
                EvidenceInput("derived-result", "derived", authoritative=False),
            ],
            "linked_component_report_ids": (),
        }
    )
    result = build_consulting_engagement(
        request,
        workspace=workspace,
        workspace_registry=workspace_registry,
        report_registry=report_registry,
    )

    assert result.evidence_summary["class_counts"] == {"derived": 1, "live": 1}
    assert result.evidence_summary["live_authoritative_evidence"] is False
    assert result.evidence_summary["launch_authorized"] is False
