from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.companyos.credential_registry import (
    CREDENTIAL_STATUSES,
    CREDENTIAL_TYPES,
    SECRET_MANAGERS,
    CredentialReference,
    ProviderHealthCheckStatus,
    ProviderPermissionScope,
    ProviderRateLimitPolicy,
    CredentialRotationPolicy,
    build_credential_registry,
)
from evaluation.companyos.intelligence_provider_plan import ACQUISITION_MODES, build_intelligence_provider_plan
from evaluation.companyos.provider_credential_report import build_provider_credential_report
from evaluation.companyos.provider_registry import ACTION_MODES, INTEGRATION_STAGES, PROVIDER_CATEGORIES, build_provider_registry
from evaluation.companyos.subscription_registry import PHASES, SUBSCRIPTION_STATUSES, build_subscription_registry

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "run_companyos_provider_registry.py"
FIXTURES = ROOT / "tests" / "fixtures" / "companyos_provider_registry"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CLI), *args], cwd=ROOT, capture_output=True, text=True, check=False)


def test_combined_report_is_deterministic_and_safe():
    first = build_provider_credential_report().to_dict()
    second = build_provider_credential_report().to_dict()
    assert first == second
    assert first["safety_summary"]["read_only"] is True
    assert first["safety_summary"]["network_calls"] is False
    assert first["safety_summary"]["secret_values_stored"] is False


@pytest.mark.parametrize("credential_type", CREDENTIAL_TYPES)
def test_credential_types_are_accepted(credential_type: str):
    report = build_credential_registry()
    reference = next(item for item in report.credentials if item.credential_type == credential_type) if any(item.credential_type == credential_type for item in report.credentials) else None
    if reference is not None:
        assert reference.credential_type == credential_type
    else:
        assert credential_type in CREDENTIAL_TYPES


@pytest.mark.parametrize("manager", SECRET_MANAGERS)
def test_secret_manager_vocabulary_is_seeded(manager: str):
    report = build_credential_registry()
    assert manager in {item.manager_id for item in report.secret_managers}
    assert all(item.reference_only for item in report.secret_managers)


@pytest.mark.parametrize("status", CREDENTIAL_STATUSES)
def test_credential_status_vocabulary_is_explicit(status: str):
    assert status in CREDENTIAL_STATUSES
    assert status in {item.status for item in build_credential_registry().credentials} or status in CREDENTIAL_STATUSES


def _reference() -> CredentialReference:
    provider = "fixture-provider"
    scope = ProviderPermissionScope("read", "read-only fixture metadata", "reference_only", True, "least privilege")
    health = ProviderHealthCheckStatus(provider, "not_checked", "never", "metadata_only", "unknown", (), ("no live check",))
    rotation = CredentialRotationPolicy("rotation-fixture", 90, True, True, True, "fixture-runbook")
    limit = ProviderRateLimitPolicy(provider, 10, 100, False, "bounded backoff", "offline")
    return CredentialReference("credential-fixture", provider, "account-placeholder", "local", "manual_reference", "marketos/fixture/reference", "api_key", (scope,), "intelligence", (), (), (), "approval-policy-provider-fixture", "medium", 20, 2, limit, rotation, health, "never", "never", "needed", "safe placeholder")


def test_credential_reference_serializes_without_secret_value():
    data = _reference().to_dict()
    assert data["secret_manager_ref"] == "marketos/fixture/reference"
    assert "actual_secret_value" not in json.dumps(data)
    assert data["health_status"]["check_mode"] == "metadata_only"


@pytest.mark.parametrize("bad", ("sk-12345678901234567890", "Bearer live-placeholder", "-----BEGIN PRIVATE KEY-----", "eyJabcdefghijklmnopqrst.abcdefghijklmnop"))
def test_credential_reference_rejects_obvious_secret_like_values(bad: str):
    with pytest.raises(ValueError):
        CredentialReference(**{**_reference().__dict__, "notes": bad})


@pytest.mark.parametrize("bad_key", ("actual_secret_value", "raw_api_key", "raw_oauth_token", "password", "private_key_material", "api_key"))
def test_seed_rejects_secret_like_keys(bad_key: str):
    with pytest.raises(ValueError, match="secret-like"):
        build_credential_registry(seed={bad_key: "fixture-value"})


def test_credential_seed_can_change_status_without_value():
    report = build_credential_registry(seed={"credentials": [{"credential_id": "credential-apify", "status": "configured_reference_only"}]})
    assert next(item for item in report.credentials if item.provider_id == "apify").status == "configured_reference_only"


def test_invalid_credential_status_degrades_to_safe_default():
    report = build_credential_registry(seed={"credentials": [{"credential_id": "credential-apify", "status": "active"}]})
    assert next(item for item in report.credentials if item.provider_id == "apify").status == "needed"


def test_credential_gaps_are_explicit():
    report = build_credential_registry()
    assert len(report.credential_gaps) == len(report.credentials)
    assert all("no secret-manager value" in item for item in report.credential_gaps)


def test_credential_approval_tool_and_model_links_are_present():
    report = build_credential_registry()
    assert len(report.approval_links) == len(report.credentials)
    assert len(report.tool_links) == len(report.credentials)
    assert len(report.model_route_links) == len(report.credentials)
    assert next(item for item in report.model_route_links if item.credential_id == "credential-litellm").route_ids == ("local_low_cost", "cheap_api")


def test_credential_rotation_health_and_environment_policies_are_present():
    report = build_credential_registry()
    assert len(report.rotation_policies) == len(report.credentials)
    assert all(item.status == "not_checked" for item in report.health_checks)
    assert {item.environment for item in report.environment_policies} == {"local", "ci", "staging", "production"}


@pytest.mark.parametrize("category", PROVIDER_CATEGORIES)
def test_provider_categories_are_valid(category: str):
    assert category in PROVIDER_CATEGORIES


@pytest.mark.parametrize("stage", INTEGRATION_STAGES)
def test_provider_integration_stages_are_valid(stage: str):
    assert stage in INTEGRATION_STAGES


@pytest.mark.parametrize("mode", ACTION_MODES)
def test_provider_action_modes_are_valid(mode: str):
    assert mode in ACTION_MODES


@pytest.mark.parametrize("provider_id", ("infisical", "doppler", "aws-secrets-manager", "gcp-secret-manager", "azure-key-vault", "github-actions-secrets", "supabase-secrets"))
def test_secret_providers_are_seeded(provider_id: str):
    provider = next(item for item in build_provider_registry().providers if item.provider_id == provider_id)
    assert provider.category == "secrets_manager"
    assert provider.default_action_mode == "reference_only"


@pytest.mark.parametrize("provider_id", ("litellm", "openai", "anthropic", "google-gemini", "mistral", "groq", "together", "aws-bedrock", "ollama", "llama-cpp", "vllm"))
def test_model_providers_are_seeded(provider_id: str):
    provider = next(item for item in build_provider_registry().providers if item.provider_id == provider_id)
    assert provider.category in {"llm_gateway", "llm_provider"}
    assert "model_spend" in provider.approval_ledger_mapping or provider_id in {"ollama", "llama-cpp", "vllm"}


@pytest.mark.parametrize("provider_id", ("langfuse", "phoenix", "open-telemetry"))
def test_observability_providers_are_seeded(provider_id: str):
    provider = next(item for item in build_provider_registry().providers if item.provider_id == provider_id)
    assert provider.category == "observability"
    assert provider.license_or_terms_risk


@pytest.mark.parametrize("provider_id", ("apify", "dataforseo", "serpapi", "bright-data", "scrapingbee", "scraperapi", "oxylabs", "browse-ai"))
def test_intelligence_candidates_are_seeded(provider_id: str):
    provider = next(item for item in build_provider_registry().providers if item.provider_id == provider_id)
    assert provider.approval_ledger_mapping
    assert provider.security_risk
    assert provider.operational_complexity


@pytest.mark.parametrize("provider_id", ("composio", "pipedream", "apideck", "unified-to", "activepieces", "n8n", "windmill"))
def test_integration_candidates_are_seeded(provider_id: str):
    provider = next(item for item in build_provider_registry().providers if item.provider_id == provider_id)
    assert provider.category in {"integration_platform", "workflow_automation"}
    assert provider.default_action_mode in {"reference_only", "write_requires_approval"}


@pytest.mark.parametrize("provider_id", ("twilio", "meta-whatsapp-cloud", "hubspot", "pipedrive", "quickbooks", "xero", "shopify", "medusa", "woocommerce", "webflow", "wix", "squarespace", "supabase"))
def test_operations_providers_are_seeded_safely(provider_id: str):
    provider = next(item for item in build_provider_registry().providers if item.provider_id == provider_id)
    assert provider.approval_ledger_mapping
    if provider.category in {"whatsapp_sms", "payments", "crm", "ecommerce_platform"}:
        assert provider.default_action_mode in {"blocked", "write_requires_approval"}


def test_apify_and_dataforseo_are_high_priority():
    report = build_provider_registry()
    assert "apify" in report.highest_priority_providers
    assert "dataforseo" in report.highest_priority_providers


def test_bright_data_and_oxylabs_are_not_current_priority():
    report = build_provider_registry()
    assert "bright-data" in report.providers_to_avoid_now or "bright-data" not in report.highest_priority_providers
    assert "oxylabs" in report.providers_to_avoid_now


def test_provider_seed_overrides_stage_and_action():
    report = build_provider_registry(seed={"providers": [{"provider_id": "apify", "integration_stage": "study_later", "default_action_mode": "blocked"}]})
    provider = next(item for item in report.providers if item.provider_id == "apify")
    assert provider.integration_stage == "study_later"
    assert provider.default_action_mode == "blocked"


def test_invalid_provider_seed_values_fail_closed():
    report = build_provider_registry(seed={"providers": [{"provider_id": "apify", "integration_stage": "unknown", "default_action_mode": "unknown"}]})
    provider = next(item for item in report.providers if item.provider_id == "apify")
    assert provider.integration_stage == "study_later"
    assert provider.default_action_mode == "blocked"


def test_provider_capability_matrix_has_one_row_per_provider():
    report = build_provider_registry()
    assert len(report.capability_matrix) == len(report.providers)
    assert all(item.confidence == "reference_only" for item in report.capability_matrix)


@pytest.mark.parametrize("status", SUBSCRIPTION_STATUSES)
def test_subscription_status_vocabulary_is_explicit(status: str):
    assert status in SUBSCRIPTION_STATUSES


@pytest.mark.parametrize("phase", PHASES)
def test_subscription_phase_cost_plan_covers_every_phase(phase: str):
    report = build_subscription_registry(phase=phase)
    assert {item.phase for item in report.cost_estimates} == set(PHASES)
    selected = next(item for item in report.cost_estimates if item.phase == phase)
    assert selected.monthly_min <= selected.monthly_max


def test_subscription_plans_have_owner_cost_usage_and_approval():
    report = build_subscription_registry()
    assert report.plans
    assert len(report.cost_bands) == len(report.plans)
    assert len(report.usage_budgets) == len(report.plans)
    assert all(item.approval_required_to_activate for item in report.plans)
    assert all(item.owner_department for item in report.plans)


def test_subscription_references_are_research_only():
    report = build_subscription_registry()
    assert all(item.status == "research_only" for item in report.plans)
    assert report.safety_summary["activated"] is False
    assert report.safety_summary["purchased"] is False


def test_subscription_consolidation_recommendations_cover_search_and_model():
    report = build_subscription_registry()
    actions = " ".join(item.action for item in report.consolidation_recommendations)
    assert "search provider" in actions
    assert "gateway" in actions


def test_subscription_renewal_and_cancellation_metadata_present():
    report = build_subscription_registry()
    assert len(report.renewal_policies) == len(report.plans)
    assert report.cancellation_candidates
    assert all(not item.auto_renew_allowed for item in report.renewal_policies)


def test_subscription_phase_argument_rejects_unknown_phase():
    with pytest.raises(ValueError, match="invalid subscription phase"):
        build_subscription_registry(phase="phase_unknown")


def test_intelligence_plan_has_all_requested_data_needs():
    plan = build_intelligence_provider_plan()
    need_ids = {item.data_need_id for item in plan.data_needs}
    assert need_ids == {"marketplace_demand", "competitor_pricing", "supplier_feasibility", "review_extraction", "consumer_attention", "search_serp_keyword", "ad_creative_signals", "social_public_snapshots", "official_api_validation", "scheduled_monitoring"}


@pytest.mark.parametrize("mode", ACQUISITION_MODES)
def test_acquisition_modes_are_explicit_and_network_default_off(mode: str):
    plan = build_intelligence_provider_plan()
    item = next(item for item in plan.acquisition_modes if item.mode == mode)
    assert item.network_allowed is False
    if mode in {"approved_live_read_only", "scheduled_read_only", "official_api_read_only"}:
        assert item.approval_required is True


def test_intelligence_plan_recommends_apify_for_broad_public_coverage():
    plan = build_intelligence_provider_plan()
    mapping = next(item for item in plan.coverage if item.provider_id == "apify")
    assert "marketplace_demand" in mapping.data_need_ids
    assert "scheduled_monitoring" in mapping.data_need_ids
    assert mapping.acquisition_mode == "approved_live_read_only"


def test_intelligence_plan_recommends_dataforseo_and_serpapi_for_search():
    plan = build_intelligence_provider_plan()
    for provider in ("dataforseo", "serpapi"):
        mapping = next(item for item in plan.coverage if item.provider_id == provider)
        assert mapping.data_need_ids == ("search_serp_keyword",)


def test_intelligence_plan_delays_enterprise_scraping_proxies():
    plan = build_intelligence_provider_plan()
    assert next(item for item in plan.coverage if item.provider_id == "bright-data").acquisition_mode == "blocked"
    assert next(item for item in plan.coverage if item.provider_id == "oxylabs").acquisition_mode == "blocked"


def test_intelligence_plan_requires_terms_and_privacy_review():
    plan = build_intelligence_provider_plan()
    assert all(item.tos_policy_review_required for item in plan.data_needs)
    assert all(item.privacy_review_required for item in plan.data_needs)
    assert all(item.blocking for item in plan.activation_gates)


def test_intelligence_plan_performs_no_acquisition():
    plan = build_intelligence_provider_plan()
    assert plan.safety_summary["network_calls"] is False
    assert plan.safety_summary["actor_runs"] is False
    assert plan.safety_summary["scraping_performed"] is False


def test_combined_report_counts_and_costs():
    report = build_provider_credential_report()
    assert report.provider_count >= 50
    assert report.credential_reference_count == 12
    assert report.subscription_count == 9
    assert report.intelligence_data_need_count == 10
    assert report.estimated_monthly_cost_min <= report.estimated_monthly_cost_max


def test_combined_report_has_priority_gaps_and_gates():
    report = build_provider_credential_report()
    assert "apify" in report.highest_priority_providers
    assert report.credential_gaps
    assert report.activation_gates
    assert report.subscription_consolidation
    assert report.next_best_action


def test_litellm_combined_mapping_has_model_routes():
    report = build_provider_credential_report()
    provider = next(item for item in report.providers.providers if item.provider_id == "litellm")
    assert set(provider.model_router_mapping) >= {"local_low_cost", "cheap_api", "frontier_reasoning"}
    credential = next(item for item in report.credentials.credentials if item.provider_id == "litellm")
    assert next(item for item in report.credentials.model_route_links if item.credential_id == credential.credential_id).approval_required is True


def test_langfuse_combined_mapping_is_future_trace_eval():
    report = build_provider_credential_report()
    provider = next(item for item in report.providers.providers if item.provider_id == "langfuse")
    assert "trace_collection" in provider.knowledge_registry_mapping
    assert provider.integration_stage == "integrate_soon"


def test_composio_combined_mapping_is_future_tool_integration():
    report = build_provider_credential_report()
    provider = next(item for item in report.providers.providers if item.provider_id == "composio")
    assert provider.category == "integration_platform"
    assert "workflow_resume" in provider.approval_ledger_mapping


def test_provider_filter_returns_selected_provider_in_priority():
    report = build_provider_credential_report(provider="apify")
    assert report.highest_priority_providers == ("apify",)


def test_unknown_provider_filter_fails():
    with pytest.raises(ValueError, match="unknown provider"):
        build_provider_credential_report(provider="not-a-provider")


def test_report_markdown_contains_required_sections():
    markdown = build_provider_credential_report().to_markdown()
    for section in ("Executive Summary", "Highest-Priority Providers", "Credential Gaps", "Intelligence Plan", "Activation Gates", "Providers To Avoid Now", "Safety", "Next Best Action"):
        assert f"## {section}" in markdown


@pytest.mark.parametrize("fixture_name", ("provider_registry_seed.json", "credential_registry_seed.json", "subscription_registry_seed.json", "intelligence_provider_plan_seed.json", "approval_links_seed.json", "tool_links_seed.json", "model_route_links_seed.json", "phase_2_live_read_only_intelligence_context.json", "secret_manager_context.json", "apify_provider_context.json", "dataforseo_provider_context.json", "litellm_provider_context.json", "langfuse_provider_context.json", "composio_provider_context.json", "malformed_provider_registry_input.json"))
def test_fixture_inputs_are_json_and_secret_free(fixture_name: str):
    data = json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8"))
    assert data is not None
    assert "api_key" not in json.dumps(data).lower()


def test_cli_default_json_is_offline_and_deterministic():
    first = run_cli("--json")
    second = run_cli("--json")
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout) == json.loads(second.stdout)
    assert json.loads(first.stdout)["safety_summary"]["network_calls"] is False


def test_cli_markdown_is_readable():
    result = run_cli("--markdown")
    assert result.returncode == 0
    assert result.stdout.startswith("# CompanyOS Provider / Credential Registry")
    assert "No secret values" in result.stdout


def test_cli_accepts_include_flags():
    result = run_cli("--include-credentials", "--include-providers", "--include-subscriptions", "--include-intelligence-plan", "--markdown")
    assert result.returncode == 0, result.stderr
    assert "Intelligence Plan" in result.stdout


def test_cli_phase_filter():
    result = run_cli("--phase", "phase_2_live_read_only_intelligence", "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["subscriptions"]["cost_estimates"][0]["phase"] == "phase_2_live_read_only_intelligence"


@pytest.mark.parametrize("provider", ("apify", "dataforseo", "litellm"))
def test_cli_provider_filter(provider: str):
    result = run_cli("--provider", provider, "--markdown")
    assert result.returncode == 0, result.stderr
    assert provider in result.stdout


def test_cli_accepts_seed_files():
    result = run_cli("--provider-seed", str(FIXTURES / "provider_registry_seed.json"), "--credential-seed", str(FIXTURES / "credential_registry_seed.json"), "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert next(item for item in payload["credentials"]["credentials"] if item["credential_id"] == "credential-apify")["status"] == "configured_reference_only"


def test_cli_rejects_secret_like_seed():
    result = run_cli("--provider-seed", str(FIXTURES / "secret_like_provider_input_rejected.json"), "--json")
    assert result.returncode == 2
    assert "secret-like" in result.stderr


def test_cli_rejects_traversal_path():
    result = run_cli("--provider-seed", "tests/fixtures/companyos_provider_registry/../companyos_registry/tool_registry_seed.json", "--json")
    assert result.returncode == 2
    assert "traversal" in result.stderr


def test_cli_writes_sanitized_exports(tmp_path: Path):
    output = tmp_path / "provider-registry"
    result = run_cli("--output", str(output), "--markdown")
    assert result.returncode == 0, result.stderr
    expected = {"provider_credential_report.json", "provider_credential_report.md", "credential_registry.json", "provider_registry.json", "subscription_registry.json", "intelligence_provider_plan.json", "provider_capability_matrix.json", "subscription_cost_plan.json", "credential_gap_report.json", "activation_gates.json"}
    assert {item.name for item in output.iterdir()} == expected
    assert "actual_secret_value" not in (output / "provider_credential_report.json").read_text(encoding="utf-8")


def test_cli_rejects_both_output_formats():
    result = run_cli("--json", "--markdown")
    assert result.returncode != 0


def test_cli_has_no_provider_call_language_as_execution():
    result = run_cli("--json")
    payload = json.loads(result.stdout)
    assert payload["safety_summary"]["provider_calls"] is False
    assert payload["safety_summary"]["subscriptions_activated"] is False
