from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.commerce.google_ads_keyword_demand_adapter import (
    DOCUMENTED_API_VERSION,
    OAUTH_SCOPE,
    PROVIDER_ID,
    DisabledLiveTransport,
    FakeGoogleAdsKeywordTransport,
    GoogleAdsKeywordDemandError,
    KeywordDemandAuthorization,
    classify_provider_error,
    collect_google_ads_keyword_demand,
    parse_historical_result,
)
from evaluation.companyos.approval_ledger import REQUEST_TYPES

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "run_google_ads_keyword_demand.py"
MODULE = ROOT / "evaluation" / "commerce" / "google_ads_keyword_demand_adapter.py"


def _approved() -> KeywordDemandAuthorization:
    return KeywordDemandAuthorization(
        approval_status="approved",
        credential_reference_present=True,
        cloud_project_access_level="basic",
        terms_review_complete=True,
        privacy_review_complete=True,
        quota_limit_acknowledged=True,
        cost_unknown_acknowledged=True,
    )


def _request(**overrides: object) -> dict:
    payload = {
        "method": "generate_keyword_historical_metrics",
        "keywords": ["thermal printer"],
        "geo_target_constants": ["geoTargetConstants/1000001"],
        "language_constant": "languageConstants/1003",
        "keyword_plan_network": "GOOGLE_SEARCH",
        "customer_reference_id": "credential-google-ads-customer",
    }
    payload.update(overrides)
    return payload


def _row(keyword: str = "thermal printer", **metrics: object) -> dict:
    return {"text": keyword, "keyword_idea_metrics": metrics}


def test_provider_constants_match_reviewed_docs() -> None:
    assert PROVIDER_ID == "google_ads_keyword_planner"
    assert DOCUMENTED_API_VERSION == "v26"
    assert OAUTH_SCOPE == "https://www.googleapis.com/auth/adwords"
    assert "provider_call" in REQUEST_TYPES


def test_module_does_not_import_a_live_client() -> None:
    import ast

    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    banned = {"socket", "urllib", "requests", "http", "google"}
    assert not any(name.split(".")[0] in banned for name in imported)


def test_missing_gates_do_not_call_transport_or_invent_keywords() -> None:
    transport = FakeGoogleAdsKeywordTransport([{"results": [_row(avg_monthly_searches=10)]}])
    report = collect_google_ads_keyword_demand(_request(), transport=transport)
    assert report.result_status == "blocked"
    assert report.observations == ()
    assert report.network_calls is False
    assert report.live_evidence is False
    assert report.fixture_fallback is False
    assert transport.calls == 0
    assert "approval_missing" in report.blockers


def test_approved_default_transport_stays_blocked_without_a_network_call() -> None:
    report = collect_google_ads_keyword_demand(_request(), _approved())
    assert isinstance(DisabledLiveTransport(), DisabledLiveTransport)
    assert report.result_status == "blocked_live_transport_not_implemented"
    assert report.observations == ()
    assert report.network_calls is False
    assert report.credentials_loaded is False
    assert report.live_transport_implemented is False
    assert report.live_evidence is False
    assert report.mutated is False
    assert report.request_plan is not None
    assert report.request_plan.live_request_created is False
    assert "{customer_reference}" in report.request_plan.endpoint_template
    assert report.request_plan.endpoint_template.startswith("https://googleads.googleapis.com/v26/")
    assert report.request_plan.developer_token_required is False


def test_fake_transport_runs_only_after_gates_and_is_not_labeled_live() -> None:
    transport = FakeGoogleAdsKeywordTransport([
        {"results": [_row(avg_monthly_searches=12, competition_index=40)]}
    ])
    report = collect_google_ads_keyword_demand(_request(), _approved(), transport=transport)
    assert transport.calls == 1
    assert report.result_status == "collected"
    assert report.live_evidence is False
    assert "live" not in report.result_status
    assert "synthetic_test_transport_not_live_evidence" in report.warnings
    assert report.observations[0].avg_monthly_searches == 12
    assert report.attention_projection["available_for_canonical_scoring"] is False
    assert report.attention_projection["rows"][0]["search_growth_signal"] is None


def test_null_search_count_is_not_zero_and_real_zero_is_kept() -> None:
    missing = parse_historical_result(_row(competition="UNSPECIFIED"), year_month_range=None)
    zero = parse_historical_result(_row(avg_monthly_searches=0), year_month_range=None)
    explicit_null = parse_historical_result(_row(avg_monthly_searches=None), year_month_range=None)
    assert missing.avg_monthly_searches is None
    assert explicit_null.avg_monthly_searches is None
    assert zero.avg_monthly_searches == 0
    assert missing.observation_window == "unavailable"
    assert zero.observation_window == "trailing_12_months_or_unspecified_range"


def test_micros_are_not_converted_and_currency_stays_null() -> None:
    row = parse_historical_result(
        _row(low_top_of_page_bid_micros=2_500_000, high_top_of_page_bid_micros=0, average_cpc_micros=1),
        year_month_range=None,
    )
    assert row.low_top_of_page_bid_micros == 2500000
    assert row.high_top_of_page_bid_micros == 0
    assert row.average_cpc_micros == 1
    assert row.currency is None
    assert row.bid_unit == "micros"
    assert row.search_growth_signal is None
    assert row.available_for_canonical_scoring is False


def test_competition_index_above_100_is_not_clamped() -> None:
    transport = FakeGoogleAdsKeywordTransport([
        {"results": [_row(avg_monthly_searches=3, competition_index=101)]}
    ])
    report = collect_google_ads_keyword_demand(_request(), _approved(), transport=transport)
    assert report.observations == ()
    assert any("competition_index" in warning for warning in report.warnings)
    assert "101" not in json.dumps(report.to_dict())


def test_geography_and_language_are_not_defaulted() -> None:
    missing_geo = collect_google_ads_keyword_demand(
        {key: value for key, value in _request().items() if key != "geo_target_constants"},
        _approved(),
    )
    missing_language = collect_google_ads_keyword_demand(
        {key: value for key, value in _request().items() if key != "language_constant"},
        _approved(),
    )
    missing_network = collect_google_ads_keyword_demand(
        {key: value for key, value in _request().items() if key != "keyword_plan_network"},
        _approved(),
    )
    for report in (missing_geo, missing_language, missing_network):
        assert report.observations == ()
        assert report.request_plan is None
        assert report.result_status == "unavailable"
    explicit = collect_google_ads_keyword_demand(
        _request(
            geo_target_constants=[],
            all_locations=True,
            language_constant=None,
            language_unspecified=True,
        ),
        _approved(),
    )
    assert explicit.request_plan is not None
    assert explicit.request_plan.geo_target_constants == ()
    assert explicit.request_plan.language_constant is None
    assert "2840" not in json.dumps(explicit.request_plan.to_dict())
    assert explicit.request_plan.language_constant != "languageConstants/1000"


def test_seed_geo_and_historical_caps() -> None:
    ideas = dict(_request(method="generate_keyword_ideas", keywords=[f"k{i}" for i in range(21)]))
    historical = _request(keywords=[f"k{i}" for i in range(51)])
    geos = _request(geo_target_constants=[f"geoTargetConstants/{i}" for i in range(1, 12)])
    for payload in (ideas, historical, geos):
        report = collect_google_ads_keyword_demand(payload, _approved())
        assert report.observations == ()
        assert report.request_plan is None
    twenty = collect_google_ads_keyword_demand(
        _request(method="generate_keyword_ideas", keywords=[f"k{i}" for i in range(20)]),
        _approved(),
    )
    assert twenty.request_plan is not None
    assert len(twenty.request_plan.keywords) == 20


def test_forecast_site_seed_and_fixture_keys_are_rejected() -> None:
    transport = FakeGoogleAdsKeywordTransport([{"results": [_row(avg_monthly_searches=9)]}])
    forecast = collect_google_ads_keyword_demand(
        _request(method="generate_keyword_forecast_metrics"),
        _approved(),
        transport=transport,
    )
    site = collect_google_ads_keyword_demand(_request(site_seed="www.example.com"), _approved(), transport=transport)
    fixture = collect_google_ads_keyword_demand(
        _request(fixture_keywords=["invented keyword"]),
        _approved(),
        transport=transport,
    )
    assert forecast.observations == ()
    assert "forecast" in forecast.blockers[0]
    assert site.observations == ()
    assert fixture.result_status == "rejected"
    assert fixture.observations == ()
    assert transport.calls == 0


def test_secrets_and_numeric_customer_ids_are_not_echoed() -> None:
    token = "ya29.super-secret-token"
    account = "1234567890"
    with pytest.raises(GoogleAdsKeywordDemandError) as raised:
        collect_google_ads_keyword_demand(_request(access_token=token), _approved())
    assert token not in str(raised.value)
    report = collect_google_ads_keyword_demand(_request(customer_reference_id=account), _approved())
    encoded = json.dumps(report.to_dict())
    assert account not in encoded
    assert report.observations == ()
    with pytest.raises(GoogleAdsKeywordDemandError) as linked:
        collect_google_ads_keyword_demand(
            _request(),
            _approved(),
            identity_links={"thermal printer": token},
        )
    assert token not in str(linked.value)


def test_pagination_cap_marks_incomplete_without_reading_further_pages() -> None:
    transport = FakeGoogleAdsKeywordTransport([
        {"results": [_row("thermal printer", avg_monthly_searches=4)], "next_page_token": "page-2"},
        {"results": [_row("label maker", avg_monthly_searches=8)]},
    ])
    report = collect_google_ads_keyword_demand(_request(max_pages=1, page_size=100), _approved(), transport=transport)
    assert [item.keyword for item in report.observations] == ["thermal printer"]
    assert report.result_status == "incomplete"
    assert "adapter_page_cap_reached" in report.warnings
    assert "next_page_not_read" in report.warnings
    assert "label maker" not in json.dumps(report.to_dict())


def test_identity_links_are_exact_and_hints_do_not_score() -> None:
    transport = FakeGoogleAdsKeywordTransport([
        {"results": [_row(avg_monthly_searches=6)]}
    ])
    report = collect_google_ads_keyword_demand(
        _request(),
        _approved(),
        transport=transport,
        identity_links={
            "thermal printer": "cand-1",
            "Thermal printer": "cand-case",
            "candidate_id_hint": "invented",
            "term_hint": "also-invented",
            "thermal printer ": "cand-space",
            "same": "same",
        },
    )
    row = report.attention_projection["rows"][0]
    assert row["candidate_id"] == "cand-1"
    assert row["available_for_canonical_scoring"] is False
    assert row["search_growth_signal"] is None
    assert report.attention_projection["canonical_schema_mutated"] is False
    assert "candidate_id_hint_ignored" in report.attention_projection["warnings"]
    assert "invented" not in json.dumps(row)


def test_resource_exhausted_is_rate_limited_and_does_not_keep_keywords() -> None:
    secret_account = "99887766"
    transport = FakeGoogleAdsKeywordTransport([
        {
            "error": {
                "status": "RESOURCE_EXHAUSTED",
                "message": f"quota for customer {secret_account}",
                "details": [{"errors": [{"error_code": {"quota_error": "RESOURCE_EXHAUSTED"}}]}],
            },
            "results": [_row(avg_monthly_searches=99)],
        }
    ])
    report = collect_google_ads_keyword_demand(_request(), _approved(), transport=transport)
    assert report.result_status == "rate_limited"
    assert report.observations == ()
    assert secret_account not in json.dumps(report.to_dict())
    assert classify_provider_error({"error": {"status": "DEADLINE_EXCEEDED"}}) == "timed_out"
    assert classify_provider_error({"status": "PERMISSION_DENIED"}) == "authorization_unavailable"


def test_transport_cannot_mark_a_network_call() -> None:
    class Hostile:
        def execute(self, plan):  # noqa: ANN001
            del plan
            from evaluation.commerce.google_ads_keyword_demand_adapter import KeywordDemandTransportResult

            return KeywordDemandTransportResult("collected", (), (), 1, False, True, False)

    with pytest.raises(GoogleAdsKeywordDemandError):
        collect_google_ads_keyword_demand(_request(), _approved(), transport=Hostile())


def _run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=merged,
    )


def test_cli_has_no_fixture_flag_and_ignores_environment_secrets(tmp_path: Path) -> None:
    help_result = _run_cli("--help")
    assert help_result.returncode == 0
    assert "--fixture" not in help_result.stdout
    assert "os.environ" not in CLI.read_text(encoding="utf-8")
    request = tmp_path / "request.json"
    request.write_text(json.dumps(_request()), encoding="utf-8")
    token = "ya29.cli-must-not-print"
    result = _run_cli(
        "--request",
        str(request),
        env={"GOOGLE_ADS_DEVELOPER_TOKEN": token, "GOOGLE_ADS_REFRESH_TOKEN": token},
    )
    assert result.returncode == 0
    assert token not in result.stdout
    assert token not in result.stderr
    payload = json.loads(result.stdout)
    assert payload["result_status"] == "blocked"
    assert payload["observations"] == []
    assert payload["network_calls"] is False


def test_cli_rejects_secret_file_without_echoing_it(tmp_path: Path) -> None:
    token = "ya29.do-not-echo"
    request = tmp_path / "request.json"
    body = _request()
    body["refresh_token"] = token
    request.write_text(json.dumps(body), encoding="utf-8")
    result = _run_cli("--request", str(request))
    assert result.returncode == 2
    assert token not in result.stdout
    assert token not in result.stderr
    assert result.stdout == ""


def test_cli_rejects_path_traversal() -> None:
    result = _run_cli("--request", "../secrets.json")
    assert result.returncode == 2
    assert "secrets.json" not in result.stderr
