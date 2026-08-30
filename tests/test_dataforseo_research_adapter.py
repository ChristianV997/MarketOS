"""Tests for backend.adapters.research.dataforseo -- the thin runtime
bridge from the offline DataForSEO adapter into the Product Research seam.

Every test stays fixture-only and offline: no network, no SDK, no
credential, no live transport. See docs/DATAFORSEO_RUNTIME_ADAPTER.md.
"""
from __future__ import annotations

import copy

import pytest

from backend.adapters.research import dataforseo as adapter
from backend.contracts.adapters import AdapterHealth, SidecarContext


def _dry_run_context() -> SidecarContext:
    return SidecarContext(workspace_id="test-workspace", run_id="run-1", dry_run=True)


def _live_context() -> SidecarContext:
    return SidecarContext(workspace_id="test-workspace", run_id="run-1", dry_run=False)


# --- fixture parsing / normalized signal counts -----------------------------


def test_fetch_search_evidence_parses_default_fixture():
    evidence = adapter.fetch_search_evidence("mini thermal printer", context=_dry_run_context())
    assert evidence.source == adapter.SOURCE
    assert evidence.query == "mini thermal printer"
    assert evidence.status == "dry_run_ready"
    assert evidence.readiness_state == "dry_run_ready"
    assert evidence.search_signal_count >= 1


def test_fetch_search_evidence_shopping_request_kind_produces_shopping_signals():
    evidence = adapter.fetch_search_evidence(
        "portable espresso maker", context=_dry_run_context(), request_kind="serp_google_shopping_snapshot"
    )
    assert evidence.request_kind == "serp_google_shopping_snapshot"
    assert evidence.shopping_signal_count >= 1


def test_fetch_search_evidence_competitor_request_kind_produces_competitor_signals():
    evidence = adapter.fetch_search_evidence(
        "jade roller", context=_dry_run_context(), request_kind="competitor_serp_snapshot"
    )
    assert evidence.competitor_signal_count >= 1


def test_unsupported_request_kind_falls_back_to_default():
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context(), request_kind="not_a_real_kind")
    assert evidence.request_kind == adapter.DEFAULT_REQUEST_KIND


# --- approval / terms / privacy / credential blockers -----------------------


def test_dry_run_evidence_reports_approval_and_terms_privacy_blockers():
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context())
    assert "approval_missing" in evidence.blockers
    assert "terms_review_missing" in evidence.blockers
    assert "privacy_review_missing" in evidence.blockers


def test_missing_credential_reference_is_reported(monkeypatch):
    import evaluation.commerce.dataforseo_adapter as offline_module
    from evaluation.companyos.credential_registry import CredentialRegistryReport

    original_builder = offline_module.build_credential_registry

    def _empty_credential_registry(*, generated_at: str = "offline-deterministic", seed=None):
        real = original_builder(generated_at=generated_at, seed=seed)
        return CredentialRegistryReport(**{**real.__dict__, "credentials": ()})

    monkeypatch.setattr(offline_module, "build_credential_registry", _empty_credential_registry)
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context())
    assert "credential_missing" in evidence.blockers


def test_budget_cap_is_present_in_underlying_report():
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context())
    cost = evidence.report["cost_estimate"]
    assert cost["monthly_budget_cap"] > 0
    assert cost["stop_conditions"]


# --- output contract invariants --------------------------------------------


def test_output_contract_forbids_raw_payload_and_raw_html():
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context())
    contract = evidence.report["output_contract"]
    assert contract["raw_payload_allowed"] is False
    assert contract["raw_html_allowed"] is False


# --- live-mode fail-closed behavior -----------------------------------------


def test_live_context_never_reaches_offline_builder():
    evidence = adapter.fetch_search_evidence("widget", context=_live_context())
    assert evidence.status == "blocked_live_mode"
    assert evidence.readiness_state == "blocked"
    assert "live_mode_requested" in evidence.blockers
    assert evidence.report == {}
    assert evidence.search_signal_count == 0


def test_live_context_names_every_missing_prerequisite():
    evidence = adapter.fetch_search_evidence("widget", context=_live_context())
    for prerequisite in adapter._LIVE_PREREQUISITES:
        assert prerequisite in evidence.blockers


# --- deterministic output ----------------------------------------------------


def test_fetch_search_evidence_is_deterministic(monkeypatch):
    monkeypatch.setattr(adapter.time, "time", lambda: 1000.0)
    first = adapter.fetch_search_evidence("repeatable query", context=_dry_run_context()).to_dict()
    second = adapter.fetch_search_evidence("repeatable query", context=_dry_run_context()).to_dict()
    assert first == second


# --- safety: no network, no SDK, no raw payload persistence -----------------


def test_safety_summary_reports_offline_read_only_fail_closed():
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context())
    safety = evidence.report["safety_summary"]
    assert safety["read_only"] is True
    assert safety["network_calls"] is False
    assert safety["sdk_used"] is False
    assert safety["live_request_created"] is False
    assert safety["raw_payload_stored"] is False
    assert safety["raw_html_stored"] is False
    assert safety["credentials_loaded"] is False
    assert safety["fail_closed"] is True


def test_no_raw_payload_or_html_leaks_into_normalized_signals():
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context())
    blob = str(evidence.report)
    assert "<html" not in blob.lower()
    assert "raw_payload" not in blob.lower() or "raw_payload_stored" in blob


def test_module_performs_no_network_import():
    import ast
    import inspect

    source = inspect.getsource(adapter)
    tree = ast.parse(source)
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module.split(".")[0])
    forbidden = {"requests", "httpx", "urllib3", "socket", "aiohttp"}
    assert imported_names.isdisjoint(forbidden)


# --- discover_search_queries -------------------------------------------------


def test_discover_search_queries_returns_cleaned_input_only():
    result = adapter.discover_search_queries("  mini   thermal   printer  ", context=_dry_run_context())
    assert result == ["mini thermal printer"]


def test_discover_search_queries_empty_input_returns_empty_list():
    assert adapter.discover_search_queries("   ", context=_dry_run_context()) == []


# --- ResearchCandidate.additional_evidence integration point ----------------


def test_to_additional_evidence_shapes_for_research_candidate_extension_point():
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context())
    packet = adapter.to_additional_evidence(evidence)
    assert set(packet.keys()) == {"dataforseo"}
    assert packet["dataforseo"]["source"] == adapter.SOURCE


def test_additional_evidence_attaches_without_mutating_research_candidate_shape():
    from backend.mvp_commerce.opportunity import OpportunityCandidate
    from backend.mvp_commerce.product_research import ResearchCandidate

    candidate = OpportunityCandidate(
        candidate_id="c1", workspace_id="test-workspace", query="widget", product_name="Widget",
        category_name="Home", evidence_signal_ids=(), evidence_titles=(), source_urls=(),
        source_count=0, source_local_score=0.0, recency_score=0.0, evidence_strength="weak",
        confidence_level="low", assumptions=(), unknowns=(), cannot_claim=(),
        recommended_next_action="gather_more_evidence",
    )
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context())
    research_candidate = ResearchCandidate(
        candidate_id="c1",
        opportunity_candidate=candidate,
        additional_evidence=adapter.to_additional_evidence(evidence),
    )
    assert research_candidate.additional_evidence["dataforseo"]["source"] == adapter.SOURCE
    assert research_candidate.to_dict()["additional_evidence_keys"] == ["dataforseo"]


# --- health() -----------------------------------------------------------------


def test_health_reports_unreachable_offline_adapter():
    result = adapter.health()
    assert isinstance(result, AdapterHealth)
    assert result.name == adapter.SOURCE
    assert result.configured is True
    assert result.reachable is False
    assert "fixture_only" in result.capabilities
    assert "dry_run_only" in result.capabilities
