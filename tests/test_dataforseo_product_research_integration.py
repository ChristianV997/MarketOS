"""Canonical dry-run integration tests for
backend.adapters.research.dataforseo's ProductResearchProvider-shaped
`discover()` path and its attachment to
backend.mvp_commerce.product_research.ResearchCandidate.

Complements tests/test_dataforseo_research_adapter.py (which covers
fetch_search_evidence/discover_search_queries/health() directly). This file
covers the newer discover()/DataForSEOResearchAdapter/
signals_to_additional_evidence surface added on top of that PR.
"""
from __future__ import annotations

import pytest

from backend.adapters.research import dataforseo as adapter
from backend.contracts.adapters import SidecarContext
from backend.mvp_commerce.opportunity import OpportunityCandidate
from backend.mvp_commerce.product_research import ResearchCandidate, build_research_candidates


def _dry_run_context() -> SidecarContext:
    return SidecarContext(workspace_id="test-workspace", run_id="run-1", dry_run=True)


def _live_context() -> SidecarContext:
    return SidecarContext(workspace_id="test-workspace", run_id="run-1", dry_run=False)


def _opportunity_candidate(candidate_id: str = "c1") -> OpportunityCandidate:
    return OpportunityCandidate(
        candidate_id=candidate_id, workspace_id="test-workspace", query="widget", product_name="Widget",
        category_name="Home", evidence_signal_ids=(), evidence_titles=(), source_urls=(),
        source_count=0, source_local_score=0.0, recency_score=0.0, evidence_strength="weak",
        confidence_level="low", assumptions=(), unknowns=(), cannot_claim=(),
        recommended_next_action="gather_more_evidence",
    )


# --- discover() Protocol-shaped path -----------------------------------------


@pytest.mark.asyncio
async def test_discover_returns_normalized_mappings_with_full_lineage():
    signals = await adapter.discover("mini thermal printer", context=_dry_run_context())
    assert len(signals) >= 1
    for record in signals:
        assert record["candidate_id"]
        assert record["query"] == "mini thermal printer"
        assert record["source_method"] == "sanitized_fixture_parser"
        assert record["confidence"] == "fixture"
        assert record["limitations"]
        assert record["request_kind"] == adapter.DEFAULT_REQUEST_KIND
        assert record["readiness_state"] == "dry_run_ready"


@pytest.mark.asyncio
async def test_discover_shopping_request_kind_preserves_lineage():
    signals = await adapter.discover(
        "portable espresso maker", context=_dry_run_context(), request_kind="serp_google_shopping_snapshot"
    )
    assert signals
    assert all(record["request_kind"] == "serp_google_shopping_snapshot" for record in signals)


@pytest.mark.asyncio
async def test_discover_is_deterministic_across_calls():
    first = await adapter.discover("repeatable query", context=_dry_run_context())
    second = await adapter.discover("repeatable query", context=_dry_run_context())
    assert first == second


@pytest.mark.asyncio
async def test_discover_live_mode_fails_closed_with_single_blocked_record():
    signals = await adapter.discover("widget", context=_live_context())
    assert len(signals) == 1
    assert signals[0]["status"] == "blocked_live_mode"
    assert signals[0]["readiness_state"] == "blocked"
    assert "live_mode_requested" in signals[0]["blockers"]
    assert signals[0]["report"] == {}


@pytest.mark.asyncio
async def test_discover_never_exposes_raw_payload_or_html():
    signals = await adapter.discover("widget", context=_dry_run_context())
    blob = str(signals)
    assert "<html" not in blob.lower()
    assert "raw_payload" not in blob
    assert "raw_html" not in blob
    for record in signals:
        assert "raw_payload" not in record
        assert "raw_html" not in record
        assert "api_key" not in record
        assert "authorization" not in record


# --- ProductResearchProvider structural conformance --------------------------


@pytest.mark.asyncio
async def test_research_adapter_class_matches_free_function_behavior():
    instance = adapter.DataForSEOResearchAdapter()
    via_class = await instance.discover("widget", context=_dry_run_context())
    via_function = await adapter.discover("widget", context=_dry_run_context())
    assert via_class == via_function
    class_health, function_health = instance.health(), adapter.health()
    assert class_health.name == function_health.name
    assert class_health.configured == function_health.configured
    assert class_health.reachable == function_health.reachable
    assert class_health.capabilities == function_health.capabilities


def test_research_adapter_class_has_no_registry_state():
    instance = adapter.DataForSEOResearchAdapter()
    assert instance.name == adapter.SOURCE
    # No registry, no persisted state: a fresh instance is fully equivalent.
    assert adapter.DataForSEOResearchAdapter().name == instance.name


# --- attaching discover() output to ResearchCandidate ------------------------


@pytest.mark.asyncio
async def test_discover_signals_attach_to_research_candidate_additional_evidence():
    signals = await adapter.discover("widget", context=_dry_run_context())
    packet = adapter.signals_to_additional_evidence(signals)
    candidate = ResearchCandidate(
        candidate_id="c1",
        opportunity_candidate=_opportunity_candidate("c1"),
        additional_evidence=packet,
    )
    assert candidate.additional_evidence["dataforseo_signals"]
    assert candidate.additional_evidence["dataforseo_signals"][0]["query"] == "widget"
    assert candidate.to_dict()["additional_evidence_keys"] == ["dataforseo_signals"]


@pytest.mark.asyncio
async def test_both_evidence_shapes_can_coexist_on_one_candidate():
    """to_additional_evidence (aggregate) and signals_to_additional_evidence
    (per-signal) use distinct keys and do not collide."""
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context())
    signals = await adapter.discover("widget", context=_dry_run_context())
    packet = {**adapter.to_additional_evidence(evidence), **adapter.signals_to_additional_evidence(signals)}
    candidate = ResearchCandidate(
        candidate_id="c1", opportunity_candidate=_opportunity_candidate("c1"), additional_evidence=packet,
    )
    assert set(candidate.additional_evidence.keys()) == {"dataforseo", "dataforseo_signals"}


# --- default Commerce MVP behavior is unchanged without this adapter --------


def test_build_research_candidates_default_behavior_unchanged_without_dataforseo():
    candidates = build_research_candidates([_opportunity_candidate("c1"), _opportunity_candidate("c2")])
    assert len(candidates) == 2
    for candidate in candidates:
        assert candidate.additional_evidence == {}
        assert candidate.to_dict()["additional_evidence_keys"] == []
        assert candidate.opportunity_score is None
        assert candidate.supplier_evidence is None
        assert candidate.competition_evidence is None
