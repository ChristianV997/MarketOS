"""Offline contract tests for the Meta Ad Library advertiser-transparency evidence layer.

Everything here is synthetic and offline. No test opens a socket, reads an environment variable, or loads a
credential. The live path is proven unreachable by blocking ``socket.socket``. Fixture
``tests/fixtures/ad_library/meta_ad_library_synthetic.json`` is invented; see docs/META_AD_LIBRARY_EVIDENCE.md.
"""

from __future__ import annotations

import ast
import json
import socket
from collections.abc import Mapping
from pathlib import Path

import pytest

from backend.adapters.research import meta_ad_library as bridge
from backend.contracts.adapters import SidecarContext
from evaluation.commerce import meta_ad_library_evidence as contract
from evaluation.commerce.meta_ad_library_evidence import UNAVAILABLE_BY_POLICY, build_ad_library_evidence

FIXTURE = Path(__file__).parent / "fixtures" / "ad_library" / "meta_ad_library_synthetic.json"
OBSERVED_AT = 1_790_000_000.0
CANARIES = (
    "SYNTHETIC_TOKEN_CANARY_0001",
    "SYNTHETIC_TOKEN_CANARY_0002",
    "SYNTHETIC_CURSOR",
    "owner@example.invalid",
    "access_token",
    "ads.example.invalid/render?",
    "graph.example.invalid",
    "Synthetic Region",
    "Traceback",
)
# Exact JSON string values that the policy says must never reach an output.
POLICY_VALUES = ('"1999"', '"1000"', '"199"', '"100"', '"0.5"', '"all"', '"25-34"', '"Synthetic Region"')
FORBIDDEN_IMPORTS = (
    "os",
    "socket",
    "requests",
    "httpx",
    "http",
    "subprocess",
    "ssl",
    "aiohttp",
    "urllib.request",
    "importlib",
    "asyncio",
    "ftplib",
    "smtplib",
    "ctypes",
)


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _dry_run() -> SidecarContext:
    return SidecarContext(workspace_id="test-workspace", run_id="run-1", dry_run=True)


def _live() -> SidecarContext:
    return SidecarContext(workspace_id="test-workspace", run_id="run-1", dry_run=False)


def _run(response, *, country="US", date_min=None, date_max=None, search_terms="synthetic kitchen organiser"):
    return build_ad_library_evidence(
        response,
        search_terms=search_terms,
        country=country,
        observed_at=OBSERVED_AT,
        date_min=date_min,
        date_max=date_max,
    )


def _body_response(*entries, paging=None, http_status=200):
    body = {"data": list(entries)}
    if paging is not None:
        body["paging"] = paging
    return {"http_status": http_status, "body": body}


def _record(report, ad_id):
    return next(record for record in report.records if record.ad_id == ad_id)


def _assert_no_canary(text: str) -> None:
    for canary in CANARIES:
        assert canary not in text, f"canary leaked: {canary!r}"


def _entry_with_copy(copy, **extra):
    base = {"id": "900000060", "page_id": "100000060", "ad_reached_countries": ["US"], "ad_creative_bodies": [copy]}
    base.update(extra)
    return base


def _imported_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


# --- field mapping ----------------------------------------------------------


def test_fixture_run_keeps_only_records_that_name_the_queried_country():
    report = _run(_fixture())

    assert [record.ad_id for record in report.records] == ["900000001", "900000002", "900000004", "900000005"]
    assert report.counts["received"] == 8
    assert report.counts["kept"] == 4
    assert dict(report.counts["dropped"]) == {
        "country_not_in_reached_countries": 1,
        "missing_or_invalid_id": 1,
        "geography_unavailable": 1,
        "malformed_entry": 1,
    }


def test_active_record_maps_identity_status_geography_and_reference_fields():
    record = _record(_run(_fixture()), "900000001")

    assert record.page_id == "100000001"
    assert record.page_name == "Synthetic Kitchen Co"
    assert record.delivery_start == "2026-08-01T10:00:00+00:00"
    assert record.delivery_stop is None
    assert record.delivery_status == "stop_time_absent"
    assert record.countries == ("US", "CA")
    assert record.platforms == ("FACEBOOK", "INSTAGRAM")
    assert record.creative_excerpt == "Synthetic countertop organiser for small kitchens. Ships in two days."
    assert record.creative_excerpt_truncated is False
    assert record.snapshot_reference == "https://ads.example.invalid/render"
    assert record.record_status == "ok"
    assert record.field_status["delivery_status"] == "derived"
    assert record.field_status["page_id"] == "supplied_fixture"


def test_ended_record_reports_both_dates_and_ended_status():
    record = _record(_run(_fixture()), "900000002")

    assert record.delivery_start == "2026-07-15T08:00:00+00:00"
    assert record.delivery_stop == "2026-08-10T08:00:00+00:00"
    assert record.delivery_status == "stop_time_recorded"


def test_timestamps_are_normalized_to_utc_and_naive_timestamps_are_malformed():
    entry = {
        "id": "900000010",
        "page_id": "100000010",
        "ad_delivery_start_time": "2026-08-01T12:00:00+02:00",
        "ad_reached_countries": ["US"],
    }
    assert _record(_run(_body_response(entry)), "900000010").delivery_start == "2026-08-01T10:00:00+00:00"

    naive = dict(entry, id="900000011", ad_delivery_start_time="2026-08-01T12:00:00")
    record = _record(_run(_body_response(naive)), "900000011")
    assert record.delivery_start is None
    assert record.field_status["delivery_start"] == "malformed"
    assert record.record_status == "partial"
    assert "delivery_start_malformed" in record.warnings


def test_unknown_or_malformed_start_makes_status_unavailable_not_guessed():
    record = _record(_run(_fixture()), "900000004")

    assert record.delivery_start is None
    assert record.delivery_status == "unavailable"
    assert record.field_status["delivery_status"] == "unavailable"
    assert "delivery_start_malformed" in record.warnings


def test_valid_stop_with_malformed_start_is_not_reported_as_ended():
    entry = {
        "id": "900000012",
        "page_id": "100000012",
        "ad_delivery_start_time": "2026-13-40T00:00:00Z",
        "ad_delivery_stop_time": "2026-08-10T08:00:00Z",
        "ad_reached_countries": ["US"],
    }
    record = _record(_run(_body_response(entry)), "900000012")

    assert record.delivery_status == "unavailable"
    assert record.delivery_stop == "2026-08-10T08:00:00+00:00"


def test_stop_time_before_start_is_rejected_and_status_becomes_unavailable():
    record = _record(_run(_fixture()), "900000005")

    assert record.delivery_stop is None
    assert record.field_status["delivery_stop"] == "malformed"
    assert "delivery_stop_before_start" in record.warnings
    assert record.delivery_status == "unavailable"


def test_year_nine_thousand_timestamp_is_malformed_and_does_not_cost_the_valid_records():
    valid = {
        "id": "900000013",
        "page_id": "100000013",
        "ad_reached_countries": ["US"],
        "ad_delivery_start_time": "2026-08-01T00:00:00+00:00",
    }
    extreme = {
        "id": "900000014",
        "page_id": "100000014",
        "ad_reached_countries": ["US"],
        "ad_delivery_start_time": "9999-12-31T23:00:00-05:00",
    }

    report = _run(_body_response(valid, extreme))

    assert [record.ad_id for record in report.records] == ["900000013", "900000014"]
    assert _record(report, "900000014").delivery_start is None
    assert "delivery_start_malformed" in _record(report, "900000014").warnings
    assert report.response_status == "partial"


def test_invalid_entries_are_dropped_from_lists_and_counted_as_partial():
    record = _record(_run(_fixture()), "900000005")

    assert record.countries == ("US",)
    assert record.platforms == ("FACEBOOK",)
    assert "countries_partially_invalid" in record.warnings
    assert "platforms_partially_invalid" in record.warnings
    assert record.page_id is None
    assert record.field_status["page_id"] == "malformed"
    assert record.record_status == "partial"


def test_a_filtered_first_entry_does_not_shadow_a_valid_later_entry_with_the_same_identifier():
    filtered_first = {"id": "900000401", "ad_reached_countries": ["GB"]}
    valid_later = {"id": "900000401", "ad_reached_countries": ["US"]}

    report = _run(_body_response(filtered_first, valid_later))

    assert [record.ad_id for record in report.records] == ["900000401"]
    assert dict(report.counts["dropped"]) == {"country_not_in_reached_countries": 1}
    assert report.response_status == "ok"


def test_duplicate_identifiers_keep_the_first_entry_and_are_counted():
    first = {"id": "900000203", "page_id": "100000203", "ad_reached_countries": ["US"]}
    second = {"id": "900000203", "page_id": "100000204", "ad_reached_countries": ["US"]}

    report = _run(_body_response(first, second))

    assert [record.ad_id for record in report.records] == ["900000203"]
    assert report.records[0].page_id == "100000203"
    assert report.counts["kept"] == 1
    assert dict(report.counts["dropped"]) == {"duplicate_id": 1}
    assert report.response_status == "partial"


def test_records_are_sorted_by_identifier_and_output_is_deterministic():
    first = _run(_fixture()).to_dict()
    second = _run(_fixture()).to_dict()

    assert first == second
    ids = [record["ad_id"] for record in first["records"]]
    assert ids == sorted(ids)


# --- geography --------------------------------------------------------------


def test_only_records_naming_the_queried_country_survive():
    report = _run(_fixture(), country="GB")

    assert [record.ad_id for record in report.records] == ["900000003"]
    assert dict(report.counts["dropped"])["country_not_in_reached_countries"] == 4


def test_record_without_any_country_is_dropped_fail_closed():
    entry = {"id": "900000020", "page_id": "100000020", "ad_delivery_start_time": "2026-08-01T00:00:00+00:00"}

    report = _run(_body_response(entry))

    assert report.records == ()
    assert dict(report.counts["dropped"]) == {"geography_unavailable": 1}


@pytest.mark.parametrize("country", ["us", "USA", "U", "", "u1", None, 840])
def test_invalid_country_is_rejected_before_any_record_is_read(country):
    report = _run(_fixture(), country=country)

    assert report.response_status == "invalid_request"
    assert report.records == ()
    assert report.query["country"] == ""


def test_complete_response_with_no_matching_country_is_ok_not_partial():
    entry = {
        "id": "900000030",
        "page_id": "100000030",
        "ad_reached_countries": ["US"],
        "ad_delivery_start_time": "2026-08-01T00:00:00+00:00",
    }

    report = _run(_body_response(entry), country="GB")

    assert report.records == ()
    assert report.response_status == "ok"
    assert dict(report.counts["dropped"]) == {"country_not_in_reached_countries": 1}


# --- date ranges ------------------------------------------------------------


def test_date_window_keeps_start_days_inside_the_window_and_drops_the_rest():
    report = _run(_fixture(), date_min="2026-08-01", date_max="2026-08-31")

    assert [record.ad_id for record in report.records] == ["900000001", "900000005"]
    assert dict(report.counts["dropped"]) == {
        "country_not_in_reached_countries": 1,
        "missing_or_invalid_id": 1,
        "geography_unavailable": 1,
        "malformed_entry": 1,
        "outside_date_window": 1,
        "date_unverifiable": 1,
    }


def test_window_bounds_are_inclusive_on_the_utc_start_day():
    report = _run(_fixture(), date_min="2026-07-15", date_max="2026-08-01")

    kept = [record.ad_id for record in report.records]
    assert "900000002" in kept
    assert "900000001" in kept


def test_window_uses_the_utc_day_not_the_local_day_of_the_timestamp():
    entry = {
        "id": "900000040",
        "page_id": "100000040",
        "ad_reached_countries": ["US"],
        "ad_delivery_start_time": "2026-08-01T23:30:00-05:00",
    }

    # 23:30 at -05:00 is 04:30 UTC on the next day, so the UTC day is 2026-08-02.
    local_day = _run(_body_response(entry), date_min="2026-08-01", date_max="2026-08-01")
    utc_day = _run(_body_response(entry), date_min="2026-08-02", date_max="2026-08-02")

    assert local_day.records == ()
    assert dict(local_day.counts["dropped"]) == {"outside_date_window": 1}
    assert [record.ad_id for record in utc_day.records] == ["900000040"]
    assert utc_day.records[0].delivery_start == "2026-08-02T04:30:00+00:00"
    assert utc_day.coverage["date_rule"] == "utc_calendar_day_of_supplied_delivery_start_inclusive"


@pytest.mark.parametrize(
    "date_min, date_max",
    [("2026-8-1", None), ("2026-02-30", None), (None, "not-a-date"), ("2026-09-01", "2026-08-01"), (20260801, None)],
)
def test_invalid_or_inverted_date_windows_are_refused(date_min, date_max):
    report = _run(_fixture(), date_min=date_min, date_max=date_max)

    assert report.response_status == "invalid_request"
    assert report.records == ()
    assert report.blockers in (("date_window_invalid",), ("date_window_inverted",))


# --- unsupported metrics and audience fields --------------------------------


def test_spend_impression_and_targeting_values_are_never_copied_to_output():
    report = _run(_fixture())
    text = json.dumps(report.to_dict())

    for value in POLICY_VALUES:
        assert value not in text, f"policy value leaked: {value}"
    # The policy names appear only inside field_status and policy_fields_present, as ``unavailable`` markers.
    record_body = _record(report, "900000001").to_dict()
    for key in ("field_status", "policy_fields_present"):
        record_body.pop(key)
    serialized = json.dumps(record_body)
    for name in ("spend", "impressions", "target_ages", "target_gender", "target_locations", "delivery_by_region"):
        assert f'"{name}"' not in serialized


def test_policy_fields_are_reported_as_unavailable_and_listed_by_name_only():
    record = _record(_run(_fixture()), "900000001")

    assert set(record.policy_fields_present) == {
        "spend",
        "impressions",
        "target_ages",
        "target_gender",
        "target_locations",
        "delivery_by_region",
    }
    for name in UNAVAILABLE_BY_POLICY:
        assert record.field_status[name] == "unavailable"


def test_supplied_fixture_is_not_a_live_ad_or_performance_outcome():
    entry = {
        "id": "900000090",
        "page_id": "100000090",
        "page_name": "Synthetic Fixture Page",
        "ad_creative_bodies": ["Synthetic fixture copy only."],
        "ad_delivery_start_time": "2026-08-01T00:00:00+00:00",
        "ad_reached_countries": ["DE"],
        "publisher_platforms": ["FACEBOOK", "instagram", "not-a-meta-surface"],
        "spend": {"lower_bound": "100", "upper_bound": "199"},
        "impressions": "<1000",
        "br_total_reach": 424242,
        "eu_total_reach": 515151,
        "bylines": "NotARealPayerName",
        "currency": "EUR",
        "target_ages": ["25-34"],
        "estimated_audience_size": {"lower_bound": "1000", "upper_bound": "5000"},
    }
    report = _run(_body_response(entry), country="DE")
    record = _record(report, "900000090")
    rendered = json.dumps(report.to_dict())

    assert record.platforms == ("FACEBOOK", "INSTAGRAM")
    assert "platforms_partially_invalid" in record.warnings
    assert record.delivery_status == "stop_time_absent"
    assert record.delivery_status not in {"delivering", "ended", "live"}
    assert set(record.field_status.values()).isdisjoint({"observed", "live", "verified"})
    assert "424242" not in rendered
    assert "515151" not in rendered
    assert "NotARealPayerName" not in rendered
    assert "EUR" not in rendered
    for flag in (
        "customer_attention",
        "purchase_evidence",
        "supplier_proof",
        "targeting_activated",
        "campaign_authority",
        "performance_outcome",
        "authenticated_observation",
        "live_ad",
        "publish",
        "spend",
        "launch",
    ):
        assert report.authority[flag] is False
    assert report.source_status == "fixture_not_authenticated_observation"
    assert report.access_method == "offline_fixture"


def test_report_declares_the_unavailable_policy_fields_coverage_and_no_authority():
    report = _run(_fixture())

    assert report.unavailable_by_policy == (
        "spend",
        "impressions",
        "delivery_by_region",
        "demographic_distribution",
        "estimated_audience_size",
        "eu_total_reach",
        "br_total_reach",
        "age_country_gender_reach_breakdown",
        "beneficiary_payers",
        "bylines",
        "currency",
        "total_reach_by_location",
        "target_ages",
        "target_gender",
        "target_locations",
    )
    assert all(value is False for value in report.authority.values())
    assert report.authority["customer_attention"] is False
    assert report.authority["purchase_evidence"] is False
    assert report.authority["targeting_activated"] is False
    assert report.authority["campaign_authority"] is False
    assert report.authority["performance_outcome"] is False
    assert report.authority["authenticated_observation"] is False
    assert report.authority["live_ad"] is False
    assert report.retry_attempts_allowed == 0
    assert report.coverage["coverage_statement"] == "fixture_only_primary_docs_do_not_make_this_an_observation"
    assert report.coverage["official_numeric_rate_limit"] == "not_stated_on_ads_archive_reference"
    assert report.coverage["delivery_times_are"] == "advertiser_intent_not_live_delivery"
    assert report.coverage["pagination_followed"] is False


def test_reports_and_records_pickle_and_copy_without_losing_read_only_guarantees():
    import copy
    import pickle

    report = _run(_fixture())

    restored = pickle.loads(pickle.dumps(report))
    assert restored.to_dict() == report.to_dict()
    assert copy.deepcopy(report).to_dict() == report.to_dict()
    with pytest.raises(TypeError):
        restored.authority["publish"] = True


def test_authority_and_mappings_are_read_only_at_runtime():
    report = _run(_fixture())
    record = _record(report, "900000001")

    with pytest.raises(TypeError):
        dict.__setitem__(report.authority, "publish", True)
    assert _run(_fixture()).authority["publish"] is False

    with pytest.raises(TypeError):
        report.authority["publish"] = True
    with pytest.raises(TypeError):
        record.field_status["spend"] = "observed"
    with pytest.raises(TypeError):
        report.counts["kept"] = 99


# --- malformed and partial responses ----------------------------------------


def test_pagination_link_marks_the_response_partial_and_is_never_followed():
    report = _run(_fixture())

    assert report.response_status == "partial"
    assert report.coverage["first_page_only"] is True
    assert "first_page_only_pagination_not_followed" in report.warnings
    _assert_no_canary(json.dumps(report.to_dict(), default=str))


def test_entry_without_identifier_or_mapping_is_dropped_without_failing_the_response():
    report = _run(_body_response("not-a-mapping", {"page_id": "100000030"}, {"id": "bad id with spaces"}))

    assert report.response_status == "partial"
    assert report.records == ()
    assert dict(report.counts["dropped"]) == {"malformed_entry": 1, "missing_or_invalid_id": 2}


def test_body_that_is_not_a_mapping_is_malformed():
    report = _run({"http_status": 200, "body": ["not", "a", "mapping"]})

    assert report.response_status == "malformed_response"
    assert report.blockers == ("body_not_mapping",)
    assert report.records == ()


def test_data_that_is_not_a_list_is_malformed():
    report = _run({"http_status": 200, "body": {"data": {"id": "900000040"}}})

    assert report.response_status == "malformed_response"
    assert report.blockers == ("data_not_list",)


def test_error_body_on_a_success_status_is_malformed_and_its_message_is_not_echoed():
    report = _run(
        {
            "http_status": 200,
            "body": {"error": {"code": 1, "message": "upstream said SYNTHETIC_TOKEN_CANARY_0001 at /private/root"}},
        }
    )

    assert report.response_status == "malformed_response"
    assert report.blockers == ("error_body_on_success_status",)
    _assert_no_canary(json.dumps(report.to_dict()))
    assert "/private/root" not in json.dumps(report.to_dict())


def test_response_that_is_not_a_mapping_is_malformed():
    report = _run(["http_status", 200])

    assert report.response_status == "malformed_response"
    assert report.blockers == ("response_not_mapping",)


def test_unexpected_success_range_status_is_malformed():
    report = _run({"http_status": 302, "body": {"data": []}})

    assert report.response_status == "malformed_response"
    assert report.blockers == ("unexpected_http_status",)


def test_record_limit_drops_only_the_overflow_and_says_so():
    entries = [
        {"id": f"9{index:08d}", "ad_reached_countries": ["US"]} for index in range(contract.MAX_INPUT_RECORDS + 3)
    ]

    report = _run(_body_response(*entries))

    assert report.counts["received"] == contract.MAX_INPUT_RECORDS + 3
    assert dict(report.counts["dropped"])["record_limit"] == 3
    assert "record_limit_exceeded" in report.warnings
    assert report.response_status == "partial"


# --- rate limits and unavailable access -------------------------------------


def test_rate_limit_status_returns_no_records_even_when_a_body_is_present():
    response = {
        "http_status": 429,
        "headers": {"retry-after": "60"},
        "body": {"data": [{"id": "900000050", "ad_reached_countries": ["US"]}]},
    }

    report = _run(response)

    assert report.response_status == "rate_limited"
    assert report.records == ()
    assert report.retry_attempts_allowed == 0
    assert "retry_not_permitted_in_offline_layer" in report.blockers


@pytest.mark.parametrize("status", [401, 403])
def test_refused_access_is_reported_without_echoing_the_provider_message(status):
    response = {
        "http_status": status,
        "body": {"error": {"message": "SYNTHETIC_TOKEN_CANARY_0001 denied for owner@example.invalid"}},
    }

    report = _run(response)

    assert report.response_status == "unavailable_access"
    assert "developer_access_unverified" in report.blockers
    assert report.records == ()
    _assert_no_canary(json.dumps(report.to_dict()))


@pytest.mark.parametrize("status", [500, 503])
def test_upstream_failure_is_reported_as_unavailable_not_as_an_empty_result(status):
    report = _run({"http_status": status, "body": {"data": []}})

    assert report.response_status == "upstream_unavailable"
    assert report.records == ()


# --- sanitization -----------------------------------------------------------


@pytest.mark.parametrize(
    "copy",
    [
        # Original withheld shapes.
        "Reach me at owner@example.invalid",
        "Call +1 555 010 1234 today",
        "Visit https://shop.example.invalid/offer now",
        "Use token sk_live_SYNTHETICCANARY0123 here",
        "Bearer SYNTHETIC_BEARER_VALUE for access",
        "Our access_token policy applies",
        # Bypass shapes found in review.
        "Reach me at owner @ example.invalid",
        "Reach me at owner​@example.invalid",
        "Reach me at owner＠example.invalid",
        "Reach me at owner<wbr>@example.invalid",
        "Reach me at owner&#64;example.invalid",
        "Shop at acme-deals.com today",
        "Call 555/010/1234 now",
        "Call 555–010–1234 now",
        "Use token EAAGxYz123456789abcdef today",
        "Use gho_ABCDEFGH12345678 today",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig",
        "access token abcdef12 here",
        "Bearer:abc123 here",
        "Use key sk_test_SYNTHETIC_0001 here",
        # Second review: separators, scripts, obfuscation, underscore identifiers, encoded tokens.
        "Call 06-12-34-56-78 today",
        "Call 030-12-34-56-78 today",
        "Call +44-20-8123-4567 now",
        "Call +1-55-50-10-1234 now",
        "Call 555 -- 010 1234 now",
        "Visit müller.de today",
        "Reach owner [at] example [dot] invalid",
        "Reach owner (at) example (dot) invalid",
        "javascript:alert(1) now",
        "DB_PASSWORD=hunter2 now",
        "client_secret abc here",
        "MY_SECRET_KEY here",
        "x_access_token here",
        "my_sk_live_SYNTHETIC0123 here",
        "Ships in two days.Really",
        "Login password123 now",
        "SECRETKEY=abc now",
        "passwordXYZ now",
        "x-access-token here",
        "Keep your secrets safe",
        "owner{at}example{dot}invalid",
        "owner<at>example<dot>invalid",
        "data:text/html,xx now",
        "Sale 01/08/2026 01/09/2026 only and 06-12-34-56-78 too",
        # Third review: separated digit groups after a date, invisible characters inside brackets, ideographic stops.
        "Call 12-08-2026 0208 1234 today",
        "Call 06-12-2034 56 78 today",
        "Sale 2026-08-01 2026-08-31 only",
        "Sale 01/08/2026 01/09/2026 only",
        "Sale 01-08-2026 - 31-08-2026 only",
        "owner<​at>example<​dot>invalid",
        "owner<\x00at>example",
        "owner<\xadat>example",
        "owner<at​>example",
        "owner[​at]example",
        "Shop shop。example。invalid",
        "Shop shop。com",
        "owner&lt;at&gt;example",
        # Fourth review: combining marks, enclosing marks, variation selectors, default-ignorable letters, entities.
        "owner<️at>example",
        "owner<͏at>example",
        "owner[́at]example",
        "owner<⃝at>example",
        "ownerㅤ@example",
        "owner<ㅤat>example",
        "pássword123 now",
        "PÁSSWORD=abc now",
        "p&#x301;assword123 now",
        "owner&#xFF20;example",
        "Use sḱ_live_SYNTHETICCANARY0123 here",
    ],
)
def test_creative_text_with_contact_link_or_secret_shapes_is_withheld_entirely(copy):
    record = _record(_run(_body_response(_entry_with_copy(copy))), "900000060")

    assert record.creative_excerpt is None
    assert record.field_status["creative_excerpt"] == "unavailable"
    assert "creative_excerpt_withheld" in record.warnings
    _assert_no_canary(json.dumps(record.to_dict()))


@pytest.mark.parametrize(
    "copy",
    [
        "Skateboarding gear for city riders",
        "Secretary needed for the Thursday shift",
        "Sale runs 2026-08-01 only today.",
        "Product data: waterproof",
    ],
)
def test_ordinary_words_and_dates_are_not_over_redacted(copy):
    record = _record(_run(_body_response(_entry_with_copy(copy))), "900000060")

    assert record.creative_excerpt is not None
    assert "creative_excerpt_withheld" not in record.warnings


def test_accented_copy_is_kept_with_its_accents_while_detection_ignores_them():
    record = _record(_run(_body_response(_entry_with_copy("Crème brûlée kit for two"))), "900000060")

    assert record.creative_excerpt == "Crème brûlée kit for two"
    assert "creative_excerpt_withheld" not in record.warnings


@pytest.mark.parametrize(
    "copy",
    [
        # Bracket rule is whole-content only, by decision. These are documented residuals, pinned here.
        "Reach (at domain dot com) today",
        "Shop example۔com now",
    ],
)
def test_bracketed_words_with_other_text_inside_are_kept_by_design(copy):
    record = _record(_run(_body_response(_entry_with_copy(copy))), "900000060")

    assert record.creative_excerpt == copy
    assert "creative_excerpt_withheld" not in record.warnings


def test_dates_and_sentence_breaks_are_kept_while_dash_grouped_numbers_are_withheld():
    kept = _record(_run(_body_response(_entry_with_copy("Ships in two days. Really good."))), "900000060")
    assert kept.creative_excerpt == "Ships in two days. Really good."


def test_html_wrapped_copy_is_kept_with_tags_removed():
    record = _record(_run(_body_response(_entry_with_copy("<b>Sale runs 2026-08-01</b> only\x07 today."))), "900000060")

    assert record.creative_excerpt == "Sale runs 2026-08-01 only today."


def test_long_copy_is_truncated_and_flagged_not_silently_shortened():
    record = _record(_run(_body_response(_entry_with_copy("Synthetic word " * 40))), "900000060")

    assert record.creative_excerpt_truncated is True
    assert len(record.creative_excerpt) <= contract.MAX_EXCERPT_CHARS
    assert "creative_excerpt_truncated" in record.warnings


def test_oversized_raw_copy_is_withheld_before_any_pattern_work():
    record = _record(_run(_body_response(_entry_with_copy("x" * (contract.MAX_RAW_TEXT_CHARS + 1)))), "900000060")

    assert record.creative_excerpt is None
    assert "creative_excerpt_withheld" in record.warnings


def test_snapshot_reference_drops_query_fragment_and_rejects_user_information():
    kept = _record(
        _run(
            _body_response(
                _entry_with_copy(
                    "Synthetic.",
                    ad_snapshot_url="https://ads.example.invalid/render/900000060?access_token=SYNTHETIC_TOKEN_CANARY_0001#frag",
                )
            )
        ),
        "900000060",
    )
    assert kept.snapshot_reference == "https://ads.example.invalid/render/900000060"

    userinfo = _record(
        _run(
            _body_response(_entry_with_copy("Synthetic.", ad_snapshot_url="https://user:secret@ads.example.invalid/x"))
        ),
        "900000060",
    )
    assert userinfo.snapshot_reference is None
    assert userinfo.field_status["snapshot_reference"] == "malformed"


@pytest.mark.parametrize(
    "path",
    [
        "/render/EAAGxYz123456789abcdef",
        "/%73k_live_ABCDEFGH12",
        "/%2573k_live_ABCDEFGH12",
        "/%2525252573k_live_ABCDEFGH12",
        "/render/sk_live_SYNTHETIC0123",
        "/x/%3Cat%3Ey",
        "/x/<at>y",
        # Fourth review: combining and variation marks inside encoded brackets, and a tag that hides an address.
        "/x/%3Cat%CC%81%3Ey",
        "/x/%3C%EF%B8%8Fat%3Ey",
        "/x/<a@b.invalid>y",
    ],
)
def test_snapshot_paths_carrying_token_shapes_are_withheld_even_when_encoded(path):
    record = _record(
        _run(_body_response(_entry_with_copy("Synthetic.", ad_snapshot_url="https://ads.example.invalid" + path))),
        "900000060",
    )

    assert record.snapshot_reference is None
    assert "snapshot_reference_withheld" in record.warnings


def test_snapshot_reference_must_be_https_and_absent_references_are_silent():
    plain = _record(
        _run(_body_response(_entry_with_copy("Synthetic.", ad_snapshot_url="http://ads.example.invalid/x"))),
        "900000060",
    )
    assert plain.snapshot_reference is None
    assert plain.field_status["snapshot_reference"] == "malformed"
    assert "snapshot_reference_malformed" in plain.warnings

    absent = _record(_run(_body_response(_entry_with_copy("Synthetic."))), "900000060")
    assert absent.snapshot_reference is None
    assert absent.field_status["snapshot_reference"] == "unavailable"
    assert absent.warnings == ()


def test_snapshot_www_hosts_are_kept_because_the_host_is_a_locator_not_text():
    record = _record(
        _run(
            _body_response(
                _entry_with_copy("Synthetic.", ad_snapshot_url="https://www.facebook.com/ads/archive/render_ad/?id=1")
            )
        ),
        "900000060",
    )

    assert record.snapshot_reference == "https://www.facebook.com/ads/archive/render_ad/"
    assert record.record_status == "ok"


def test_snapshot_reference_with_control_characters_is_rejected():
    record = _record(
        _run(_body_response(_entry_with_copy("Synthetic.", ad_snapshot_url="https://ads.example.invalid/x\x00y"))),
        "900000060",
    )

    assert record.snapshot_reference is None
    assert "snapshot_reference_malformed" in record.warnings


def test_page_name_longer_than_the_limit_is_withheld_not_shortened():
    record = _record(
        _run(_body_response(_entry_with_copy("Synthetic.", page_name="N" * (contract.MAX_PAGE_NAME_CHARS + 1)))),
        "900000060",
    )

    assert record.page_name is None
    assert "page_name_too_long" in record.warnings


def test_page_name_with_contact_shape_is_withheld():
    record = _record(
        _run(_body_response(_entry_with_copy("Synthetic.", page_name="Contact owner@example.invalid"))), "900000060"
    )

    assert record.page_name is None
    assert "page_name_withheld" in record.warnings


def test_control_and_invisible_characters_are_removed_before_checks():
    record = _record(_run(_body_response(_entry_with_copy("Synthetic\x00 desk\x1f lamp."))), "900000060")
    assert record.creative_excerpt == "Synthetic desk lamp."

    # Control characters are deleted without a gap, so they cannot split a token. The cost is that they can join words.
    joined = _record(_run(_body_response(_entry_with_copy("Synthetic\x9bdesk lamp."))), "900000060")
    assert joined.creative_excerpt == "Syntheticdesk lamp."

    spaced = _record(_run(_body_response(_entry_with_copy("Synthetic​ desk lamp."))), "900000060")
    assert spaced.creative_excerpt == "Synthetic desk lamp."


def test_search_terms_with_secret_or_contact_shape_are_refused_and_not_echoed():
    report = _run(_fixture(), search_terms="owner@example.invalid")

    assert report.response_status == "invalid_request"
    assert report.blockers == ("search_terms_withheld_sensitive",)
    _assert_no_canary(json.dumps(report.to_dict()))


@pytest.mark.parametrize(
    "terms",
    ["", "   ", "x" * (contract.MAX_SEARCH_TERMS_CHARS + 1), "bad\x00term", "bad​term", 42],
)
def test_invalid_search_terms_are_refused(terms):
    report = _run(_fixture(), search_terms=terms)

    assert report.response_status == "invalid_request"
    assert report.records == ()


# --- fail-closed behaviour and the offline boundary -------------------------


def test_missing_response_is_reported_as_no_offline_response():
    report = _run(None)

    assert report.response_status == "no_offline_response"
    assert report.records == ()
    assert report.blockers == ("no_offline_response_supplied",)


@pytest.mark.parametrize("observed_at", [float("nan"), float("inf"), 10**400, True, "1790000000"])
def test_unusable_observation_time_is_refused_without_raising(observed_at):
    report = build_ad_library_evidence(_fixture(), search_terms="synthetic", country="US", observed_at=observed_at)

    assert report.response_status == "invalid_request"
    assert report.blockers == ("observed_at_invalid",)


def test_report_serializes_to_json_and_carries_the_source_contract():
    payload = _run(_fixture()).to_dict()
    json.loads(json.dumps(payload))

    assert payload["source"] == "meta_ad_library_api"
    assert payload["source_status"] == "fixture_not_authenticated_observation"
    assert payload["evidence_tier"] == "ad_transparency_offline_non_live"
    assert payload["access_method"] == "offline_fixture"


def test_inputs_at_the_cap_run_the_detectors_and_stay_within_a_bounded_time():
    import time

    mixed_runs = "a1" * (contract.MAX_RAW_TEXT_CHARS // 2)
    assert len(mixed_runs) == contract.MAX_RAW_TEXT_CHARS
    withheld = _record(_run(_body_response(_entry_with_copy(mixed_runs))), "900000060")
    assert withheld.creative_excerpt is None
    assert "creative_excerpt_withheld" in withheld.warnings

    words = "word " * (contract.MAX_RAW_TEXT_CHARS // 5)
    truncated = _record(_run(_body_response(_entry_with_copy(words))), "900000060")
    assert truncated.creative_excerpt_truncated is True

    entries = [
        {
            "id": f"9{index:08d}",
            "page_id": "100000001",
            "page_name": "Synthetic Desk",
            "ad_reached_countries": ["US"],
            "ad_creative_bodies": [mixed_runs],
            "ad_delivery_start_time": "2026-08-01T00:00:00+00:00",
        }
        for index in range(contract.MAX_INPUT_RECORDS)
    ]
    started = time.perf_counter()
    report = _run(_body_response(*entries))
    elapsed = time.perf_counter() - started

    assert report.counts["kept"] == contract.MAX_INPUT_RECORDS
    assert elapsed < 10.0


def test_normalization_that_expands_text_is_refused_before_detection():
    expanding = "ﷺ" * (contract.MAX_RAW_TEXT_CHARS // 2)

    record = _record(_run(_body_response(_entry_with_copy(expanding))), "900000060")

    assert record.creative_excerpt is None
    assert "creative_excerpt_withheld" in record.warnings


def test_snapshot_host_with_encoded_at_sign_is_withheld():
    record = _record(
        _run(_body_response(_entry_with_copy("Synthetic.", ad_snapshot_url="https://owner%40example.invalid/x"))),
        "900000060",
    )

    assert record.snapshot_reference is None
    assert "snapshot_reference_withheld" in record.warnings


def test_builder_is_fail_closed_on_its_own_without_the_bridge():
    class Hostile(dict):
        def get(self, key, default=None):
            raise RuntimeError("SYNTHETIC_TOKEN_CANARY_0001 at /private/root")

    report = build_ad_library_evidence(Hostile(), search_terms="synthetic", country="US", observed_at=OBSERVED_AT)

    assert report.response_status == "malformed_response"
    assert report.blockers == ("offline_builder_failed",)
    _assert_no_canary(json.dumps(report.to_dict()))


def test_module_level_authority_defaults_are_read_only():
    with pytest.raises(TypeError):
        contract._AUTHORITY_VALUES["publish"] = True
    assert _run(_fixture()).authority["publish"] is False


def test_authority_tampering_in_one_report_does_not_reach_another_report():
    from types import MappingProxyType

    first = _run(_fixture())
    object.__setattr__(first.authority, "_data", MappingProxyType({"publish": True}))

    second = _run(_fixture())

    assert second.authority["publish"] is False
    assert all(value is False for value in second.authority.values())


def test_offline_modules_import_no_network_client_or_environment_access():
    for path in (Path(contract.__file__), Path(bridge.__file__)):
        source = path.read_text(encoding="utf-8")
        imported = _imported_names(ast.parse(source))
        for name in imported:
            for forbidden in FORBIDDEN_IMPORTS:
                assert not (name == forbidden or name.startswith(forbidden + ".")), f"{path.name} imports {name}"
        assert "os.environ" not in source
        assert "getenv" not in source


# --- bridge: dry-run and live fail-closed -----------------------------------


def test_bridge_dry_run_normalizes_the_supplied_fixture():
    report = bridge.fetch_ad_library_evidence(
        "synthetic kitchen organiser",
        country="US",
        context=_dry_run(),
        response=_fixture(),
        observed_at=OBSERVED_AT,
    )

    assert report.response_status == "partial"
    assert len(report.records) == 4
    _assert_no_canary(json.dumps(report.to_dict()))


def test_bridge_dry_run_without_a_fixture_reports_no_offline_response():
    report = bridge.fetch_ad_library_evidence("synthetic", country="US", context=_dry_run(), observed_at=OBSERVED_AT)

    assert report.response_status == "no_offline_response"
    assert report.records == ()


def test_bridge_live_mode_is_blocked_and_opens_no_socket(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("live mode must not open a socket")

    monkeypatch.setattr(socket, "socket", refuse)

    report = bridge.fetch_ad_library_evidence(
        "synthetic",
        country="US",
        context=_live(),
        response=_fixture(),
        observed_at=OBSERVED_AT,
    )

    assert report.response_status == "blocked_live_mode"
    assert report.records == ()
    assert report.blockers[0] == "live_mode_requested"
    assert set(bridge.LIVE_PREREQUISITES) <= set(report.blockers)
    assert any("primary-source verification" in item for item in report.blockers)


def test_bridge_live_mode_still_refuses_invalid_requests_without_echo():
    report = bridge.fetch_ad_library_evidence(
        "owner@example.invalid", country="US", context=_live(), observed_at=OBSERVED_AT
    )

    assert report.response_status == "invalid_request"
    assert report.blockers == ("search_terms_withheld_sensitive",)


@pytest.mark.parametrize("context", [_dry_run, _live])
def test_bridge_refuses_unusable_observation_time_in_both_modes_without_raising(context):
    report = bridge.fetch_ad_library_evidence(
        "synthetic", country="US", context=context(), response=_fixture(), observed_at=10**400
    )

    assert report.response_status == "invalid_request"
    assert report.blockers == ("observed_at_invalid",)


def test_bridge_fails_closed_when_the_offline_builder_raises_and_never_echoes_the_exception():
    class Hostile(Mapping):
        def __getitem__(self, key):
            raise RuntimeError("SYNTHETIC_TOKEN_CANARY_0001 at /private/root")

        def __iter__(self):
            return iter(())

        def __len__(self):
            return 1

        def get(self, key, default=None):
            raise RuntimeError("SYNTHETIC_TOKEN_CANARY_0001 at /private/root")

    report = bridge.fetch_ad_library_evidence(
        "synthetic",
        country="US",
        context=_dry_run(),
        response=Hostile(),
        observed_at=OBSERVED_AT,
    )

    assert report.response_status == "malformed_response"
    assert report.blockers == ("offline_builder_failed",)
    _assert_no_canary(json.dumps(report.to_dict()))
    assert "/private/root" not in json.dumps(report.to_dict())
