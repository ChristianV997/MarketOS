from __future__ import annotations

import json
from pathlib import Path

import backend.core.persistence as persistence
import pytest
from backend.organization.commercial_report import CommercialReport
from backend.organization.report_registry import ReportRegistry
from backend.workspaces.artifact_store import ArtifactStore
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry
from evaluation.companyos.service_catalog import package_map
from evaluation.companyos.service_engagement import catalog_with_canonical_services
from services.consulting_offers import (
    ConsultingOfferCatalogError,
    ConsultingOfferRequest,
    all_offer_definitions,
    build_consulting_offer_proposal,
    get_offer_definition,
)

FIXTURE_DIR = Path(__file__).parents[2] / "fixtures" / "consulting_offers"


@pytest.fixture()
def authorities(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "STATE_DIR", str(tmp_path / "state"))
    workspace_registry = WorkspaceRegistry(str(tmp_path / "workspaces.json"))
    workspace = workspace_registry.register(ClientWorkspace(
        workspace_id="fixture-consulting-client",
        name="fixture consulting client",
        workspace_type="client_service",
        mode="client_service",
        dry_run_default=True,
    ))
    report_registry = ReportRegistry(str(tmp_path / "reports.json"))
    report_registry.register(CommercialReport(
        report_id="report_fixture_market",
        workspace_id=workspace.workspace_id,
        proposal_id="proposal-fixture",
        experiment_id="experiment-fixture",
        service_name="product_research",
        title="Fixture market report",
        summary="Sanitized component reference.",
        status="completed",
    ))
    return workspace_registry, report_registry, workspace, ArtifactStore(workspace, workspace_registry)


def load_request(name: str) -> ConsultingOfferRequest:
    return ConsultingOfferRequest.from_mapping(json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8")))


def build_fixture(name: str, authorities):
    workspace_registry, report_registry, workspace, artifact_store = authorities
    return build_consulting_offer_proposal(
        load_request(name),
        workspace=workspace,
        artifact_store=artifact_store,
        workspace_registry=workspace_registry,
        report_registry=report_registry,
    )


def test_catalog_has_six_deterministic_productized_offers():
    first = all_offer_definitions()
    second = all_offer_definitions()

    assert [item.offer_id for item in first] == [
        "diagnostic-audit", "market-research-sprint", "unit-service-economics",
        "supplier-logistics-feasibility", "marketing-publicity-strategy", "full-commercial-assessment",
    ]
    assert [item.to_dict() for item in first] == [item.to_dict() for item in second]
    assert {item.price_range.evidence_state for item in first} == {"assumed"}
    assert all(item.turnaround_days > 0 for item in first)


def test_prices_delegate_to_existing_companyos_catalog():
    packages = package_map(catalog_with_canonical_services())
    unit_offer = get_offer_definition("unit-service-economics")
    unit_package = packages["unit-economics-cac-roas-diagnostic"]

    assert unit_offer.price_range.currency == unit_package.price_min_money.currency
    assert unit_offer.price_range.minimum == unit_package.price_min_money.amount
    assert unit_offer.price_range.maximum == unit_package.price_max_money.amount
    full = get_offer_definition("full-commercial-assessment")
    assert full.price_range.minimum > unit_offer.price_range.minimum


def test_complete_product_proposal_is_client_safe_and_draft_only(authorities):
    proposal = build_fixture("complete_product.json", authorities)
    exported = proposal.trustos_export

    assert proposal.status == "draft_ready"
    assert proposal.offering_kind == "product"
    assert proposal.next_action.startswith("Review the planning-only")
    assert proposal.evidence_summary["claims_level"] == "planning_only"
    assert proposal.evidence_summary["launch_authorized"] is False
    assert set(exported["payload"]) == {
        "workspace_id", "status", "blockers", "evidence_required", "approvals_required", "next_actions",
    }
    serialized = json.dumps(proposal.to_dict(), sort_keys=True)
    assert "manual://" not in serialized
    assert "raw_payload" not in serialized.casefold()
    assert "provider response" not in serialized.casefold()
    assert proposal.read_only is True
    assert proposal.live_actions_taken is False
    assert proposal.database_writes is False


def test_complete_service_proposal_preserves_optional_engagement_reference(authorities):
    proposal = build_fixture("complete_service.json", authorities)

    assert proposal.status == "draft_ready"
    assert {item.offer_id for item in proposal.selected_offers} == {"unit-service-economics", "marketing-publicity-strategy"}
    assert proposal.proposal_draft["engagement_reference"] == {
        "engagement_id": "engagement-fixture-1",
        "status": "reference_only",
        "authority": "optional_unmerged_on_main",
    }
    assert "engagement-fixture-1" not in json.dumps(proposal.client_safe_projection)
    assert proposal.sow_draft["planning_only"] is True


def test_hybrid_conflict_blocks_without_upgrading_evidence(authorities):
    proposal = build_fixture("hybrid_conflicting.json", authorities)

    assert proposal.status == "blocked"
    assert "evidence_missing" not in proposal.blockers
    assert "evidence_not_current" in proposal.blockers
    assert "evidence_conflict" in proposal.blockers
    assert proposal.evidence_summary["state_counts"] == {"available": 1, "conflicting": 1}
    assert proposal.evidence_summary["launch_authorized"] is False


def test_unknown_offering_fails_closed_and_keeps_sow_as_draft(authorities):
    proposal = build_fixture("unknown_offering.json", authorities)

    assert proposal.status == "blocked"
    assert "offering_kind_unknown" in proposal.blockers
    assert "offer_selection_blocked_until_classified" in proposal.blockers
    assert proposal.sow_draft["planning_only"] is True
    assert proposal.evidence_summary["launch_authorized"] is False


def test_missing_evidence_is_blocked_and_not_zero_filled(authorities):
    request = ConsultingOfferRequest.from_mapping({
        **load_request("complete_product.json").to_dict(),
        "evidence": [{
            "evidence_id": "missing-cost",
            "evidence_class": "manual",
            "state": "missing",
            "source_ref": "manual://consulting-offers/missing",
            "summary": "Cost was not supplied",
        }],
    })
    workspace_registry, report_registry, workspace, artifact_store = authorities
    proposal = build_consulting_offer_proposal(
        request,
        workspace=workspace,
        artifact_store=artifact_store,
        workspace_registry=workspace_registry,
        report_registry=report_registry,
    )

    assert proposal.status == "blocked"
    assert "evidence_missing" in proposal.blockers
    serialized = json.dumps(proposal.to_dict(), sort_keys=True).casefold()
    assert "contribution" not in serialized
    assert "computed_economics" not in serialized


def test_no_evidence_can_produce_needs_evidence_not_false_readiness(authorities):
    request = ConsultingOfferRequest.from_mapping({
        **load_request("complete_product.json").to_dict(),
        "selected_offer_ids": ["diagnostic-audit"],
        "evidence": [],
    })
    workspace_registry, report_registry, workspace, artifact_store = authorities
    proposal = build_consulting_offer_proposal(
        request,
        workspace=workspace,
        artifact_store=artifact_store,
        workspace_registry=workspace_registry,
        report_registry=report_registry,
    )

    assert proposal.status == "needs_evidence"
    assert proposal.evidence_summary["state_counts"] == {}
    assert proposal.client_safe_projection["evidence_required"]


def test_stale_evidence_blocks_and_retains_safe_next_action(authorities):
    proposal = build_fixture("stale_evidence.json", authorities)

    assert proposal.status == "blocked"
    assert "evidence_not_current" in proposal.blockers
    assert "live" not in proposal.next_action.casefold()


def test_service_only_offer_rejects_product_only_supplier_scope(authorities):
    request = ConsultingOfferRequest.from_mapping({
        **load_request("complete_service.json").to_dict(),
        "selected_offer_ids": ["supplier-logistics-feasibility"],
    })
    workspace_registry, report_registry, workspace, artifact_store = authorities
    proposal = build_consulting_offer_proposal(
        request,
        workspace=workspace,
        artifact_store=artifact_store,
        workspace_registry=workspace_registry,
        report_registry=report_registry,
    )

    assert proposal.status == "blocked"
    assert "offer_not_applicable:supplier-logistics-feasibility" in proposal.blockers


def test_currency_mismatch_fails_closed_without_conversion(authorities):
    request = ConsultingOfferRequest.from_mapping({
        **load_request("complete_product.json").to_dict(),
        "pricing_currency": "MXN",
    })
    workspace_registry, report_registry, workspace, artifact_store = authorities
    proposal = build_consulting_offer_proposal(
        request,
        workspace=workspace,
        artifact_store=artifact_store,
        workspace_registry=workspace_registry,
        report_registry=report_registry,
    )

    assert proposal.status == "blocked"
    assert "price_currency_mismatch:diagnostic-audit" in proposal.blockers
    assert proposal.price_ranges[0].currency == "USD"


def test_workspace_and_artifact_identity_are_bound(authorities):
    workspace_registry, report_registry, workspace, artifact_store = authorities
    forged = ClientWorkspace(
        workspace_id=workspace.workspace_id,
        name="forged workspace",
        workspace_type="client_service",
        mode="client_service",
    )
    with pytest.raises(ConsultingOfferCatalogError, match="workspace_identity_rejected"):
        build_consulting_offer_proposal(
            load_request("complete_product.json"),
            workspace=forged,
            artifact_store=artifact_store,
            workspace_registry=workspace_registry,
            report_registry=report_registry,
        )

    other = workspace_registry.register(ClientWorkspace(
        workspace_id="fixture-other-client", name="other client", workspace_type="client_service", mode="client_service"
    ))
    with pytest.raises(ConsultingOfferCatalogError, match="artifact_workspace_boundary_rejected"):
        build_consulting_offer_proposal(
            load_request("complete_product.json"),
            workspace=workspace,
            artifact_store=ArtifactStore(other, workspace_registry),
            workspace_registry=workspace_registry,
            report_registry=report_registry,
        )


def test_cross_workspace_component_report_is_rejected(authorities):
    workspace_registry, report_registry, workspace, artifact_store = authorities
    other = workspace_registry.register(ClientWorkspace(
        workspace_id="fixture-report-client", name="report client", workspace_type="client_service", mode="client_service"
    ))
    report_registry.register(CommercialReport(
        report_id="report_other_client", workspace_id=other.workspace_id, proposal_id="proposal-other",
        experiment_id="experiment-other", service_name="product_research", title="Other report",
        summary="Must not cross the workspace boundary.",
    ))
    request = ConsultingOfferRequest.from_mapping({
        **load_request("complete_product.json").to_dict(),
        "linked_component_report_ids": ["report_other_client"],
    })

    with pytest.raises(ConsultingOfferCatalogError, match="component_report_workspace_mismatch"):
        build_consulting_offer_proposal(
            request,
            workspace=workspace,
            artifact_store=artifact_store,
            workspace_registry=workspace_registry,
            report_registry=report_registry,
        )


@pytest.mark.parametrize("field", ["client_objective", "scope", "assumptions"])
def test_secret_shaped_values_are_rejected(field):
    raw = {
        "client_id": "client",
        "workspace_id": "workspace",
        "client_objective": "objective",
        "geography": "Mexico",
        "language": "es-MX",
        "scope": "scope",
        "offering_kind": "product",
        "selected_offer_ids": ["diagnostic-audit"],
    }
    raw[field] = ["internal_prompt"] if field == "assumptions" else "review bearer token"
    with pytest.raises(ValueError, match="unsafe"):
        ConsultingOfferRequest.from_mapping(raw)


def test_markdown_and_fingerprint_are_repeatable_and_redacted(authorities):
    first = build_fixture("complete_product.json", authorities)
    second = build_fixture("complete_product.json", authorities)

    assert first.proposal_id == second.proposal_id
    assert first.fingerprint == second.fingerprint
    assert first.to_dict() == second.to_dict()
    assert first.to_markdown() == second.to_markdown()
    assert "DRY RUN" in first.to_markdown()
    assert "manual://" not in first.to_markdown()
    assert "formula" not in first.to_markdown().casefold()


def test_component_report_reference_is_client_safe(authorities):
    workspace_registry, report_registry, workspace, artifact_store = authorities
    request = ConsultingOfferRequest.from_mapping({
        **load_request("complete_product.json").to_dict(),
        "linked_component_report_ids": ["report_fixture_market"],
    })
    proposal = build_consulting_offer_proposal(
        request,
        workspace=workspace,
        artifact_store=artifact_store,
        workspace_registry=workspace_registry,
        report_registry=report_registry,
    )

    assert proposal.component_reports[0].report_id == "report_fixture_market"
    assert "Sanitized market brief" not in json.dumps(proposal.client_safe_projection)
    assert proposal.client_safe_projection["component_reports"][0]["workspace_id"] == workspace.workspace_id
