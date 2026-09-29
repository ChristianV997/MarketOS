"""Proves the known envelope mismatch between consulting_portfolio (reads
`service`) and consulting_evidence_register (reads `service_name`,
requires `workspace_id`, and a fixed status vocabulary) is normalized in
exactly one place: build_component_report_envelope. Neither consumer is
modified -- one envelope, built once, is accepted by both, unmodified."""
from __future__ import annotations

import pytest

from services.consulting_evidence_register import ConsultingEvidenceInputError, build_component_report_envelope, build_evidence_register
from services.consulting_portfolio import PortfolioInputError, synthesize_portfolio


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


def test_consumers_reject_mixed_workspace_envelopes():
    envelopes = [
        build_component_report_envelope(
            report_id="offer-workspace-1", fingerprint="fp-1", service="consulting_offers",
            workspace_id="workspace-1", status="completed",
        ),
        build_component_report_envelope(
            report_id="offer-workspace-2", fingerprint="fp-2", service="consulting_offers",
            workspace_id="workspace-2", status="completed",
        ),
    ]

    with pytest.raises(PortfolioInputError, match="workspace mismatch"):
        synthesize_portfolio(envelopes)
    with pytest.raises(ConsultingEvidenceInputError, match="workspace mismatch"):
        build_evidence_register(envelopes)


def test_evidence_register_preserves_envelope_facts_and_provenance():
    envelope = build_component_report_envelope(
        report_id="report-facts", fingerprint="fp-facts", service="consulting_offers",
        workspace_id="workspace-1", status="completed", observed_at="2026-09-26T00:00:00Z",
        facts={"market_research": ["Synthetic fixture finding"]},
    )

    register = build_evidence_register([envelope])
    entry = register.evidence_by_area["market_research"][0]
    assert entry["facts"] == ["Synthetic fixture finding"]
    assert entry["source_report_id"] == "report-facts"
    assert entry["source_fingerprint"] == "fp-facts"
    assert entry["observed_at"] == "2026-09-26T00:00:00Z"
    assert entry["evidence_state"] == "unknown"
    assert register.readiness is False


def test_evidence_register_preserves_envelope_stale_and_conflict_flags():
    envelopes = [
        build_component_report_envelope(
            report_id="report-stale", fingerprint="fp-stale", service="consulting_offers",
            workspace_id="workspace-1", status="completed", stale=True,
            facts={"market_research": ["Synthetic stale finding"]},
        ),
        build_component_report_envelope(
            report_id="report-conflict", fingerprint="fp-conflict", service="consulting_engagement",
            workspace_id="workspace-1", status="completed", conflicting=True,
            facts={"supplier_logistics": ["Synthetic conflicting finding"]},
        ),
    ]

    register = build_evidence_register(envelopes)
    assert register.evidence_by_area["market_research"][0]["evidence_state"] == "stale"
    assert register.evidence_by_area["supplier_logistics"][0]["evidence_state"] == "conflict"
    assert register.conflicts
    assert register.readiness is False


def test_evidence_register_does_not_treat_partial_report_as_complete():
    envelope = build_component_report_envelope(
        report_id="report-partial", fingerprint="fp-partial", service="consulting_offers",
        workspace_id="workspace-1", status="partial",
    )

    register = build_evidence_register([envelope])
    assert register.status == "partial"
    assert register.readiness is False
    assert "consulting_offers:report_partial" in register.gaps
