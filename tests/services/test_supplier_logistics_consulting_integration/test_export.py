"""Tests for services.supplier_logistics_consulting_integration.export."""
import json
from dataclasses import replace

import pytest

from evaluation.trustos.client_workspace_isolation import CLIENT_EXPORT_FIELDS, ClientWorkspaceEvidenceExport
from services.supplier_logistics_consulting_integration import CrossClientLeakageError, WorkspaceMismatchError
from services.supplier_logistics_consulting_integration.export import (
    build_client_safe_deliverable,
    build_client_safe_deliverable_payload,
    collect_supplier_notes,
    export_supplier_logistics_status,
)

from .conftest import build_goods_offer, build_report, build_unknown_offer


class TestNarrowTrustOsExport:
    def test_export_client_evidence_succeeds_for_a_clean_report(self, workspace, ws_registry):
        report = build_report(build_goods_offer())
        export = export_supplier_logistics_status(report, workspace=workspace, registry=ws_registry)
        assert isinstance(export, ClientWorkspaceEvidenceExport)
        assert export.workspace_id == workspace.workspace_id
        assert set(export.payload.keys()) <= CLIENT_EXPORT_FIELDS

    def test_export_status_reflects_blockers(self, workspace, ws_registry):
        report = build_report(build_unknown_offer())
        export = export_supplier_logistics_status(report, workspace=workspace, registry=ws_registry)
        assert export.payload["status"] == "unassessed"

    def test_export_rejects_a_forged_workspace_object(self, workspace, ws_registry):
        # export_supplier_logistics_status takes a single workspace object
        # (there is no separate "claimed" id to compare it against, unlike
        # record_supplier_logistics_evidence's engagement.workspace_id), so
        # its only meaningful workspace-identity negative control is a
        # forged object that merely *claims* the right workspace_id without
        # being the genuinely registered record -- require_workspace_match
        # re-fetches from the registry and compares byte-for-byte.
        report = build_report(build_goods_offer())
        forged = type(workspace)(workspace_id=workspace.workspace_id, name="forged", workspace_type="client_service")
        with pytest.raises(WorkspaceMismatchError):
            export_supplier_logistics_status(report, workspace=forged, registry=ws_registry)

    def test_export_is_json_serializable_and_bounded(self, workspace, ws_registry):
        report = build_report(build_goods_offer())
        export = export_supplier_logistics_status(report, workspace=workspace, registry=ws_registry)
        json.dumps(export.to_dict())  # must not raise
        assert export.payload_size_bytes <= export.max_payload_bytes


class TestRicherDeliverablePayload:
    def test_payload_excludes_supplier_notes_by_default(self, workspace):
        offer = build_goods_offer()
        report = build_report(offer)
        payload = build_client_safe_deliverable_payload(report)
        assert "supplier_notes" not in payload

    def test_collect_supplier_notes_gathers_every_field_note(self):
        from services.supplier_logistics_research.schemas import FieldEvidence

        offer = build_goods_offer()
        offer = replace(offer, price_evidence=FieldEvidence(quality="manual", note="supplier claims same-day dispatch"))
        report = build_report(offer)
        notes = collect_supplier_notes(report)
        assert "supplier claims same-day dispatch" in notes


class TestClientSafeDeliverable:
    def test_builds_and_registers_a_completed_deliverable_for_a_clean_report(
        self, evidence_collection_engagement, package, workspace, ws_registry, dv_registry
    ):
        report = build_report(build_goods_offer(currency=package.currency))
        deliverable = build_client_safe_deliverable(
            report, engagement=evidence_collection_engagement, package=package, workspace=workspace,
            registry=ws_registry, deliverable_registry=dv_registry,
        )
        assert deliverable.status == "completed"
        assert dv_registry.get_package(deliverable.package_id) is deliverable

    def test_a_blocked_report_produces_a_blocked_deliverable_not_an_optimistic_one(
        self, evidence_collection_engagement, package, workspace, ws_registry, dv_registry
    ):
        report = build_report(build_unknown_offer())
        deliverable = build_client_safe_deliverable(
            report, engagement=evidence_collection_engagement, package=package, workspace=workspace,
            registry=ws_registry, deliverable_registry=dv_registry,
        )
        assert deliverable.status == "blocked"
        assert deliverable.missing_evidence

    def test_rejects_a_workspace_mismatch(self, evidence_collection_engagement, package, other_workspace, ws_registry, dv_registry):
        report = build_report(build_goods_offer(currency=package.currency))
        with pytest.raises(WorkspaceMismatchError):
            build_client_safe_deliverable(
                report, engagement=evidence_collection_engagement, package=package, workspace=other_workspace,
                registry=ws_registry, deliverable_registry=dv_registry,
            )

    def test_cross_client_leakage_in_a_supplier_note_fails_closed(
        self, evidence_collection_engagement, package, workspace, ws_registry, dv_registry
    ):
        from services.supplier_logistics_research.schemas import FieldEvidence

        offer = build_goods_offer(currency=package.currency)
        leaky_customs = replace(
            offer.goods.customs,
            evidence=FieldEvidence(quality="manual", note="our internal pricing formula for other suppliers assumes a 12% markup"),
        )
        leaky_goods = replace(offer.goods, customs=leaky_customs)
        leaky_offer = replace(offer, goods=leaky_goods)
        report = build_report(leaky_offer)
        with pytest.raises(CrossClientLeakageError):
            build_client_safe_deliverable(
                report, engagement=evidence_collection_engagement, package=package, workspace=workspace,
                registry=ws_registry, deliverable_registry=dv_registry, include_supplier_notes=True,
            )
