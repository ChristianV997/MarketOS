from __future__ import annotations

import json
from pathlib import Path

from evaluation.commerce.google_trends_attention_bridge import (
    UNBOUND_CANDIDATE_ID,
    compose_google_trends_attention,
)
from evaluation.commerce.google_trends_interest_adapter import build_google_trends_interest_report

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "google_trends_interest_adapter"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _interests(composition) -> list[float | None]:
    return [point.relative_interest for point in composition.source_series]


def test_valid_fixture_preserves_series_and_does_not_score_it() -> None:
    composition = compose_google_trends_attention(_load("trends_interest_valid.json"))
    assert composition.metric_kind == "relative_search_interest"
    assert composition.available_for_scoring is False
    assert composition.score_represents_relative_interest is False
    assert _interests(composition) == [38, 41, 22]
    assert [point.time_resolution for point in composition.source_series] == ["WEEK", "WEEK", "WEEK"]
    assert [point.observation_period_start for point in composition.source_series] == [
        "2024-01-01",
        "2024-01-08",
        "2024-01-01",
    ]
    assert {point.geography for point in composition.source_series} == {"US"}
    assert {point.language_metadata for point in composition.source_series} == {"en"}
    assert all(point.language_filter_confirmed is False for point in composition.source_series)
    assert all(row.language is None for row in composition.canonical_evidence)
    assert all(row.search_growth_signal is None and row.keyword == "" for row in composition.canonical_evidence)
    assert all(row.candidate_id == UNBOUND_CANDIDATE_ID for row in composition.canonical_evidence)
    report = composition.attention_report
    assert report.report_version == "consumer-attention-v1"
    assert report.network_calls is False and report.read_only is True and report.mutated is False
    assert report.evidence_count == 3
    for candidate in report.candidates:
        assert candidate.score.search_demand_signal == 0.0
        assert candidate.score.trend_growth_signal == 0.0
        assert candidate.score.search_signals == ()
        assert 38 not in candidate.score.contributions.values()
    encoded = json.dumps(composition.to_dict())
    assert '"currency": null' in encoded
    assert "USD" not in encoded
    assert composition.purchase_intent is None
    assert composition.absolute_search_volume is None
    assert composition.supplier_proof is False
    assert composition.launch_authority is False
    assert composition.network_calls is False


def test_missing_interest_stays_missing_across_partial_buckets() -> None:
    composition = compose_google_trends_attention(_load("trends_interest_partial.json"))
    assert _interests(composition) == [17, None, None]
    assert 0 not in _interests(composition)
    assert [point.status for point in composition.source_series] == ["stale", "unavailable", "incomplete"]
    assert [point.time_resolution for point in composition.source_series] == ["DAY", "DAY", "DAY"]
    assert {point.geography for point in composition.source_series} == {"US-CA"}
    missing = [row for row in composition.canonical_evidence if row.observation_value == "unavailable"]
    assert len(missing) == 2
    assert all(row.search_growth_signal is None for row in composition.canonical_evidence)


def test_zero_interest_is_preserved_and_still_not_a_growth_signal() -> None:
    payload = _load("trends_interest_valid.json")
    payload["series"] = [payload["series"][0]]
    payload["series"][0]["points"] = [payload["series"][0]["points"][0]]
    payload["series"][0]["points"][0]["relative_interest"] = 0
    composition = compose_google_trends_attention(payload)
    assert composition.source_series[0].relative_interest == 0
    assert composition.source_series[0].relative_interest is not None
    assert composition.canonical_evidence[0].search_growth_signal is None
    assert composition.canonical_evidence[0].observation_value == "0"


def test_omitted_geography_and_language_are_not_defaulted_onto_evidence() -> None:
    payload = _load("trends_interest_valid.json")
    payload.pop("language")
    payload.pop("geography")
    for entry in payload["series"]:
        entry.pop("language", None)
        entry.pop("geography", None)
        for point in entry["points"]:
            point.pop("language", None)
            point.pop("geography", None)
    composition = compose_google_trends_attention(payload)
    assert composition.source_series
    assert all(point.geography is None for point in composition.source_series)
    assert all(point.language_metadata is None for point in composition.source_series)
    assert all(row.geography is None and row.language is None for row in composition.canonical_evidence)
    assert composition.request_geography == "US"
    assert "geography_not_explicit_left_unavailable" in composition.canonical_evidence[0].warnings


def test_geography_mismatch_is_preserved() -> None:
    payload = _load("trends_interest_valid.json")
    payload["geography"] = "US"
    payload["series"][0]["geography"] = "MX"
    for point in payload["series"][0]["points"]:
        point["geography"] = "MX"
    composition = compose_google_trends_attention(payload)
    desk = [point for point in composition.source_series if point.term == "desk fan"]
    other = [point for point in composition.source_series if point.term != "desk fan"]
    assert {point.geography for point in desk} == {"MX"}
    assert {point.geography for point in other} == {"US"}
    assert composition.request_geography == "US"
    assert "geography_mismatch_preserved" in composition.canonical_evidence[0].warnings


def test_stale_point_keeps_interest_and_freshness() -> None:
    composition = compose_google_trends_attention(
        _load("trends_interest_stale.json"),
        as_of="2026-10-01T00:00:00Z",
    )
    point = composition.source_series[0]
    assert point.relative_interest == 55
    assert point.status == "stale"
    assert point.time_resolution == "MONTH"
    assert point.geography == "GB"
    assert composition.attention_report.freshness_status == "stale"
    assert composition.attention_report.network_calls is False
    assert composition.canonical_evidence[0].search_growth_signal is None


def test_duplicate_references_collapse_in_the_report_but_conflicts_do_not() -> None:
    payload = _load("trends_interest_valid.json")
    point = payload["series"][0]["points"][0]
    payload["series"] = [payload["series"][0]]
    payload["series"][0]["points"] = [point, dict(point), dict(point, relative_interest=99)]
    composition = compose_google_trends_attention(payload)
    assert _interests(composition) == [38, 38, 99]
    assert composition.attention_report.evidence_count == 2
    assert composition.attention_report.conflict_count == 1
    assert composition.attention_report.next_best_action == "resolve_consumer_attention_conflicts"
    assert all(row.search_growth_signal is None for row in composition.canonical_evidence)


def test_multiple_resolutions_stay_distinct() -> None:
    payload = _load("trends_interest_valid.json")
    payload["series"] = [payload["series"][0]]
    weekly = payload["series"][0]["points"][0]
    monthly = dict(weekly, time_resolution="MONTH", observation_period_end="2024-01-31", relative_interest=11)
    payload["series"][0]["points"] = [weekly, monthly]
    composition = compose_google_trends_attention(payload)
    assert [point.time_resolution for point in composition.source_series] == ["WEEK", "MONTH"]
    assert _interests(composition) == [38, 11]
    assert composition.attention_report.evidence_count == 2
    assert composition.attention_report.conflict_count == 0


def test_explicit_identity_link_is_exact_and_hints_are_ignored() -> None:
    payload = _load("trends_interest_valid.json")
    payload["candidate_id_hint"] = "hint-product"
    composition = compose_google_trends_attention(
        payload,
        identity_links={
            "candidate_id_hint": "hint-product",
            "desk fan": "cand-desk-fan",
            "Desk fan": "cand-wrong-case",
            "portable air cooler": "portable air cooler",
        },
    )
    assert "candidate_id_hint_ignored" in composition.warnings
    assert "identity_link_rejected_term_is_not_a_candidate" in composition.warnings
    bound = [row.candidate_id for row in composition.canonical_evidence if row.query == "desk fan"]
    unbound = [row.candidate_id for row in composition.canonical_evidence if row.query == "portable air cooler"]
    assert bound == ["cand-desk-fan", "cand-desk-fan"]
    assert unbound == [UNBOUND_CANDIDATE_ID]
    assert composition.identity_links_applied == ("desk fan",)
    assert "hint-product" not in {row.candidate_id for row in composition.canonical_evidence}


def test_query_plan_is_not_evidence() -> None:
    composition = compose_google_trends_attention(
        {"role": "plan", "is_plan": True, "is_evidence": False, "queries": ["desk fan buy"]}
    )
    assert composition.result_status == "plan_not_evidence"
    assert composition.source_series == ()
    assert composition.attention_report.evidence_count == 0
    assert "query_plan_is_not_collected_evidence" in composition.warnings


def test_malformed_provider_output_does_not_invent_zero() -> None:
    composition = compose_google_trends_attention({"fixture_mode": True, "series": "not-a-list"})
    assert composition.result_status == "rejected"
    assert composition.source_series == ()
    assert composition.attention_report.evidence_count == 0
    assert composition.available_for_scoring is False
    encoded = json.dumps(composition.to_dict())
    assert '"relative_interest": 0' not in encoded


def test_empty_fixture_is_incomplete_not_zero_filled() -> None:
    composition = compose_google_trends_attention(_load("trends_interest_empty.json"))
    assert composition.source_series == ()
    assert composition.result_status == "incomplete"
    assert composition.attention_report.evidence_count == 0
    assert composition.attention_report.warnings == ("consumer_attention_not_supplied",)


def test_live_mode_stays_blocked_and_fixture_labeled() -> None:
    composition = compose_google_trends_attention(_load("trends_interest_valid.json"), live_read_only=True)
    assert composition.live_mode_blocked is True
    assert composition.network_calls is False
    assert composition.live_request_created is False
    assert composition.evidence_mode == "fixture"
    assert composition.result_status == "unsupported_access"
    assert "live_mode_blocked_not_upgraded" in composition.warnings
    assert all(row.evidence_mode == "fixture" for row in composition.canonical_evidence)
    assert "live" not in {row.evidence_mode for row in composition.canonical_evidence}
    assert _interests(composition) == [38, 41, 22]
    assert composition.attention_report.network_calls is False


def test_report_object_path_still_refuses_scoring() -> None:
    report = build_google_trends_interest_report(payload=_load("trends_interest_valid.json"))
    composition = compose_google_trends_attention(report, identity_links={"desk fan": "cand-desk-fan"})
    assert composition.identity_links_applied == ("desk fan",)
    assert composition.source_series[0].language_metadata == "en"
    assert all(row.language is None for row in composition.canonical_evidence)
    assert all(row.search_growth_signal is None for row in composition.canonical_evidence)
    assert all(point.available_for_scoring is False for point in composition.source_series)
    assert composition.attention_report.candidates[0].score.search_signals == ()
