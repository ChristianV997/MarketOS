"""Tests for services.geographic_opportunity.export."""
import json

import pytest

from services.geographic_opportunity import controls
from services.geographic_opportunity.export import build_client_safe_export, collect_evidence_notes
from services.geographic_opportunity.report import build_geographic_opportunity_report
from services.geographic_opportunity.schemas import FieldEvidence

from .conftest import GENERATED_AT, build_goods_offer


class TestClientSafeExportShape:
    def test_export_is_json_serializable(self):
        report = build_geographic_opportunity_report(build_goods_offer(), generated_at=GENERATED_AT)
        payload = build_client_safe_export(report)
        json.dumps(payload)  # must not raise

    def test_export_never_includes_an_affirmative_regulatory_status(self):
        report = build_geographic_opportunity_report(build_goods_offer(), generated_at=GENERATED_AT)
        payload = build_client_safe_export(report)
        assert payload["regulatory_status"] != "compliant"

    def test_export_excludes_notes_by_default(self):
        report = build_geographic_opportunity_report(build_goods_offer(), generated_at=GENERATED_AT)
        payload = build_client_safe_export(report)
        assert "evidence_notes" not in payload

    def test_export_carries_read_only_safety_flags(self):
        report = build_geographic_opportunity_report(build_goods_offer(), generated_at=GENERATED_AT)
        payload = build_client_safe_export(report)
        assert payload["read_only"] is True
        assert payload["network_calls"] is False
        assert payload["mutated"] is False


class TestNotesAreScreenedBeforeExport:
    def test_collect_evidence_notes_gathers_every_note(self):
        offer = build_goods_offer(origin_cost_evidence=FieldEvidence(quality="manual", note="supplier claims same-day dispatch"))
        report = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        assert "supplier claims same-day dispatch" in collect_evidence_notes(report)

    def test_a_secret_shaped_note_is_rejected_when_notes_are_requested(self):
        offer = build_goods_offer(origin_cost_evidence=FieldEvidence(quality="manual", note="bearer sk_live_abcdefghijklmnop"))
        report = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        with pytest.raises(controls.NegativeControlError):
            build_client_safe_export(report, include_notes=True)

    def test_a_clean_note_is_included_when_requested(self):
        offer = build_goods_offer(origin_cost_evidence=FieldEvidence(quality="manual", note="quote valid through end of quarter"))
        report = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        payload = build_client_safe_export(report, include_notes=True)
        assert "quote valid through end of quarter" in payload["evidence_notes"]
