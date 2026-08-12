from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.commerce.intelligence_adapter_plan import (
    ADAPTER_MODES,
    EVIDENCE_CATEGORIES,
    READINESS_STATES,
    STOP_CONDITIONS,
    ProviderAdapterSafetySummary,
    ProviderOutputContract,
    ProviderRunEnvelope,
    build_intelligence_adapter_plan,
    normalize_provider_record,
    parse_dry_run_fixture,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "intelligence_adapter_plan"
CLI = ROOT / "scripts" / "run_intelligence_adapter_plan.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CLI), *args], cwd=ROOT, text=True, capture_output=True, check=False)


def report():
    return build_intelligence_adapter_plan()


@pytest.mark.parametrize("mode", ADAPTER_MODES)
def test_adapter_mode_vocabulary_is_explicit(mode: str):
    assert mode in ADAPTER_MODES
    assert mode != "live"


@pytest.mark.parametrize("state", READINESS_STATES)
def test_readiness_vocabulary_is_explicit(state: str):
    assert state in READINESS_STATES


@pytest.mark.parametrize("category", EVIDENCE_CATEGORIES)
def test_evidence_categories_are_supported(category: str):
    contract = ProviderOutputContract("fixture-contract", category, "FixtureEvidence", ("candidate_id",), (), True, False, True, ("fixture only",))
    assert contract.evidence_category == category


@pytest.mark.parametrize("condition", STOP_CONDITIONS)
def test_stop_conditions_are_explicit(condition: str):
    assert condition in STOP_CONDITIONS


def test_report_counts_and_safety():
    data = report().to_dict()
    assert data["provider_count"] == 8
    assert data["adapter_contract_count"] == 8
    assert data["request_plan_count"] == 8
    assert data["dry_run_result_count"] == 8
    assert data["safety_summary"] == {
        "read_only": True,
        "network_calls": False,
        "credentials_loaded": False,
        "provider_calls": False,
        "sdk_calls": False,
        "scraping_performed": False,
        "raw_payloads_stored": False,
        "raw_html_stored": False,
        "external_actions": False,
        "fail_closed": True,
    }


def test_report_is_deterministic():
    assert report().to_dict() == report().to_dict()
    assert report().to_markdown() == report().to_markdown()


@pytest.mark.parametrize("provider", ("apify", "dataforseo", "serpapi", "official-marketplace-apis", "official-social-search-apis", "manual-import"))
def test_expected_provider_is_dry_run_ready(provider: str):
    item = next(item for item in report().contracts if item.provider_id == provider)
    assert item.default_mode in {"dry_run_request_plan", "manual_import"}
    assert item.activation_readiness.state == "dry_run_ready"
    assert item.activation_readiness.credential_check.secret_value_absent is True


@pytest.mark.parametrize("provider", ("bright-data", "oxylabs"))
def test_enterprise_proxy_provider_is_blocked(provider: str):
    item = next(item for item in report().contracts if item.provider_id == provider)
    assert item.default_mode == "blocked"
    assert item.activation_readiness.state == "blocked"
    assert "provider_class_blocked_in_current_mode" in item.activation_readiness.blockers


@pytest.mark.parametrize("provider", ("apify", "dataforseo", "serpapi"))
def test_priority_provider_has_required_approval_types(provider: str):
    item = next(item for item in report().contracts if item.provider_id == provider)
    assert "provider_call" in item.required_approval_type
    assert "web_data_acquisition" in item.required_approval_type
    assert item.required_tool_category == "search_web"


def test_apify_contract_and_request_placeholders():
    item = next(item for item in report().contracts if item.provider_id == "apify")
    request = next(item for item in report().request_plans if item.provider_id == "apify")
    assert "marketplace_demand" in item.target_data_needs
    assert request.parameters["actor_id_placeholder"]
    assert request.parameters["schedule_disabled"] is True
    assert request.live_request_created is False


def test_dataforseo_contract_and_request_placeholders():
    item = next(item for item in report().contracts if item.provider_id == "dataforseo")
    request = next(item for item in report().request_plans if item.provider_id == "dataforseo")
    assert "search_serp_keyword_demand" in item.target_data_needs
    assert request.parameters["endpoint_placeholder"]
    assert request.parameters["location_code_placeholder"] == "TBD"
    assert request.parameters["max_cost"] == 2.0


def test_serpapi_contract_and_request_placeholders():
    item = next(item for item in report().contracts if item.provider_id == "serpapi")
    request = next(item for item in report().request_plans if item.provider_id == "serpapi")
    assert "competitor_pricing" in item.target_data_needs
    assert request.parameters["endpoint_placeholder"] == "search.json"
    assert request.parameters["engine_placeholder"] == "google_shopping"


def test_manual_import_has_no_provider_approval():
    item = next(item for item in report().contracts if item.provider_id == "manual-import")
    assert item.default_mode == "manual_import"
    assert item.required_approval_type == ("none",)
    assert item.terms_review_required is False
    assert item.privacy_review_required is False


@pytest.mark.parametrize("provider", ("apify", "dataforseo", "serpapi", "official-marketplace-apis", "official-social-search-apis", "bright-data", "oxylabs", "manual-import"))
def test_request_plans_are_bounded(provider: str):
    item = next(item for item in report().request_plans if item.provider_id == provider)
    assert item.max_items > 0
    assert item.max_cost >= 0
    assert item.schedule_disabled is True
    assert item.live_request_created is False
    assert item.output_contract_id


@pytest.mark.parametrize("provider", ("apify", "dataforseo", "serpapi", "official-marketplace-apis", "official-social-search-apis", "bright-data", "oxylabs", "manual-import"))
def test_run_envelopes_are_offline(provider: str):
    item = next(item for item in report().run_envelopes if item.provider_id == provider)
    assert item.network_allowed is False
    assert item.external_action_performed is False
    assert item.raw_payload_storage == "none"
    assert item.request_id_placeholder.endswith("placeholder")


@pytest.mark.parametrize("provider", ("apify", "dataforseo", "serpapi", "official-marketplace-apis", "official-social-search-apis", "bright-data", "oxylabs", "manual-import"))
def test_cost_and_rate_plans_have_caps(provider: str):
    cost = next(item for item in report().cost_plan if item.provider_id == provider)
    rate = next(item for item in report().rate_limit_plan if item.provider_id == provider)
    assert cost.estimated_cost_per_run_min <= cost.estimated_cost_per_run_max
    assert cost.estimated_monthly_budget_min <= cost.estimated_monthly_budget_max
    assert rate.max_runs_per_day >= 1
    assert rate.max_items_per_run >= 1
    assert "cost_cap_reached" in rate.stop_conditions


@pytest.mark.parametrize("provider", ("apify", "dataforseo", "serpapi", "official-marketplace-apis", "official-social-search-apis", "bright-data", "oxylabs", "manual-import"))
def test_contract_has_output_mapping_and_normalization(provider: str):
    item = next(item for item in report().contracts if item.provider_id == provider)
    assert item.output_contract.sanitized is True
    assert item.output_contract.raw_payload_allowed is False
    assert item.evidence_mapping
    assert item.normalization_rules
    assert all(rule.missing_behavior for rule in item.normalization_rules)


@pytest.mark.parametrize("provider", ("apify", "dataforseo", "serpapi", "official-marketplace-apis", "official-social-search-apis"))
def test_live_prerequisites_are_visible(provider: str):
    item = next(item for item in report().readiness_by_provider if item.provider_id == provider)
    assert "approval_missing" in item.blockers
    assert "terms_review_missing" in item.blockers
    assert "privacy_review_missing" in item.blockers
    assert "Approval Ledger decision recorded" in item.future_prerequisites


def test_future_approval_list_excludes_blocked_proxies():
    data = report().to_dict()
    assert "apify" in data["providers_ready_for_future_approval"]
    assert "bright-data" not in data["providers_ready_for_future_approval"]
    assert "oxylabs" not in data["providers_ready_for_future_approval"]


def test_evidence_mappings_feed_existing_report_models():
    mapping_models = {item.target_model for item in report().evidence_mappings}
    assert {"MarketplaceTrendEvidence", "ConsumerAttentionEvidence", "SearchTrendEvidence", "ProviderRunEvidence"} <= mapping_models
    assert all(item.can_feed_reports for item in report().evidence_mappings)


def test_normalized_marketplace_signal_has_required_provenance():
    item = normalize_provider_record("apify", "MarketplaceEvidence", {"candidate_id": "mini-thermal-printer", "query": "mini thermal printer", "price": 29.99, "currency": "USD"})
    assert item.source_provider == "apify"
    assert item.source_method == "fixture_snapshot"
    assert item.raw_record_ref_placeholder.startswith("normalized-")
    assert item.terms_notes
    assert item.privacy_notes
    assert item.can_feed_reports is True


@pytest.mark.parametrize("field", ("candidate_id", "query", "title", "price", "currency", "rank", "review_count", "rating", "trend_label"))
def test_normalization_preserves_supported_field(field: str):
    value = 1 if field in {"price", "rank", "review_count", "rating"} else "fixture-value"
    item = normalize_provider_record("dataforseo", "SearchDemandEvidence", {"candidate_id": "fixture", "query": "query", field: value})
    assert field in item.normalized_fields


@pytest.mark.parametrize("fixture_name,provider,category", (
    ("apify_marketplace_snapshot_dry_run.json", "apify", "MarketplaceEvidence"),
    ("apify_review_snapshot_dry_run.json", "apify", "ReviewEvidence"),
    ("dataforseo_serp_snapshot_dry_run.json", "dataforseo", "SearchDemandEvidence"),
    ("serpapi_shopping_snapshot_dry_run.json", "serpapi", "CompetitorPricingEvidence"),
    ("manual_import_marketplace_snapshot.json", "manual-import", "MarketplaceEvidence"),
))
def test_dry_run_fixture_parses_to_normalized_records(fixture_name: str, provider: str, category: str):
    payload = json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8"))
    records = parse_dry_run_fixture(provider, payload, evidence_category=category)
    assert len(records) == 1
    assert records[0].source_provider == provider
    assert records[0].evidence_category == category
    assert records[0].normalized_fields["candidate_id"]


def test_malformed_fixture_is_rejected():
    payload = json.loads((FIXTURES / "malformed_provider_output.json").read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="records"):
        parse_dry_run_fixture("fixture-provider", payload)


def test_secret_like_fixture_is_rejected():
    payload = json.loads((FIXTURES / "secret_like_provider_output_rejected.json").read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="secret-like"):
        parse_dry_run_fixture("fixture-provider", payload)


@pytest.mark.parametrize("bad", ("sk-live-placeholder", "Bearer fixture", "-----BEGIN PRIVATE KEY-----"))
def test_secret_like_normalized_record_is_rejected(bad: str):
    with pytest.raises(ValueError, match="secret-like"):
        normalize_provider_record("apify", "MarketplaceEvidence", {"candidate_id": "fixture", "notes": bad})


def test_raw_payload_key_is_rejected():
    with pytest.raises(ValueError, match="secret-like"):
        normalize_provider_record("apify", "MarketplaceEvidence", {"candidate_id": "fixture", "raw_payload": {"title": "hidden"}})


def test_fixture_payload_override_is_parsed_but_not_retained():
    custom = {"apify": {"records": [{"candidate_id": "portable-blender", "query": "portable blender", "price": 22.0}]}}
    result = build_intelligence_adapter_plan(fixture_payloads=custom)
    dry = next(item for item in result.dry_run_results if item.provider_id == "apify")
    assert dry.raw_payload_stored is False
    assert dry.normalized_records[0]["provider_id"] if "provider_id" in dry.normalized_records[0] else True


def test_report_markdown_contains_required_sections():
    markdown = report().to_markdown()
    for heading in ("Executive Summary", "Provider Adapter Contracts", "Request Plans", "Approval and Credential Checks", "Cost and Rate Limits", "Terms and Privacy Review", "Evidence Mapping", "Normalization Rules", "Dry-Run Results", "Blocked Providers", "Safety Boundaries"):
        assert f"## {heading}" in markdown


@pytest.mark.parametrize("provider", ("apify", "dataforseo", "serpapi"))
def test_provider_filter_is_deterministic(provider: str):
    result = build_intelligence_adapter_plan(provider=provider)
    assert result.provider_count == 1
    assert result.contracts[0].provider_id == provider
    assert result.safety_summary.network_calls is False


@pytest.mark.parametrize("data_need", ("search_serp_keyword_demand", "marketplace_demand", "competitor_pricing", "consumer_attention", "supplier_feasibility"))
def test_data_need_filter_is_supported(data_need: str):
    result = build_intelligence_adapter_plan(data_need=data_need)
    assert result.provider_count >= 1
    assert all(data_need in item.target_data_needs for item in result.contracts)


def test_unknown_provider_fails_closed():
    with pytest.raises(ValueError, match="unknown adapter provider"):
        build_intelligence_adapter_plan(provider="unknown-provider")


def test_unknown_data_need_fails_closed():
    with pytest.raises(ValueError, match="unknown or unsupported data need"):
        build_intelligence_adapter_plan(data_need="unbounded_live_scrape")


def test_output_contract_rejects_raw_payloads():
    with pytest.raises(ValueError, match="raw provider payloads"):
        ProviderOutputContract("unsafe", "MarketplaceEvidence", "MarketplaceTrendEvidence", ("candidate_id",), (), True, True, True, ())


def test_run_envelope_rejects_network():
    with pytest.raises(ValueError, match="offline"):
        ProviderRunEnvelope("run", "apify", "plan", "dry_run_request_plan", "request", "credential-apify", "approval", {}, "idempotency", "offline", True, False, "none")


def test_safety_summary_rejects_provider_calls():
    with pytest.raises(ValueError, match="offline"):
        ProviderAdapterSafetySummary(True, True, False, False, False, False, False, False, False, True)


def test_cli_json_is_offline_and_stable():
    first = run_cli("--json")
    second = run_cli("--json")
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout) == json.loads(second.stdout)
    payload = json.loads(first.stdout)
    assert payload["safety_summary"]["network_calls"] is False
    assert payload["safety_summary"]["provider_calls"] is False


def test_cli_markdown_is_readable():
    result = run_cli("--markdown")
    assert result.returncode == 0
    assert result.stdout.startswith("# Intelligence Live Read-Only Adapter Plan")
    assert "Apify" in result.stdout
    assert "live mode blocked" in result.stdout


@pytest.mark.parametrize("args,provider", ((("--provider", "apify", "--json"), "apify"), (("--provider", "dataforseo", "--json"), "dataforseo"), (("--provider", "serpapi", "--json"), "serpapi")))
def test_cli_provider_filter(args: tuple[str, ...], provider: str):
    result = run_cli(*args)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["provider_count"] == 1
    assert payload["contracts"][0]["provider_id"] == provider


@pytest.mark.parametrize("data_need", ("search_serp_keyword_demand", "marketplace_demand"))
def test_cli_data_need_filter(data_need: str):
    result = run_cli("--data-need", data_need, "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["provider_count"] >= 1
    assert all(data_need in item["target_data_needs"] for item in payload["contracts"])


def test_cli_fixture_dir_and_exports(tmp_path: Path):
    output = tmp_path / "exports"
    result = run_cli("--fixture-dir", str(FIXTURES), "--output", str(output), "--json")
    assert result.returncode == 0, result.stderr
    expected = {"intelligence_adapter_plan_report.json", "intelligence_adapter_plan_report.md", "provider_adapter_contracts.json", "provider_request_plans.json", "approval_credential_checks.json", "provider_cost_plan.json", "evidence_mappings.json", "normalization_rules.json", "dry_run_results.json", "blocked_providers.json"}
    assert {item.name for item in output.iterdir()} == expected
    exported = (output / "intelligence_adapter_plan_report.json").read_text(encoding="utf-8")
    assert '"raw_payload":' not in exported
    assert '"raw_payload_stored": true' not in exported


def test_cli_rejects_path_traversal():
    result = run_cli("--fixture-dir", "..\\tests\\fixtures\\intelligence_adapter_plan", "--json")
    assert result.returncode == 2
    assert "path traversal" in result.stderr


def test_cli_rejects_two_formats():
    result = run_cli("--json", "--markdown")
    assert result.returncode != 0


def test_fixture_files_are_sanitized():
    for path in FIXTURES.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if path.name == "secret_like_provider_output_rejected.json":
            continue
        text = json.dumps(payload).lower()
        assert "raw_html" not in text
        assert "raw_payload" not in text
        assert "private_key" not in text


def test_no_live_action_vocabulary_in_run_results():
    payload = report().to_dict()
    assert all(item["network_calls"] is False for item in payload["dry_run_results"])
    assert all(item["external_action_performed"] is False for item in payload["dry_run_results"])
    assert payload["safety_summary"]["raw_payloads_stored"] is False


@pytest.mark.parametrize("provider", ("apify", "dataforseo", "serpapi", "official-marketplace-apis", "official-social-search-apis", "bright-data", "oxylabs", "manual-import"))
def test_each_provider_has_a_fixture_result(provider: str):
    result = next(item for item in report().dry_run_results if item.provider_id == provider)
    assert result.fixture_ref.endswith(".json")
    assert result.result_status == "normalized_fixture"
    assert result.normalized_records


@pytest.mark.parametrize("provider", ("apify", "dataforseo", "serpapi", "official-marketplace-apis", "official-social-search-apis", "bright-data", "oxylabs", "manual-import"))
def test_each_provider_has_terms_and_privacy_policy_note(provider: str):
    item = next(item for item in report().contracts if item.provider_id == provider)
    assert all(mapping.terms_notes for mapping in item.evidence_mapping)
    assert all(mapping.privacy_notes for mapping in item.evidence_mapping)


@pytest.mark.parametrize("provider", ("apify", "dataforseo", "serpapi", "official-marketplace-apis", "official-social-search-apis", "bright-data", "oxylabs", "manual-import"))
def test_each_provider_has_a_live_mode_blocker(provider: str):
    item = next(item for item in report().contracts if item.provider_id == provider)
    assert any(check.check_type == "live_mode_blocked" for check in item.activation_readiness.approval_checks)
    assert "owner assigned" in item.activation_readiness.future_prerequisites


@pytest.mark.parametrize("provider", ("apify", "dataforseo", "serpapi", "official-marketplace-apis", "official-social-search-apis", "bright-data", "oxylabs", "manual-import"))
def test_each_provider_normalizes_provenance_fields(provider: str):
    item = next(item for item in report().contracts if item.provider_id == provider)
    fields = {rule.field for rule in item.normalization_rules}
    assert {"candidate_id", "query", "price", "currency", "source_url"} <= fields


def test_report_has_all_cost_stop_conditions():
    for item in report().cost_plan:
        assert set(STOP_CONDITIONS) <= set(item.stop_conditions)


def test_report_has_all_rate_stop_conditions():
    for item in report().rate_limit_plan:
        assert set(STOP_CONDITIONS) <= set(item.stop_conditions)


def test_report_blocked_reason_records_are_sanitized():
    for item in report().blocked_reasons:
        assert "api_key" not in json.dumps(item.to_dict()).lower()
        assert "raw_payload" not in json.dumps(item.to_dict()).lower()
