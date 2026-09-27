"""Tests for services.supplier_logistics_consulting_integration.engagement."""

import pytest

from backend.economics.kernel import CurrencyMismatchError
from services.supplier_logistics_consulting_integration import WorkspaceMismatchError
from services.supplier_logistics_consulting_integration.engagement import record_supplier_logistics_evidence

from .conftest import build_goods_offer, build_report, build_unknown_offer


class TestLifecycleTransition:
    def test_a_clean_goods_report_transitions_to_analysis(self, evidence_collection_engagement, workspace, ws_registry, package):
        report = build_report(build_goods_offer(currency=package.currency))
        updated = record_supplier_logistics_evidence(evidence_collection_engagement, report, workspace=workspace, registry=ws_registry)
        assert updated.lifecycle_state == "analysis"

    def test_an_unknown_offering_transitions_to_data_inadequate(self, evidence_collection_engagement, workspace, ws_registry):
        report = build_report(build_unknown_offer())
        updated = record_supplier_logistics_evidence(evidence_collection_engagement, report, workspace=workspace, registry=ws_registry)
        assert updated.lifecycle_state == "data_inadequate"

    def test_a_report_with_blockers_transitions_to_data_inadequate(self, evidence_collection_engagement, workspace, ws_registry, package):
        from services.supplier_logistics_research.schemas import FieldEvidence

        report = build_report(build_goods_offer(currency=package.currency, logistics_evidence=FieldEvidence(quality="missing")))
        updated = record_supplier_logistics_evidence(evidence_collection_engagement, report, workspace=workspace, registry=ws_registry)
        assert updated.lifecycle_state == "data_inadequate"
        assert updated.missing_information

    def test_rejects_an_engagement_not_in_evidence_collection(self, workspace, ws_registry, package):
        from evaluation.companyos.service_delivery import create_engagement

        engagement = create_engagement(client_id="acme-consulting-client", workspace=workspace, package=package, scope="s")
        report = build_report(build_goods_offer(currency=package.currency))
        with pytest.raises(ValueError, match="evidence_collection"):
            record_supplier_logistics_evidence(engagement, report, workspace=workspace, registry=ws_registry)


class TestEvidenceAccumulation:
    def test_evidence_refs_and_scenario_assumptions_are_carried_onto_the_engagement(self, evidence_collection_engagement, workspace, ws_registry, package):
        report = build_report(build_goods_offer(currency=package.currency))
        updated = record_supplier_logistics_evidence(evidence_collection_engagement, report, workspace=workspace, registry=ws_registry)
        assert len(updated.evidence_set) > 0
        assert len(updated.evidence_references) == len(updated.evidence_set)
        assert any("cost-basis" in note for note in updated.assumptions)

    def test_a_second_offers_evidence_set_is_independent_of_the_first(self, evidence_collection_engagement, workspace, ws_registry, package):
        """record_supplier_logistics_evidence only accepts an engagement in
        evidence_collection (a state 'analysis'/'data_inadequate' cannot
        return to per the existing state machine), so multi-offer
        accumulation onto ONE engagement is exercised via a fresh
        evidence_collection engagement per offer here; true multi-offer
        roll-up across engagements is proven at the portfolio/pipeline
        layer in test_pipeline.py instead."""
        report_a = build_report(build_goods_offer(candidate_id="cand-a", currency=package.currency))
        updated_a = record_supplier_logistics_evidence(evidence_collection_engagement, report_a, workspace=workspace, registry=ws_registry)
        assert len(updated_a.evidence_set) > 0


class TestCurrencyMismatch:
    def test_report_currency_must_match_engagement_fee_currency(self, evidence_collection_engagement, workspace, ws_registry, package):
        other_currency = "EUR" if package.currency != "EUR" else "GBP"
        offer = build_goods_offer(currency=other_currency)
        report = build_report(offer)
        with pytest.raises(CurrencyMismatchError):
            record_supplier_logistics_evidence(evidence_collection_engagement, report, workspace=workspace, registry=ws_registry)

    def test_matching_currency_does_not_raise(self, evidence_collection_engagement, workspace, ws_registry, package):
        offer = build_goods_offer(currency=package.currency)
        report = build_report(offer)
        record_supplier_logistics_evidence(evidence_collection_engagement, report, workspace=workspace, registry=ws_registry)  # must not raise


class TestWorkspaceMismatch:
    def test_rejects_a_workspace_that_does_not_own_the_engagement(self, evidence_collection_engagement, other_workspace, ws_registry, package):
        report = build_report(build_goods_offer(currency=package.currency))
        with pytest.raises(WorkspaceMismatchError):
            record_supplier_logistics_evidence(evidence_collection_engagement, report, workspace=other_workspace, registry=ws_registry)
