from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.commerce.dataforseo_adapter import (
    EVIDENCE_CATEGORIES,
    READINESS_STATES,
    REQUEST_KINDS,
    REQUEST_STATUSES,
    STOP_CONDITIONS,
    DataForSEOAdapterSafetySummary,
    DataForSEOOutputContract,
    DataForSEORequestPlan,
    DataForSEOSerpTask,
    build_dataforseo_adapter_report,
    parse_dataforseo_fixture,
    to_consumer_attention_signals,
    to_marketplace_trend_signals,
    to_opportunity_search_context,
    to_product_validation_search_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "dataforseo_adapter"
CLI = ROOT / "scripts" / "run_dataforseo_readonly_adapter.py"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CLI), *args], cwd=ROOT, text=True, capture_output=True, check=False)


def report(**kwargs):
    return build_dataforseo_adapter_report(**kwargs)


def test_default_report_is_safe_and_deterministic():
    first = report().to_dict()
    second = report().to_dict()
    assert first == second
    assert first["provider_id"] if "provider_id" in first else True
    assert first["safety_summary"]["network_calls"] is False
    assert first["safety_summary"]["credentials_loaded"] is False
    assert first["safety_summary"]["raw_payload_stored"] is False


@pytest.mark.parametrize("kind", REQUEST_KINDS)
def test_request_kind_vocabulary(kind: str):
    result = report(request_kind=kind)
    assert result.request_plan.request_kind == kind
    assert result.request_plan.live_request_created is False


@pytest.mark.parametrize("status", REQUEST_STATUSES)
def test_request_status_vocabulary(status: str):
    assert status in REQUEST_STATUSES


@pytest.mark.parametrize("state", READINESS_STATES)
def test_readiness_state_vocabulary(state: str):
    assert state in READINESS_STATES


@pytest.mark.parametrize("category", EVIDENCE_CATEGORIES)
def test_evidence_category_vocabulary(category: str):
    assert category in EVIDENCE_CATEGORIES


@pytest.mark.parametrize("condition", STOP_CONDITIONS)
def test_stop_condition_vocabulary(condition: str):
    assert condition in STOP_CONDITIONS


@pytest.mark.parametrize("kind,endpoint", (
    ("serp_google_organic_snapshot", "/serp/google/organic/task_post"),
    ("serp_google_shopping_snapshot", "/serp/google/shopping/task_post"),
    ("keyword_demand_snapshot", "/keywords_data/google_ads/search_volume/task_post"),
    ("competitor_serp_snapshot", "/serp/google/organic/task_post"),
    ("dry_run_fixture_parse", "fixture://dataforseo"),
))
def test_request_plan_endpoint_and_bounds(kind: str, endpoint: str):
    item = report(request_kind=kind).request_plan
    assert item.endpoint_placeholder == endpoint
    assert item.location_code_placeholder == "TBD"
    assert item.language_code == "en"
    assert item.max_requests >= 1
    assert item.max_items >= 1
    assert item.max_cost >= 0
    assert item.monthly_budget_cap >= item.max_cost


@pytest.mark.parametrize("field", ("live_request_created", "network_calls", "sdk_used", "raw_payload_stored", "schedule_enabled"))
def test_request_plan_safety_flags_are_false(field: str):
    assert getattr(report().request_plan, field) is False


def test_request_plan_uses_existing_provider_and_approval_vocabularies():
    item = report().request_plan
    assert item.provider_id == "dataforseo"
    assert item.credential_reference_id == "credential-dataforseo"
    assert item.approval_request_type in {"provider_call", "web_data_acquisition"}


def test_request_plan_rejects_live_request():
    with pytest.raises(ValueError):
        DataForSEORequestPlan("dataforseo", "plan", "serp_google_organic_snapshot", "fixture://", ("query",), "TBD", "en", "desktop", 1, 1, 1, 50, "credential-dataforseo", "provider_call", True, True, True, False, False, False, False, "blocked_live_mode")


def test_serp_task_rejects_invalid_kind():
    with pytest.raises(ValueError):
        DataForSEOSerpTask("query", "keyword_demand_snapshot")


def test_organic_fixture_parses():
    result = parse_dataforseo_fixture(load("dataforseo_serp_fixture.json"))
    assert result.parse_status == "parsed"
    assert len(result.search_signals) == 2
    assert result.shopping_signals == ()
    assert result.fixture.sanitized is True


def test_shopping_fixture_parses():
    result = parse_dataforseo_fixture(load("dataforseo_shopping_fixture.json"), request_kind="serp_google_shopping_snapshot")
    assert len(result.shopping_signals) == 2
    assert result.shopping_signals[0].evidence_category == "ShoppingResultEvidence"
    assert result.shopping_signals[0].seller_placeholder == "Synthetic Seller"


def test_keyword_fixture_parses_as_search():
    result = parse_dataforseo_fixture(load("dataforseo_keyword_fixture.json"), request_kind="keyword_demand_snapshot")
    assert len(result.search_signals) == 1
    assert result.search_signals[0].evidence_category == "SearchDemandEvidence"


def test_competitor_fixture_parses():
    result = parse_dataforseo_fixture(load("dataforseo_competitor_fixture.json"), request_kind="competitor_serp_snapshot")
    assert len(result.competitor_signals) == 1
    assert result.competitor_signals[0].evidence_category == "CompetitorSearchEvidence"
    assert result.competitor_signals[0].competitor_name == "Synthetic Competitor"


def test_mixed_fixture_parses_both_search_and_shopping():
    result = parse_dataforseo_fixture(load("dataforseo_mixed_fixture.json"), request_kind="serp_google_shopping_snapshot")
    assert result.search_signals
    assert result.shopping_signals
    assert result.competitor_signals


def test_empty_fixture_degrades_safely():
    result = parse_dataforseo_fixture(load("dataforseo_empty_results_fixture.json"))
    assert result.parse_status == "empty"
    assert result.search_signals == ()
    assert "empty_fixture_results" in result.warnings


def test_unexpected_schema_rejected():
    with pytest.raises(ValueError, match="tasks"):
        parse_dataforseo_fixture(load("dataforseo_unexpected_schema_fixture.json"))


@pytest.mark.parametrize("name", ("dataforseo_secret_like_fixture_rejected.json", "dataforseo_raw_html_fixture_rejected.json"))
def test_secret_or_html_fixture_rejected(name: str):
    with pytest.raises(ValueError, match="secret-like"):
        parse_dataforseo_fixture(load(name))


@pytest.mark.parametrize("field", ("source_provider", "source_method", "request_kind", "candidate_id", "query", "rank", "title", "url_placeholder", "domain_placeholder", "evidence_category", "confidence", "limitations", "terms_notes", "privacy_notes", "can_feed_reports"))
def test_search_signal_has_required_normalized_field(field: str):
    item = report().parse_result.search_signals[0].to_dict()
    assert field in item


@pytest.mark.parametrize("field", ("source_provider", "source_method", "request_kind", "candidate_id", "query", "rank", "title", "price", "currency", "seller_placeholder", "availability", "evidence_category", "confidence", "limitations", "terms_notes", "privacy_notes", "can_feed_reports"))
def test_shopping_signal_has_required_normalized_field(field: str):
    item = report(request_kind="serp_google_shopping_snapshot", payload=load("dataforseo_shopping_fixture.json"), source_file="fixture.json").parse_result.shopping_signals[0].to_dict()
    assert field in item


@pytest.mark.parametrize("field", ("source_provider", "source_method", "request_kind", "candidate_id", "query", "competitor_name", "domain_placeholder", "rank", "price", "currency", "commercial_intent_score", "evidence_category", "confidence", "limitations", "terms_notes", "privacy_notes", "can_feed_reports"))
def test_competitor_signal_has_required_normalized_field(field: str):
    item = report(request_kind="competitor_serp_snapshot", payload=load("dataforseo_competitor_fixture.json"), source_file="fixture.json").parse_result.competitor_signals[0].to_dict()
    assert field in item


def test_commercial_intent_is_bounded():
    for item in (*report().parse_result.search_signals, *report(request_kind="serp_google_shopping_snapshot").parse_result.shopping_signals, *report(request_kind="competitor_serp_snapshot", payload=load("dataforseo_competitor_fixture.json")).parse_result.competitor_signals):
        assert 0 <= item.commercial_intent_score <= 1


def test_no_raw_payload_or_html_in_parse_result():
    text = json.dumps(report().parse_result.to_dict()).lower()
    assert '"raw_payload"' not in text
    assert '"raw_html"' not in text
    assert "<html" not in text


def test_output_contract_is_sanitized_and_tested():
    contract = report().output_contract
    assert contract.fixture_tested is True
    assert contract.raw_payload_allowed is False
    assert contract.raw_html_allowed is False
    assert contract.provenance_required is True


def test_output_contract_rejects_raw_payloads():
    with pytest.raises(ValueError):
        DataForSEOOutputContract("unsafe", REQUEST_KINDS, ("Signal",), ("field",), True, False, True, False)


def test_provider_and_credential_readiness():
    item = report().approval_readiness
    credential = report().credential_readiness
    assert item.provider_registered is True
    assert item.credential_reference_exists is True
    assert item.secret_value_absent is True
    assert item.approval_required is True
    assert item.approval_request_type == "provider_call"
    assert credential.reference_exists is True
    assert credential.status == "metadata_only"


def test_dry_run_readiness_is_not_live_ready():
    item = report().approval_readiness
    assert item.readiness_state == "dry_run_ready"
    assert item.live_mode_blocked is True
    assert "approval_missing" in item.blockers
    assert "terms_review_missing" in item.blockers
    assert "privacy_review_missing" in item.blockers


def test_live_flag_fails_closed():
    item = report(live_read_only=True)
    assert item.approval_readiness.readiness_state == "blocked"
    assert item.request_plan.status == "blocked_live_mode"
    assert "live_mode_requested" in item.blocked_live_activation
    assert item.safety_summary.network_calls is False


@pytest.mark.parametrize("field", ("estimated_cost_per_request_min", "estimated_cost_per_request_max", "estimated_cost_per_run_min", "estimated_cost_per_run_max", "monthly_budget_cap"))
def test_cost_fields_present_and_nonnegative(field: str):
    assert getattr(report().cost_estimate, field) >= 0


def test_cost_bands_are_ordered():
    cost = report().cost_estimate
    assert cost.estimated_cost_per_request_min <= cost.estimated_cost_per_request_max
    assert cost.estimated_cost_per_run_min <= cost.estimated_cost_per_run_max
    assert cost.monthly_budget_cap >= cost.estimated_cost_per_run_max


@pytest.mark.parametrize("field", ("max_keywords_per_run", "max_requests_per_run", "max_results_per_keyword", "max_runs_per_day"))
def test_rate_limit_fields_present(field: str):
    assert getattr(report().rate_limit_plan, field) >= 1


def test_cost_and_rate_stop_conditions_are_complete():
    assert set(STOP_CONDITIONS) <= set(report().cost_estimate.stop_conditions)
    assert set(STOP_CONDITIONS) <= set(report().rate_limit_plan.stop_conditions)


def test_terms_privacy_status_blocks_live():
    item = report().terms_privacy_status
    assert item.terms_review_required is True
    assert item.privacy_review_required is True
    assert item.terms_review_complete is False
    assert item.privacy_review_complete is False
    assert set(item.blockers) == {"terms_review_missing", "privacy_review_missing"}


def test_to_marketplace_trend_signals():
    item = report(request_kind="serp_google_shopping_snapshot").to_marketplace_trend_signals()
    assert item
    assert item[0]["evidence_category"] == "MarketplaceTrendEvidence"
    assert item[0]["can_feed_reports"] is True


def test_to_consumer_attention_signals():
    item = report().to_consumer_attention_signals()
    assert item
    assert item[0]["evidence_category"] == "ConsumerAttentionEvidence"
    assert item[0]["keyword"]


def test_to_opportunity_search_context():
    item = report().to_opportunity_search_context()
    assert item["provider"] == "dataforseo"
    assert item["evidence_mode"] == "fixture_demo"
    assert item["network_calls"] is False


def test_to_product_validation_search_summary():
    item = report().to_product_validation_search_summary()
    assert item["provider"] == "dataforseo"
    assert item["confidence"] == "fixture"
    assert item["next_action"]


def test_module_conversion_helpers_match_report_methods():
    item = report(request_kind="serp_google_shopping_snapshot")
    assert to_marketplace_trend_signals(item) == item.to_marketplace_trend_signals()
    assert to_consumer_attention_signals(item) == item.to_consumer_attention_signals()
    assert to_opportunity_search_context(item) == item.to_opportunity_search_context()
    assert to_product_validation_search_summary(item) == item.to_product_validation_search_summary()


def test_report_markdown_sections():
    markdown = report().to_markdown()
    for heading in ("Executive Summary", "Request Plan", "Normalized Signals", "Approval and Credential Readiness", "Cost and Rate Limits", "Commerce Dry-Run Context", "Blocked Live Activation", "Safety Boundaries"):
        assert f"## {heading}" in markdown


def test_report_json_round_trip_is_safe():
    data = report().to_dict()
    assert json.loads(json.dumps(data)) == data


@pytest.mark.parametrize("kind,fixture", (
    ("serp_google_organic_snapshot", "dataforseo_serp_fixture.json"),
    ("serp_google_shopping_snapshot", "dataforseo_shopping_fixture.json"),
    ("keyword_demand_snapshot", "dataforseo_keyword_fixture.json"),
    ("competitor_serp_snapshot", "dataforseo_competitor_fixture.json"),
))
def test_explicit_fixture_cli(kind: str, fixture: str):
    result = run_cli("--fixture", str(FIXTURES / fixture), "--request-kind", kind, "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["request_plan"]["request_kind"] == kind
    assert payload["safety_summary"]["network_calls"] is False


def test_cli_markdown():
    result = run_cli("--markdown")
    assert result.returncode == 0
    assert result.stdout.startswith("# DataForSEO Read-Only Intelligence Adapter")
    assert "dry-run" in result.stdout


@pytest.mark.parametrize("kind", ("serp_google_organic_snapshot", "serp_google_shopping_snapshot", "keyword_demand_snapshot", "competitor_serp_snapshot"))
def test_cli_request_kind(kind: str):
    result = run_cli("--request-kind", kind, "--keyword", "mini thermal printer", "--markdown")
    assert result.returncode == 0, result.stderr
    assert kind in result.stdout


def test_cli_multiple_keywords():
    result = run_cli("--keyword", "mini thermal printer", "--keyword", "portable espresso maker", "--json")
    payload = json.loads(result.stdout)
    assert payload["request_plan"]["keywords"] == ["mini thermal printer", "portable espresso maker"]
    assert len(payload["keyword_tasks"]) == 2


def test_cli_feed_opportunity_context():
    result = run_cli("--feed-opportunity-context", "--markdown")
    assert result.returncode == 0
    assert "Commerce Dry-Run Context" in result.stdout


def test_cli_live_flag_is_blocked_without_network():
    result = run_cli("--live-read-only", "--json")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["approval_readiness"]["readiness_state"] == "blocked"
    assert payload["request_plan"]["status"] == "blocked_live_mode"
    assert payload["safety_summary"]["network_calls"] is False


def test_cli_output_exports_are_sanitized(tmp_path: Path):
    output = tmp_path / "dataforseo"
    result = run_cli("--fixture", str(FIXTURES / "dataforseo_mixed_fixture.json"), "--request-kind", "serp_google_shopping_snapshot", "--output", str(output), "--json")
    assert result.returncode == 0, result.stderr
    expected = {"dataforseo_adapter_report.json", "dataforseo_adapter_report.md", "dataforseo_request_plan.json", "dataforseo_readiness_checks.json", "dataforseo_cost_plan.json", "dataforseo_normalized_signals.json", "dataforseo_opportunity_context.json", "blocked_live_activation.json"}
    assert {item.name for item in output.iterdir()} == expected
    text = (output / "dataforseo_adapter_report.json").read_text(encoding="utf-8")
    assert '"raw_payload_stored": true' not in text
    assert "<html" not in text.lower()


def test_cli_rejects_path_traversal():
    result = run_cli("--fixture", "..\\tests\\fixtures\\dataforseo_adapter\\dataforseo_serp_fixture.json", "--json")
    assert result.returncode == 2
    assert "path traversal" in result.stderr


def test_cli_rejects_input_outside_repository(tmp_path: Path):
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"fixture_mode": True, "tasks": []}), encoding="utf-8")
    result = run_cli("--fixture", str(outside), "--json")
    assert result.returncode == 2
    assert "inside the repository" in result.stderr


def test_cli_rejects_secret_like_fixture():
    result = run_cli("--fixture", str(FIXTURES / "dataforseo_secret_like_fixture_rejected.json"), "--json")
    assert result.returncode == 2
    assert "secret-like" in result.stderr


def test_cli_rejects_raw_html_fixture():
    result = run_cli("--fixture", str(FIXTURES / "dataforseo_raw_html_fixture_rejected.json"), "--json")
    assert result.returncode == 2
    assert "secret-like" in result.stderr


def test_cli_rejects_two_formats():
    result = run_cli("--json", "--markdown")
    assert result.returncode != 0


def test_fixture_files_are_sanitized():
    for path in FIXTURES.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "rejected" in path.name:
            continue
        text = json.dumps(payload).lower()
        assert "raw_html" not in text
        assert "raw_payload" not in text
        assert "api_key" not in text


def test_safety_summary_constructor_rejects_network():
    with pytest.raises(ValueError):
        DataForSEOAdapterSafetySummary(True, False, True, False, False, False, False, False, True)


@pytest.mark.parametrize("flag", ("live_request_created", "network_calls", "sdk_used", "raw_payload_stored", "schedule_enabled"))
def test_report_safety_flags_are_false(flag: str):
    assert getattr(report().request_plan, flag) is False


def test_no_provider_response_or_sdk_language_in_execution_path():
    source = (ROOT / "scripts" / "run_dataforseo_readonly_adapter.py").read_text(encoding="utf-8").lower()
    assert "requests.get" not in source
    assert "httpx" not in source
    assert "dataforseo" in source
