"""Tests for backend.adapters.research.serpapi -- the thin runtime bridge
from the existing generic Intelligence Adapter Plan
(evaluation.commerce.intelligence_adapter_plan) into the Product Research
seam, for the "serpapi" provider entry.

Every test stays fixture-only and offline: no network, no SDK, no
credential, no live transport. See docs/SERPAPI_RUNTIME_ADAPTER.md.
"""
from __future__ import annotations

import pytest

from backend.adapters.research import serpapi as adapter
from backend.contracts.adapters import AdapterHealth, SidecarContext


def _dry_run_context() -> SidecarContext:
    return SidecarContext(workspace_id="test-workspace", run_id="run-1", dry_run=True)


def _live_context() -> SidecarContext:
    return SidecarContext(workspace_id="test-workspace", run_id="run-1", dry_run=False)


# --- organic SERP request plan (primary, required) ------------------------------


def test_organic_search_snapshot_is_the_default_request_kind():
    assert adapter.DEFAULT_REQUEST_KIND == "organic_search_snapshot"
    evidence = adapter.fetch_search_evidence("neck massager", context=_dry_run_context())
    assert evidence.request_kind == "organic_search_snapshot"
    assert evidence.evidence_category == "SearchDemandEvidence"
    assert evidence.signal_count == 1


def test_organic_snapshot_substitutes_caller_query_into_fixture_record():
    evidence = adapter.fetch_search_evidence("portable espresso maker", context=_dry_run_context())
    record = evidence.report["records"][0]
    assert record["normalized_fields"]["query"] == "portable espresso maker"
    assert record["normalized_fields"]["candidate_id"] == "neck-massager"
    assert "rank" in record["normalized_fields"]
    assert "trend_label" in record["normalized_fields"]


def test_organic_request_plan_is_bounded():
    """max_items > 0, max_cost bounded, scheduling disabled, no live
    request created -- enforced by the reused generic module's own
    ProviderRequestPlan.__post_init__, not re-implemented here."""
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context())
    request_plan = evidence.report["request_plan"]
    assert request_plan["max_items"] > 0
    assert request_plan["max_cost"] >= 0
    assert request_plan["schedule_disabled"] is True
    assert request_plan["live_request_created"] is False


# --- shopping snapshot (optional secondary) --------------------------------------


def test_shopping_snapshot_is_selectable_as_secondary_request_kind():
    evidence = adapter.fetch_search_evidence("neck massager", context=_dry_run_context(), request_kind="shopping_snapshot")
    assert evidence.request_kind == "shopping_snapshot"
    assert evidence.evidence_category == "CompetitorPricingEvidence"
    record = evidence.report["records"][0]["normalized_fields"]
    assert record["price"] == 35.0
    assert record["currency"] == "USD"


def test_unsupported_request_kind_falls_back_to_organic_default():
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context(), request_kind="not_a_real_kind")
    assert evidence.request_kind == "organic_search_snapshot"


# --- request-plan / contract reuse (via the generic offline module) -------------


def test_request_plan_and_contract_are_reused_from_generic_offline_module():
    """No duplicate provider spec/contract logic exists here -- the
    request plan and contract are the exact objects the generic
    evaluation.commerce.intelligence_adapter_plan module already builds
    and already tests for "serpapi"."""
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context())
    request_plan = evidence.report["request_plan"]
    assert request_plan["provider_id"] == "serpapi"
    assert request_plan["parameters"]["engine_placeholder"] == "google_shopping"
    contract = evidence.report["contract"]
    assert contract["provider_id"] == "serpapi"


def test_caller_supplied_fixture_payload_is_used_instead_of_bundled_default():
    payload = {
        "provider": "serpapi",
        "records": [{"candidate_id": "custom", "query": "custom query", "price": 9.99, "currency": "USD"}],
        "fixture_mode": True,
    }
    evidence = adapter.fetch_search_evidence("ignored", context=_dry_run_context(), payload=payload)
    assert evidence.signal_count == 1
    assert evidence.report["records"][0]["normalized_fields"]["candidate_id"] == "custom"


# --- output-contract validation --------------------------------------------------


def test_output_contract_forbids_raw_payload_and_is_sanitized():
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context())
    output_contract = evidence.report["contract"]["output_contract"]
    assert output_contract["raw_payload_allowed"] is False
    assert output_contract["sanitized"] is True
    assert output_contract["required_fields"]


def test_normalization_rules_and_evidence_mapping_are_present():
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context())
    contract = evidence.report["contract"]
    assert contract["evidence_mapping"]
    assert contract["normalization_rules"]
    assert all(rule["missing_behavior"] for rule in contract["normalization_rules"])


# --- provider registration --------------------------------------------------------


def test_provider_registered_check_reflects_real_provider_registry():
    """serpapi is a real entry in evaluation.companyos.provider_registry
    today -- this must reflect that truthfully, not assume it."""
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context())
    assert evidence.provider_registered is True
    assert "provider_not_registered" not in evidence.blockers


def test_missing_provider_registration_blocks_and_is_named(monkeypatch):
    from evaluation.companyos.provider_registry import ProviderRegistryReport

    real_registry = adapter.build_provider_registry()

    def _empty_provider_registry(*args, **kwargs):
        return ProviderRegistryReport(**{**real_registry.__dict__, "providers": ()})

    monkeypatch.setattr(adapter, "build_provider_registry", _empty_provider_registry)
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context())
    assert evidence.provider_registered is False
    assert "provider_not_registered" in evidence.blockers
    assert evidence.readiness_state == "blocked"
    assert evidence.status == "blocked"


# --- approval / credential / terms-privacy blockers -----------------------------


def test_dry_run_evidence_reports_approval_and_terms_privacy_blockers():
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context())
    assert "approval_missing" in evidence.blockers
    assert "terms_review_missing" in evidence.blockers
    assert "privacy_review_missing" in evidence.blockers


def test_credential_reference_check_is_metadata_only_no_secret_read():
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context())
    credential_check = evidence.report["contract"]["activation_readiness"]["credential_check"]
    assert credential_check["secret_value_absent"] is True
    assert credential_check["credential_reference_id"] == "credential-serpapi"


# --- budget/rate/retry caps --------------------------------------------------------


def test_budget_and_rate_caps_are_present_and_bounded():
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context())
    contract = evidence.report["contract"]
    assert contract["monthly_budget_cap"] > 0
    assert contract["estimated_cost_per_run_min"] <= contract["estimated_cost_per_run_max"]
    rate = contract["rate_limit_policy"]
    assert rate["max_runs_per_day"] >= 1
    assert rate["max_items_per_run"] >= 1
    assert "cost_cap_reached" in rate["stop_conditions"]


def test_retry_attempts_allowed_is_explicitly_zero():
    assert adapter.MAX_RETRY_ATTEMPTS == 0
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context())
    assert evidence.retry_attempts_allowed == 0
    assert evidence.to_dict()["retry_attempts_allowed"] == 0


# --- evidence-tier label (supplemental / non-live) ------------------------------


def test_evidence_tier_labels_dry_run_result_as_supplemental_non_live():
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context())
    assert evidence.evidence_tier == "supplemental_non_live"


def test_evidence_tier_labels_live_blocked_result_as_supplemental_non_live():
    evidence = adapter.fetch_search_evidence("widget", context=_live_context())
    assert evidence.evidence_tier == "supplemental_non_live"


@pytest.mark.asyncio
async def test_discover_signals_carry_evidence_category_and_readiness_state():
    signals = await adapter.discover("widget", context=_dry_run_context())
    assert signals
    assert all(record["evidence_category"] == "SearchDemandEvidence" for record in signals)
    assert all(record["readiness_state"] == "dry_run_ready" for record in signals)


# --- live flag fail-closed -------------------------------------------------------


def test_live_context_never_reaches_offline_plan():
    evidence = adapter.fetch_search_evidence("widget", context=_live_context())
    assert evidence.status == "blocked_live_mode"
    assert evidence.readiness_state == "blocked"
    assert "live_mode_requested" in evidence.blockers
    assert evidence.report == {}
    assert evidence.signal_count == 0


def test_live_context_names_every_missing_prerequisite():
    evidence = adapter.fetch_search_evidence("widget", context=_live_context())
    for prerequisite in adapter._LIVE_PREREQUISITES:
        assert prerequisite in evidence.blockers


@pytest.mark.asyncio
async def test_discover_live_mode_fails_closed_with_single_blocked_record():
    signals = await adapter.discover("widget", context=_live_context())
    assert len(signals) == 1
    assert signals[0]["status"] == "blocked_live_mode"
    assert signals[0]["report"] == {}


# --- malformed response / secret-like response / raw payload rejection ---------


def test_malformed_fixture_records_field_fails_closed_not_raises():
    payload = {"provider": "serpapi", "records": "not-a-list", "fixture_mode": True}
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context(), payload=payload)
    assert evidence.status == "error"
    assert evidence.readiness_state == "unavailable"
    assert evidence.signal_count == 0


def test_secret_like_fixture_payload_is_rejected_not_kept():
    payload = {
        "provider": "serpapi",
        "records": [{"candidate_id": "x", "query": "x"}],
        "api_key": "sk-test-abcdefghijklmnopqrstuvwxyz",
        "fixture_mode": True,
    }
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context(), payload=payload)
    assert evidence.status == "error"
    assert "sk-test" not in str(evidence.to_dict())


def test_unexpected_offline_module_failure_fails_closed_without_leaking(monkeypatch):
    def _raise(*args, **kwargs):
        raise ValueError("internal failure embedding credential-shaped-value: sk-test-abcdefghijklmnopqrstuvwxyz")

    monkeypatch.setattr(adapter, "build_intelligence_adapter_plan", _raise)
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context())
    assert evidence.status == "error"
    assert evidence.readiness_state == "unavailable"
    blob = str(evidence.to_dict())
    assert "sk-test" not in blob


def test_raw_payload_and_html_are_never_stored():
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context())
    contract = evidence.report["contract"]
    assert contract["output_contract"]["raw_payload_allowed"] is False
    blob = str(evidence.to_dict())
    assert "<html" not in blob.lower()


# --- deterministic normalization -------------------------------------------------


def test_fetch_search_evidence_is_deterministic(monkeypatch):
    monkeypatch.setattr(adapter.time, "time", lambda: 1000.0)
    first = adapter.fetch_search_evidence("repeatable query", context=_dry_run_context()).to_dict()
    second = adapter.fetch_search_evidence("repeatable query", context=_dry_run_context()).to_dict()
    assert first == second


@pytest.mark.asyncio
async def test_discover_is_deterministic_across_calls():
    first = await adapter.discover("repeatable query", context=_dry_run_context())
    second = await adapter.discover("repeatable query", context=_dry_run_context())
    assert first == second


# --- ProductResearchProvider structural conformance -----------------------------


@pytest.mark.asyncio
async def test_research_adapter_class_matches_free_function_behavior():
    instance = adapter.SerpApiResearchAdapter()
    via_class = await instance.discover("widget", context=_dry_run_context())
    via_function = await adapter.discover("widget", context=_dry_run_context())
    assert via_class == via_function
    class_health, function_health = instance.health(), adapter.health()
    assert class_health.name == function_health.name
    assert class_health.configured == function_health.configured
    assert class_health.reachable == function_health.reachable


# --- ResearchCandidate.additional_evidence integration point --------------------


def test_to_additional_evidence_shapes_for_research_candidate_extension_point():
    evidence = adapter.fetch_search_evidence("widget", context=_dry_run_context())
    packet = adapter.to_additional_evidence(evidence)
    assert set(packet.keys()) == {"serpapi"}
    assert packet["serpapi"]["source"] == adapter.SOURCE


@pytest.mark.asyncio
async def test_signals_to_additional_evidence_uses_distinct_key_from_dataforseo_shape():
    signals = await adapter.discover("widget", context=_dry_run_context())
    packet = adapter.signals_to_additional_evidence(signals)
    assert set(packet.keys()) == {"serpapi_signals"}


# --- health() --------------------------------------------------------------------


def test_health_reports_unreachable_offline_adapter():
    result = adapter.health()
    assert isinstance(result, AdapterHealth)
    assert result.name == adapter.SOURCE
    assert result.configured is True
    assert result.reachable is False
    assert "fixture_only" in result.capabilities
    assert "dry_run_only" in result.capabilities


# --- no network / no SDK / no environment reads ---------------------------------


def test_module_imports_no_network_or_sdk_modules():
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
    forbidden = {"requests", "httpx", "urllib3", "socket", "aiohttp", "boto3", "openai", "anthropic"}
    assert imported_names.isdisjoint(forbidden)
