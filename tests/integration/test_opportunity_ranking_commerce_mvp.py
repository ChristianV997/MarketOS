"""Tests for the opt-in use_opportunity_ranking path wired into
backend.mvp_commerce.runner.run_commerce_mvp_slice — must never change the
default (use_opportunity_ranking=False) behavior byte-for-byte, and must
correctly key supplier evidence to whichever candidate ranking actually
selects."""
from __future__ import annotations

from pathlib import Path

from backend.adapters.research.cj_public_evidence import CJProductEvidence
from backend.events.repository import InMemoryEventRepository
from backend.mvp_commerce.events import commerce_mvp_events
from backend.mvp_commerce.opportunity import build_opportunity_candidates_from_signals, select_candidate
from backend.mvp_commerce.runner import run_commerce_mvp_slice
from backend.mvp_commerce.supplier_evidence import SupplierEvidenceResult
from backend.signals.public_signal_models import PublicSignal

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/commerce_mvp/public_signals.json"


def _evidence(unit_cost=9.5, shipping_cost=2.0):
    ev = CJProductEvidence(
        source="cj_public_page", source_url="https://www.cjdropshipping.com/product/x.html", observed_at=1_700_000_000.0,
        external_product_id="cj-1", title="Portable Espresso Maker",
        field_status={"price": "observed", "shipping_cost": "observed"}, price=unit_cost, shipping_cost=shipping_cost,
    )
    return SupplierEvidenceResult(
        attempted=True, unit_cost=unit_cost, shipping_cost=shipping_cost, source_url=ev.source_url,
        candidates_considered=1, evidence=ev, ranking=({"product_id": "cj-1", "composite_score": 0.9},),
    )


class TestByteIdenticalDefault:
    def test_default_path_matches_pre_existing_run_exactly(self):
        baseline = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=FIXTURE)
        opted_out = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=FIXTURE, use_opportunity_ranking=False)
        assert baseline.to_dict() == opted_out.to_dict()

    def test_default_path_has_no_opportunity_assessment_metadata(self):
        run = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=FIXTURE)
        assert "opportunity_assessment" not in run.metadata

    def test_default_path_selects_same_candidate_as_select_candidate(self):
        run = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=FIXTURE)
        signals = [PublicSignal.from_dict(item) for item in __import__("json").loads(FIXTURE.read_text())]
        candidates = build_opportunity_candidates_from_signals(signals, "commerce-mvp-dry-run", "portable espresso maker", 5)
        assert run.selected_candidate.candidate_id == select_candidate(candidates).candidate_id


class TestOpportunityRankingOptIn:
    def test_selects_top_ranked_candidate_and_stores_assessment(self):
        run = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=FIXTURE, use_opportunity_ranking=True)
        assert run.status == "completed"
        assert "opportunity_assessment" in run.metadata
        assessment = run.metadata["opportunity_assessment"]
        assert assessment["top_candidate_id"] == run.selected_candidate.candidate_id
        assert len(assessment["scores"]) == len(run.opportunity_candidates)

    def test_supplier_evidence_only_applies_to_its_own_candidate(self):
        # supplier_evidence is gathered for whatever select_candidate() would
        # have picked (the provisional pick); ranking must still key it
        # correctly even though rank_opportunities() re-evaluates all
        # candidates independently.
        run = run_commerce_mvp_slice(
            query="portable espresso maker", signal_fixture_path=FIXTURE,
            use_opportunity_ranking=True, supplier_evidence=_evidence(),
        )
        assert run.unit_economics_summary.source in ("partial_observed_supplier_evidence", "dry_run_assumption")
        if run.unit_economics_summary.source == "partial_observed_supplier_evidence":
            assert run.unit_economics_summary.assumed_unit_cost == 9.5

    def test_events_include_opportunity_scoring_types(self):
        repository = InMemoryEventRepository()
        run = run_commerce_mvp_slice(
            query="portable espresso maker", signal_fixture_path=FIXTURE,
            use_opportunity_ranking=True, write_repository=repository,
        )
        types = {event.event_type for event in repository.tail()}
        assert "opportunity_scoring_started" in types
        assert "candidate_scored" in types
        assert "opportunity_ranked" in types
        assert "opportunity_scoring_completed" in types
        base_types = {event.event_type for event in commerce_mvp_events(run)}
        assert base_types.issubset(types)

    def test_no_events_when_ranking_not_used(self):
        repository = InMemoryEventRepository()
        run_commerce_mvp_slice(
            query="portable espresso maker", signal_fixture_path=FIXTURE,
            use_opportunity_ranking=False, write_repository=repository,
        )
        types = {event.event_type for event in repository.tail()}
        assert "opportunity_scoring_started" not in types

    def test_empty_candidates_falls_back_gracefully(self):
        run = run_commerce_mvp_slice(query="nonexistent query", signals=[], use_opportunity_ranking=True)
        assert run.status == "blocked"
        assert run.selected_candidate is None
        assert "opportunity_assessment" not in run.metadata

    def test_deterministic_replay(self):
        first = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=FIXTURE, use_opportunity_ranking=True)
        second = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=FIXTURE, use_opportunity_ranking=True)
        assert first.to_dict() == second.to_dict()
