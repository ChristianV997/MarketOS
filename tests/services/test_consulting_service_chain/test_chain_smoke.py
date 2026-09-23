"""Real import/call-chain smoke test across the integrated consulting
service chain: offer catalog -> engagement -> economics -> portfolio
synthesis -> evidence register -> secure client delivery.

This is not a duplicate of any single package's own unit tests: those
verify one stage in isolation with mocked/local registries. This test
proves the six retained packages actually compose under one shared
workspace identity, and that the final delivery stage's TrustOS boundary
(check_workspace_leakage) holds on real output from the earlier stages.
"""
from __future__ import annotations

import json
from pathlib import Path

import backend.core.persistence as persistence
import pytest
from backend.organization.commercial_report import CommercialReport
from backend.organization.portfolio_report import PortfolioReport
from backend.organization.report_registry import ReportRegistry, get_report_registry
from backend.workspaces.artifact_store import ArtifactStore
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry

from services.consulting_delivery import package_consulting_deliverable
from services.consulting_economics import build_consulting_economics_report
from services.consulting_engagement import ConsultingEngagementRequest, build_consulting_engagement
from services.consulting_evidence_register import build_evidence_register
from services.consulting_offers import ConsultingOfferRequest, build_consulting_offer_proposal
from services.consulting_portfolio import synthesize_portfolio

WORKSPACE_ID = "fixture-consulting-client"
OFFERS_FIXTURES = Path(__file__).parents[2] / "fixtures" / "consulting_offers"
ENGAGEMENT_FIXTURES = Path(__file__).parents[2] / "fixtures" / "consulting_engagement"
ECONOMICS_FIXTURES = Path(__file__).parents[2] / "fixtures" / "consulting_economics"


@pytest.fixture()
def local_authorities(tmp_path, monkeypatch):
    """The workspace/report registry setup consulting_offers and
    consulting_engagement each require, shared by both stages so they
    operate against one real, registered client workspace."""
    monkeypatch.setattr(persistence, "STATE_DIR", str(tmp_path / "state"))
    workspace_registry = WorkspaceRegistry(str(tmp_path / "workspaces.json"))
    workspace = workspace_registry.register(
        ClientWorkspace(
            workspace_id=WORKSPACE_ID,
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
    artifact_store = ArtifactStore(workspace, workspace_registry)
    return workspace_registry, report_registry, workspace, artifact_store


@pytest.fixture()
def global_report_registry():
    """package_consulting_deliverable calls the process-global
    get_report_registry() singleton (not the local instances above), so
    the delivery stage is exercised against that registry directly,
    matching the package's own test_packager.py pattern."""
    registry = get_report_registry()
    registry.reports.clear()
    registry.portfolio_reports.clear()
    yield registry
    registry.reports.clear()
    registry.portfolio_reports.clear()


def test_full_chain_composes_under_one_workspace_identity(local_authorities, global_report_registry):
    workspace_registry, report_registry, workspace, artifact_store = local_authorities

    # 1. Offer catalog / proposal stage.
    offer_request = ConsultingOfferRequest.from_mapping(
        json.loads((OFFERS_FIXTURES / "complete_product.json").read_text(encoding="utf-8"))
    )
    proposal = build_consulting_offer_proposal(
        offer_request,
        workspace=workspace,
        artifact_store=artifact_store,
        workspace_registry=workspace_registry,
        report_registry=report_registry,
    )
    assert proposal.workspace_id == WORKSPACE_ID
    assert proposal.fingerprint

    # 2. Engagement stage.
    engagement_request = ConsultingEngagementRequest.from_mapping(
        json.loads((ENGAGEMENT_FIXTURES / "complete_product.json").read_text(encoding="utf-8"))
    )
    engagement = build_consulting_engagement(
        engagement_request,
        workspace=workspace,
        artifact_store=artifact_store,
        workspace_registry=workspace_registry,
        report_registry=report_registry,
    )
    assert engagement.workspace_id == WORKSPACE_ID
    assert engagement.fingerprint

    # 3. Economics stage (standalone, product-agnostic; no workspace coupling by design).
    economics = build_consulting_economics_report(
        json.loads((ECONOMICS_FIXTURES / "project_complete.json").read_text(encoding="utf-8"))
    )
    assert economics.fingerprint

    # 4. Portfolio synthesis and evidence register consume a generic
    # persisted-component-report envelope; wrap each upstream stage's
    # already-computed fingerprint/status into that shape, proving the
    # two "one register" / "one synthesis" authorities are reusable
    # across heterogeneous component services, not just one pillar.
    # NOTE: synthesize_portfolio reads `service`; build_evidence_register
    # reads `service_name` and additionally requires `workspace_id` on
    # every envelope and a status drawn from its own fixed vocabulary
    # (`completed|partial|unavailable|blocked|draft|empty`) rather than
    # each component's own status enum. The two "generic component
    # report" consumers do not share one envelope schema today; this
    # smoke test supplies both key spellings rather than papering over
    # the mismatch, and it is called out as a follow-up compatibility
    # adapter in docs/ai/CONSULTING_SERVICE_CHAIN_INTEGRATION.md.
    envelopes = [
        {
            "report_id": f"offer-{proposal.proposal_id}",
            "fingerprint": proposal.fingerprint,
            "service": "consulting_offers",
            "service_name": "consulting_offers",
            "workspace_id": WORKSPACE_ID,
            "status": "completed",
            "facts": {"offering_kind": proposal.offering_kind},
        },
        {
            "report_id": f"engagement-{engagement.engagement_id}",
            "fingerprint": engagement.fingerprint,
            "service": "consulting_engagement",
            "service_name": "consulting_engagement",
            "workspace_id": WORKSPACE_ID,
            "status": "completed",
            "facts": {"offering_kind": engagement.offering_kind},
        },
        {
            "report_id": f"economics-{economics.service_id}",
            "fingerprint": economics.fingerprint,
            "service": "consulting_economics",
            "service_name": "consulting_economics",
            "workspace_id": WORKSPACE_ID,
            "status": "completed",
            "facts": {"recommendation": economics.recommendation},
        },
    ]
    portfolio = synthesize_portfolio(envelopes)
    assert portfolio.report_ids == sorted(item["report_id"] for item in envelopes)

    register = build_evidence_register(envelopes, workspace_id=WORKSPACE_ID)
    assert register.workspace_id == WORKSPACE_ID
    assert len(register.report_refs) == len(envelopes)

    # 5. Secure client delivery: register the upstream results as a real
    # CommercialReport + PortfolioReport in the global report registry
    # (the registry package_consulting_deliverable actually reads from),
    # then package a client-safe deliverable that references them.
    global_report_registry.register(
        CommercialReport(
            report_id="chain-smoke-commercial",
            workspace_id=WORKSPACE_ID,
            proposal_id=proposal.proposal_id,
            experiment_id="chain-smoke",
            service_name="consulting_offers",
            title="Chain smoke commercial report",
            summary="Sanitized chain-smoke summary.",
            findings="Sanitized chain-smoke findings.",
            recommendations=[],
            risk_flags=[],
            next_actions=[],
            metadata={},
            status="completed",
        )
    )
    global_report_registry.register_portfolio_report(
        PortfolioReport(
            portfolio_report_id="chain-smoke-portfolio",
            workspace_id=WORKSPACE_ID,
            title="Chain smoke portfolio",
            summary="Sanitized chain-smoke portfolio summary.",
            report_ids=list(portfolio.report_ids),
            service_counts={},
            status_counts={},
            top_recommendations=[],
            recurring_risk_flags=[],
            next_actions=[],
            metrics={},
            metadata={},
        )
    )

    delivery = package_consulting_deliverable(
        workspace_id=WORKSPACE_ID,
        package_id="chain-smoke-delivery",
        title="Chain Smoke Delivery",
        objective="Prove the integrated consulting chain composes end to end.",
        executive_summary="All six retained consulting packages compose under one workspace identity.",
        metadata={"assumptions": list(proposal.evidence_summary.keys()) if isinstance(proposal.evidence_summary, dict) else []},
        report_ids=["chain-smoke-commercial"],
        portfolio_report_ids=["chain-smoke-portfolio"],
    )
    assert delivery.workspace_id == WORKSPACE_ID
    assert delivery.compute_fingerprint()
    assert len(delivery.sections) == 2


def test_cross_workspace_report_is_rejected_by_the_delivery_boundary(global_report_registry):
    """Fail-closed: a report registered under a different workspace_id must
    never be packaged into another workspace's client deliverable."""
    global_report_registry.register(
        CommercialReport(
            report_id="other-workspace-report",
            workspace_id="some-other-workspace",
            proposal_id="p",
            experiment_id="e",
            service_name="test",
            title="T",
            summary="S",
            findings="F",
            recommendations=[],
            risk_flags=[],
            next_actions=[],
            metadata={},
            status="completed",
        )
    )
    with pytest.raises(ValueError, match="cross_workspace_leakage"):
        package_consulting_deliverable(
            workspace_id=WORKSPACE_ID,
            package_id="should-fail",
            title="T",
            objective="O",
            executive_summary="E",
            metadata={},
            report_ids=["other-workspace-report"],
        )
