"""Shared fixtures for services.supplier_logistics_consulting_integration
tests. Everything here builds REAL objects from the real upstream modules
(services.supplier_logistics_research, evaluation.companyos.service_delivery,
backend.workspaces, backend.deliverables) -- no mocks, no monkeypatching of
the consumed modules.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from backend.deliverables.registry import DeliverableRegistry
from backend.economics.kernel import EvidenceRef, MarketLane, Money
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry
from evaluation.commerce.canonical import SupplierOfferIdentity
from evaluation.companyos.service_delivery import (
    ClientEngagement,
    create_engagement,
    default_service_delivery_packages,
    transition_engagement,
)
from services.supplier_logistics_research.schemas import (
    CandidateBoundSupplierIdentity,
    CustomsDutyTaxProfile,
    FieldEvidence,
    GoodsLogisticsProfile,
    LeadTimeWindow,
    MoqAvailability,
    ReturnsDefectAssumptions,
    ServiceCapacityProfile,
    ShippingCostProfile,
    SupplierLogisticsOffer,
)
from services.supplier_logistics_research.report import build_supplier_logistics_report

GENERATED_AT = "2026-02-01T00:00:00Z"


def observed_evidence(evidence_id: str = "ev-observed") -> FieldEvidence:
    ref = EvidenceRef(evidence_id=evidence_id, source_type="manual_import", evidence_state="observed", human_confirmed=True)
    return FieldEvidence(quality="observed", evidence_ref=ref)


@pytest.fixture
def ws_registry(tmp_path) -> WorkspaceRegistry:
    return WorkspaceRegistry(path=str(tmp_path / "workspaces.json"))


@pytest.fixture
def dv_registry(tmp_path) -> DeliverableRegistry:
    return DeliverableRegistry(path=str(tmp_path / "deliverables.json"))


@pytest.fixture
def workspace(ws_registry) -> ClientWorkspace:
    ws = ClientWorkspace(name="acme-consulting-client", workspace_type="client_service")
    ws_registry.register(ws)
    return ws


@pytest.fixture
def other_workspace(ws_registry) -> ClientWorkspace:
    ws = ClientWorkspace(name="beta-consulting-client", workspace_type="client_service")
    ws_registry.register(ws)
    return ws


@pytest.fixture
def package():
    packages = {item.package_id: item for item in default_service_delivery_packages()}
    return packages["product-validation-sprint"]


@pytest.fixture
def evidence_collection_engagement(workspace, package) -> ClientEngagement:
    """A real ClientEngagement walked, via the real state machine, from
    intake all the way to evidence_collection -- the only lifecycle state
    record_supplier_logistics_evidence accepts."""
    engagement = create_engagement(client_id="acme-consulting-client", workspace=workspace, package=package, scope="supplier feasibility review")
    for state in ("screening", "eligible", "scoped", "evidence_collection"):
        engagement = transition_engagement(engagement, state)
    return engagement


def build_goods_offer(
    *,
    candidate_id: str = "cand-goods",
    currency: str = "USD",
    price_evidence: FieldEvidence | None = None,
    duty_rate: Decimal | None = Decimal("0.03"),
    tax_rate: Decimal | None = Decimal("0.07"),
    customs_evidence: FieldEvidence | None = None,
    logistics_evidence: FieldEvidence | None = None,
    lane: MarketLane | None = None,
) -> SupplierLogisticsOffer:
    identity = CandidateBoundSupplierIdentity(candidate_id, SupplierOfferIdentity(f"sup-{candidate_id}", f"off-{candidate_id}", f"sku-{candidate_id}"))
    goods = GoodsLogisticsProfile(
        moq_availability=MoqAvailability(minimum_order_quantity=50, availability_status="in_stock", evidence=observed_evidence()),
        lead_time=LeadTimeWindow(minimum_days=10, maximum_days=20, evidence=observed_evidence()),
        fulfillment_mode="wholesale_fba",
        customs=CustomsDutyTaxProfile(duty_rate=duty_rate, tax_rate=tax_rate, evidence=customs_evidence or observed_evidence()),
        returns_defects=ReturnsDefectAssumptions(return_rate=Decimal("0.02"), evidence=observed_evidence()),
        shipping=ShippingCostProfile(supplier_shipping=Money(Decimal("1.20"), currency), evidence=observed_evidence()),
        supplier_evidence=observed_evidence(),
        logistics_evidence=logistics_evidence or observed_evidence(),
    )
    return SupplierLogisticsOffer(
        identity=identity,
        offering_kind="goods",
        quoted_price=Money(Decimal("12.50"), currency, evidence_ref=EvidenceRef(evidence_id="price-ev", evidence_state="observed", human_confirmed=True)),
        price_evidence=price_evidence or observed_evidence(),
        goods=goods,
        lane=lane,
        captured_at="2026-01-15T00:00:00Z",
    )


def build_service_offer(*, candidate_id: str = "cand-service", currency: str = "USD") -> SupplierLogisticsOffer:
    identity = CandidateBoundSupplierIdentity(candidate_id, SupplierOfferIdentity(f"sup-{candidate_id}", f"off-{candidate_id}", f"svc-{candidate_id}"))
    service = ServiceCapacityProfile(
        weekly_capacity_hours=Decimal("40"),
        subcontractor_dependency=True,
        sla_assumption="next-business-day response claimed by provider",
        geographic_coverage=("TX", "OK"),
        evidence=FieldEvidence(quality="manual"),
    )
    return SupplierLogisticsOffer(
        identity=identity,
        offering_kind="service",
        quoted_price=Money(Decimal("450.00"), currency),
        price_evidence=FieldEvidence(quality="manual"),
        service=service,
        captured_at="2026-01-15T00:00:00Z",
    )


def build_hybrid_offer(*, candidate_id: str = "cand-hybrid", currency: str = "USD") -> SupplierLogisticsOffer:
    goods_offer = build_goods_offer(candidate_id=candidate_id, currency=currency)
    identity = goods_offer.identity
    service = ServiceCapacityProfile(
        weekly_capacity_hours=Decimal("20"),
        subcontractor_dependency=False,
        sla_assumption="installation within 48 hours, claimed by provider",
        geographic_coverage=("CA", "AZ"),
        evidence=FieldEvidence(quality="manual"),
    )
    return SupplierLogisticsOffer(
        identity=identity,
        offering_kind="hybrid",
        quoted_price=goods_offer.quoted_price,
        price_evidence=goods_offer.price_evidence,
        goods=goods_offer.goods,
        service=service,
        lane=goods_offer.lane,
        captured_at="2026-01-15T00:00:00Z",
    )


def build_unknown_offer(*, candidate_id: str = "cand-unknown") -> SupplierLogisticsOffer:
    identity = CandidateBoundSupplierIdentity(candidate_id, SupplierOfferIdentity(f"sup-{candidate_id}", f"off-{candidate_id}", f"sku-{candidate_id}"))
    return SupplierLogisticsOffer(identity=identity, offering_kind="unknown", quoted_price=None, price_evidence=FieldEvidence(quality="missing"))


def build_report(offer: SupplierLogisticsOffer, *, generated_at: str = GENERATED_AT):
    return build_supplier_logistics_report(offer, generated_at=generated_at)
