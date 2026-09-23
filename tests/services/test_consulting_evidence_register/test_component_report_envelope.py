"""Proves the known envelope mismatch between consulting_portfolio (reads
`service`) and consulting_evidence_register (reads `service_name`,
requires `workspace_id`, and a fixed status vocabulary) is normalized in
exactly one place: build_component_report_envelope. Neither consumer is
modified -- one envelope, built once, is accepted by both, unmodified."""
from __future__ import annotations

import pytest

from services.consulting_evidence_register import ConsultingEvidenceInputError, build_component_report_envelope, build_evidence_register
from services.consulting_portfolio import synthesize_portfolio


def test_envelope_carries_both_service_and_service_name_aliased():
    envelope = build_component_report_envelope(
        report_id="report-1",
        fingerprint="fp-1",
        service="consulting_offers",
        workspace_id="workspace-1",
        status="completed",
    )
    assert envelope["service"] == "consulting_offers"
    assert envelope["service_name"] == "consulting_offers"


def test_envelope_rejects_a_status_outside_the_fixed_vocabulary():
    with pytest.raises(ConsultingEvidenceInputError):
        build_component_report_envelope(
            report_id="report-1", fingerprint="fp-1", service="consulting_offers",
            workspace_id="workspace-1", status="not_a_real_status",
        )


def test_one_envelope_is_accepted_unmodified_by_synthesize_portfolio():
    envelope = build_component_report_envelope(
        report_id="report-1", fingerprint="fp-1", service="consulting_offers",
        workspace_id="workspace-1", status="completed", facts={"offering_kind": "product"},
    )
    portfolio = synthesize_portfolio([envelope])
    assert list(portfolio.report_ids) == ["report-1"]


def test_one_envelope_is_accepted_unmodified_by_build_evidence_register():
    envelope = build_component_report_envelope(
        report_id="report-1", fingerprint="fp-1", service="consulting_offers",
        workspace_id="workspace-1", status="completed",
    )
    register = build_evidence_register([envelope], workspace_id="workspace-1")
    assert register.workspace_id == "workspace-1"
    assert len(register.report_refs) == 1


def test_the_same_list_of_envelopes_satisfies_both_consumers_at_once():
    envelopes = [
        build_component_report_envelope(
            report_id="offer-1", fingerprint="fp-offer", service="consulting_offers",
            workspace_id="workspace-1", status="completed", facts={"offering_kind": "product"},
        ),
        build_component_report_envelope(
            report_id="engagement-1", fingerprint="fp-engagement", service="consulting_engagement",
            workspace_id="workspace-1", status="partial", facts={"offering_kind": "product"},
        ),
    ]
    portfolio = synthesize_portfolio(envelopes)
    register = build_evidence_register(envelopes, workspace_id="workspace-1")
    assert set(portfolio.report_ids) == {"offer-1", "engagement-1"}
    assert len(register.report_refs) == 2
