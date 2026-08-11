"""Deterministic model, importer, creative extraction, and synthesis tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.adapters.research.consumer_attention import ConsumerAttentionImportError, contains_secret, import_csv, import_json, normalize_record, validate_input_path
from evaluation.commerce.consumer_attention import PROVENANCE, SOURCE_TYPES, ConsumerAttentionEvidence, build_report, extract_creative_angles, normalize_intent, normalize_sentiment, score_candidate

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "consumer_attention"


def fixture(name: str) -> Path:
    return FIXTURES / name


def test_provenance_vocabulary_is_bounded():
    assert PROVENANCE == {"observed", "derived", "assumed", "unavailable", "malformed", "blocked", "manual_import", "fixture"}


def test_source_vocabulary_contains_requested_families():
    for source in ("google_trends_fixture", "tiktok_creative_center_snapshot", "tiktok_ad_snapshot", "meta_ad_library_snapshot", "youtube_search_snapshot", "reddit_threads_manual_import", "amazon_reviews_snapshot", "mercadolibre_reviews_snapshot", "ebay_reviews_snapshot", "shopify_reviews_snapshot", "minea_manual_import", "minee_manual_import", "dropshipio_manual_import", "pipiads_manual_import", "kalodata_manual_import", "manual_csv_import"):
        assert source in SOURCE_TYPES


@pytest.mark.parametrize("value,expected", [("positive", "positive"), ("very negative", "negative"), ("mixed", "mixed"), ("unknown label", "unknown"), ("love", "positive")])
def test_sentiment_normalization(value, expected):
    assert normalize_sentiment(value) == expected


@pytest.mark.parametrize("value,expected", [("buy", "transactional"), ("compare", "commercial_research"), ("learn", "informational"), ("problem", "problem_aware"), ("other", "unknown")])
def test_intent_normalization(value, expected):
    assert normalize_intent(value) == expected


def test_google_trends_fixture_imports():
    rows = import_json(fixture("google_trends_fixture.json"), platform="google_trends", source_type="google_trends_fixture")
    assert len(rows) == 2
    assert rows[0].platform == "google_trends"
    assert rows[0].search_growth_signal == 0.78


@pytest.mark.parametrize("name,platform,source", [("tiktok_creative_center_snapshot.json", "tiktok", "tiktok_creative_center_snapshot"), ("tiktok_ad_snapshot.json", "tiktok", "tiktok_ad_snapshot"), ("meta_ad_library_snapshot.json", "meta", "meta_ad_library_snapshot"), ("youtube_search_snapshot.json", "youtube", "youtube_search_snapshot"), ("reddit_threads_manual_import.json", "reddit", "reddit_threads_manual_import"), ("amazon_reviews_snapshot.json", "amazon", "amazon_reviews_snapshot"), ("mercadolibre_reviews_snapshot.json", "mercadolibre", "mercadolibre_reviews_snapshot"), ("ebay_reviews_snapshot.json", "ebay", "ebay_reviews_snapshot"), ("shopify_reviews_snapshot.json", "shopify", "shopify_reviews_snapshot")])
def test_json_source_importers(name, platform, source):
    rows = import_json(fixture(name), platform=platform, source_type=source)
    assert rows
    assert rows[0].platform == platform
    assert rows[0].source_type == source
    assert rows[0].read_only and not rows[0].network_calls and not rows[0].mutated


@pytest.mark.parametrize("name,platform,source", [("youtube_comments_manual_import.csv", "youtube", "youtube_comments_manual_import"), ("reddit_comments_manual_import.csv", "reddit", "reddit_comments_manual_import"), ("minee_manual_import.csv", "minea", "minea_manual_import"), ("dropshipio_manual_import.csv", "dropshipio", "dropshipio_manual_import"), ("pipiads_manual_import.csv", "pipiads", "pipiads_manual_import"), ("kalodata_manual_import.csv", "kalodata", "kalodata_manual_import"), ("mixed_consumer_attention_import.csv", "manual", "manual_csv_import")])
def test_csv_source_importers(name, platform, source):
    rows = import_csv(fixture(name), platform=platform, source_type=source)
    assert rows
    assert all(row.evidence_mode == "manual_import" for row in rows)
    assert all(row.source_type == source for row in rows)


def test_malformed_csv_degrades_to_empty():
    assert import_csv(fixture("malformed_consumer_attention_import.csv")) == []


def test_secret_like_json_is_rejected():
    assert import_json(fixture("secret_like_consumer_attention_rejected.json")) == []


@pytest.mark.parametrize("payload", [{"api_key": "secret"}, {"authorization": "Bearer private"}, {"cookie": "private"}, {"nested": {"token": "secret"}}])
def test_secret_detection(payload):
    assert contains_secret(payload)


def test_normal_value_is_not_secret():
    assert not contains_secret({"hook": "Print labels anywhere", "view_count": 1000})


def test_path_traversal_rejected():
    with pytest.raises(ConsumerAttentionImportError):
        validate_input_path(FIXTURES / ".." / "private.json")


def test_unsupported_path_rejected(tmp_path):
    path = tmp_path / "input.txt"
    path.write_text("private", encoding="utf8")
    with pytest.raises(ConsumerAttentionImportError):
        validate_input_path(path)


def test_missing_candidate_id_is_skipped():
    assert normalize_record({"platform": "manual", "hook": "ignored"}) is None


def test_unknown_platform_is_skipped():
    assert normalize_record({"candidate_id": "x", "platform": "private"}) is None


def test_nested_content_fields_are_supported():
    row = normalize_record({"candidate_id": "x", "platform": "manual", "content": {"hook": "Solve the messy problem", "pain_point": "messy setup"}})
    assert row is not None
    assert row.hook == "Solve the messy problem"
    assert row.pain_point == "messy setup"


def test_metrics_are_normalized():
    row = normalize_record({"candidate_id": "x", "platform": "tiktok", "view_count": "10K", "like_count": "1.2K", "search_growth_signal": "0.6"})
    assert row is not None
    assert row.view_count == 10000
    assert row.like_count == 1200
    assert row.search_growth_signal == 0.6


def test_evidence_json_is_safe():
    row = import_json(fixture("tiktok_creative_center_snapshot.json"), platform="tiktok", source_type="tiktok_creative_center_snapshot")[0]
    json.dumps(row.to_dict())
    assert row.read_only and not row.network_calls and not row.mutated


def test_evidence_rejects_mutation():
    with pytest.raises(ValueError):
        ConsumerAttentionEvidence("x", "x", "manual", "fixture_demo", mutated=True)


def test_no_evidence_recommends_low_attention():
    score = score_candidate("x", [])
    assert score.recommendation == "reject_low_attention"


def test_google_trend_improves_search_signal():
    row = import_json(fixture("google_trends_fixture.json"), platform="google_trends", source_type="google_trends_fixture")[0]
    assert score_candidate(row.candidate_id, [row]).search_demand_signal > 0
    assert score_candidate(row.candidate_id, [row]).trend_growth_signal > 0


def test_social_engagement_signal_uses_view_and_engagement():
    row = import_json(fixture("tiktok_creative_center_snapshot.json"), platform="tiktok", source_type="tiktok_creative_center_snapshot")[0]
    assert score_candidate(row.candidate_id, [row]).social_engagement_signal > 0


def test_ad_activity_signal_uses_active_flag():
    row = import_json(fixture("tiktok_ad_snapshot.json"), platform="tiktok", source_type="tiktok_ad_snapshot")[0]
    assert score_candidate(row.candidate_id, [row]).ad_activity_signal == 1


def test_review_density_and_voc_use_review_fields():
    row = import_json(fixture("amazon_reviews_snapshot.json"), platform="amazon", source_type="amazon_reviews_snapshot")[0]
    score = score_candidate(row.candidate_id, [row])
    assert score.review_density_signal > 0
    assert score.voice_of_customer_quality > 0


def test_pain_point_clarity_is_observable():
    row = normalize_record({"candidate_id": "x", "platform": "reddit", "pain_point": "hard to clean", "desired_outcome": "easy cleaning"})
    assert row is not None
    assert score_candidate("x", [row]).pain_point_clarity == 1


def test_objection_density_increases_risk():
    row = normalize_record({"candidate_id": "x", "platform": "reddit", "objection": "concern about durability"})
    assert row is not None
    assert score_candidate("x", [row]).objection_density == 1


def test_hook_diversity_increases_with_distinct_hooks():
    rows = [normalize_record({"candidate_id": "x", "platform": "tiktok", "hook": f"Hook {index}"}) for index in range(4)]
    rows = [row for row in rows if row]
    assert score_candidate("x", rows).creative_hook_diversity == 1


def test_ugc_scriptability_and_visual_demo_are_scored():
    row = normalize_record({"candidate_id": "x", "platform": "tiktok", "ugc_scriptability": 0.9, "visual_demo_score": 0.8})
    assert row is not None
    score = score_candidate("x", [row])
    assert score.ugc_scriptability == 0.9
    assert score.visual_demo_potential == 0.8


def test_intent_strength_is_scored():
    row = normalize_record({"candidate_id": "x", "platform": "google_trends", "intent_label": "transactional"})
    assert row is not None
    assert score_candidate("x", [row]).intent_strength == 1


def test_source_diversity_is_scored():
    rows = [normalize_record({"candidate_id": "x", "platform": platform, "source": platform}) for platform in ("google_trends", "tiktok", "reddit", "amazon")]
    rows = [row for row in rows if row]
    assert score_candidate("x", rows).source_diversity == 1


def test_saturation_risk_is_scored():
    rows = [normalize_record({"candidate_id": "x", "platform": "meta", "ad_active_signal": True, "hook": "Same hook"}) for _ in range(3)]
    rows = [row for row in rows if row]
    assert score_candidate("x", rows).attention_saturation_risk > 0


def test_high_objection_risk_recommends_rejection():
    row = normalize_record({"candidate_id": "x", "platform": "reddit", "objection": "concern", "pain_point": "pain", "desired_outcome": "outcome"})
    assert row is not None
    assert score_candidate("x", [row]).recommendation == "reject_high_objection_risk"


def test_attention_without_supplier_proof_requires_validation():
    rows = import_json(fixture("tiktok_creative_center_snapshot.json"), platform="tiktok", source_type="tiktok_creative_center_snapshot")
    score = score_candidate(rows[0].candidate_id, rows)
    assert "consumer_attention_is_not_supplier_proof" in score.reasons
    assert score.recommendation in {"validate_supplier_first", "expand_consumer_research", "generate_creative_tests"}


def test_supplier_proof_is_explicit_input():
    row = normalize_record({"candidate_id": "x", "platform": "tiktok", "hook": "Demo", "search_growth_signal": 0.9, "ugc_scriptability": 0.9, "visual_demo_score": 0.9, "source_confidence": 1})
    assert row is not None
    without = score_candidate("x", [row], supplier_proof=False)
    with_proof = score_candidate("x", [row], supplier_proof=True)
    assert "supplier_proof_not_observed" in without.reasons
    assert "supplier_proof_not_observed" not in with_proof.reasons


def test_creative_angle_extraction_maps_keywords():
    row = normalize_record({"candidate_id": "x", "platform": "tiktok", "hook": "See the before and after demo", "desired_outcome": "travel convenience", "pain_point": "messy setup"})
    assert row is not None
    angles = extract_creative_angles([row])
    assert "before_after" in angles["recommended_ad_angles"]
    assert "demo" in angles["recommended_ad_angles"]


def test_creative_hooks_are_returned():
    row = normalize_record({"candidate_id": "x", "platform": "tiktok", "hook": "Stop carrying a full-size printer"})
    assert row is not None
    score = score_candidate("x", [row])
    assert score.creative_hooks[0].hook == "Stop carrying a full-size printer"


def test_voc_pain_outcome_objection_claim_proof_are_returned():
    row = normalize_record({"candidate_id": "x", "platform": "amazon", "pain_point": "mess", "desired_outcome": "clean home", "objection": "noise", "claim": "quiet", "proof_signal": "review repetition"})
    assert row is not None
    voc = score_candidate("x", [row]).voice_of_customer
    assert voc.pain_points == ("mess",)
    assert voc.desired_outcomes == ("clean home",)
    assert voc.objections == ("noise",)
    assert voc.claims == ("quiet",)
    assert voc.proof_signals == ("review repetition",)


def test_ugc_formats_are_recommended():
    row = normalize_record({"candidate_id": "x", "platform": "tiktok", "creative_format": "ugc_demo", "ugc_scriptability": 0.8})
    assert row is not None
    assert score_candidate("x", [row]).recommended_ugc_formats == ("ugc_demo",)


def test_landing_page_hints_use_desired_outcomes():
    row = normalize_record({"candidate_id": "x", "platform": "amazon", "desired_outcome": "quick labels"})
    assert row is not None
    assert "Lead with: quick labels" in score_candidate("x", [row]).landing_page_copy_hints


def test_creative_risks_include_objection_evidence():
    row = normalize_record({"candidate_id": "x", "platform": "reddit", "objection": "too loud"})
    assert row is not None
    assert "objection_evidence_present" in score_candidate("x", [row]).creative_risks


def test_duplicate_evidence_collapses():
    row = normalize_record({"candidate_id": "x", "platform": "tiktok", "source": "same", "content_title": "same", "hook": "h", "source_confidence": 0.5})
    better = normalize_record({"candidate_id": "x", "platform": "tiktok", "source": "same", "content_title": "same", "hook": "h", "source_confidence": 0.9, "view_count": 1000})
    assert row and better
    assert len(build_report([row, better]).to_dict()["candidates"][0]["evidence"]) == 1


def test_report_sorts_candidates_and_has_safety_flags():
    rows = import_json(fixture("tiktok_creative_center_snapshot.json"), platform="tiktok", source_type="tiktok_creative_center_snapshot")
    report = build_report(rows).to_dict()
    assert report["top_candidate_id"] == "mini-thermal-printer"
    assert report["read_only"] and not report["network_calls"] and not report["mutated"]


def test_empty_report_is_explicit():
    report = build_report([]).to_dict()
    assert report["candidate_count"] == 0
    assert report["next_best_action"] == "expand_consumer_research"
    assert report["warnings"] == ["consumer_attention_not_supplied"]


@pytest.mark.parametrize("value,expected", [("1.5K", 1500), ("2M", 2000000), ("$12.50", 12), ("", None)])
def test_import_metric_formats_are_deterministic(value, expected):
    row = normalize_record({"candidate_id": "x", "platform": "manual", "view_count": value})
    assert row is not None
    assert row.view_count == expected


@pytest.mark.parametrize("platform,source", [("google_trends", "fixture_demo"), ("amazon", "fixture_demo"), ("meta", "fixture_demo"), ("manual", "fixture_demo")])
def test_platform_defaults_map_to_safe_source_types(platform, source):
    row = normalize_record({"candidate_id": "x", "platform": platform})
    assert row is not None
    assert row.source_type == source


def test_unknown_source_type_degrades_to_fixture_demo():
    row = normalize_record({"candidate_id": "x", "platform": "manual", "source_type": "private_dashboard"})
    assert row is not None
    assert row.source_type == "manual_csv_import"


def test_field_provenance_unknown_value_is_marked_malformed():
    row = normalize_record({"candidate_id": "x", "platform": "manual", "field_provenance": {"hook": "invented"}, "hook": "Demo"})
    assert row is not None
    assert row.field_provenance["hook"] == "malformed"


def test_content_excerpt_is_bounded():
    row = normalize_record({"candidate_id": "x", "platform": "manual", "content_text_excerpt": "a" * 500})
    assert row is not None
    assert len(row.content_text_excerpt) == 240


def test_manual_mode_marks_observed_fields_manual_import():
    row = normalize_record({"candidate_id": "x", "platform": "reddit", "pain_point": "hard to clean"}, mode="manual_import")
    assert row is not None
    assert row.field_provenance["pain_point"] == "manual_import"


def test_source_confidence_is_bounded():
    high = normalize_record({"candidate_id": "x", "platform": "manual", "source_confidence": 4})
    low = normalize_record({"candidate_id": "y", "platform": "manual", "source_confidence": -1})
    assert high is not None and low is not None
    assert high.source_confidence == 1
    assert low.source_confidence == 0


def test_ad_metrics_create_ad_signal_summary():
    row = normalize_record({"candidate_id": "x", "platform": "meta", "ad_active_signal": True, "ad_platform": "meta", "creative_format": "video"})
    assert row is not None
    assert score_candidate("x", [row]).ad_signals[0].platform == "meta"


def test_search_metrics_create_search_signal_summary():
    row = normalize_record({"candidate_id": "x", "platform": "google_trends", "keyword": "portable blender", "search_growth_signal": 0.8, "keyword_intent": "buy"})
    assert row is not None
    assert score_candidate("x", [row]).search_signals[0].keyword_intent == "transactional"


def test_review_metrics_create_review_signal_summary():
    row = normalize_record({"candidate_id": "x", "platform": "amazon", "review_count": 400, "rating": 4.5, "sentiment": "positive"})
    assert row is not None
    assert score_candidate("x", [row]).review_signals[0].rating == 4.5


def test_creative_angle_fallback_is_problem_solution():
    row = normalize_record({"candidate_id": "x", "platform": "manual", "content_title": "Product"})
    assert row is not None
    assert extract_creative_angles([row])["recommended_ad_angles"] == ["problem_solution"]


def test_creative_angle_extracts_travel_and_demo():
    row = normalize_record({"candidate_id": "x", "platform": "tiktok", "hook": "Travel demo in seconds"})
    assert row is not None
    angles = extract_creative_angles([row])["recommended_ad_angles"]
    assert "travel_portability" in angles and "demo" in angles


def test_creative_risk_is_only_emitted_for_objections():
    clear = normalize_record({"candidate_id": "x", "platform": "manual", "hook": "Simple demo"})
    risky = normalize_record({"candidate_id": "y", "platform": "manual", "objection": "battery concern"})
    assert clear is not None and risky is not None
    assert extract_creative_angles([clear])["creative_risks"] == []
    assert extract_creative_angles([risky])["creative_risks"] == ["objection_evidence_present"]


def test_duplicate_selection_prefers_higher_confidence():
    first = normalize_record({"candidate_id": "x", "platform": "manual", "source": "same", "content_title": "same", "hook": "old", "source_confidence": 0.2})
    second = normalize_record({"candidate_id": "x", "platform": "manual", "source": "same", "content_title": "same", "hook": "new", "source_confidence": 0.9})
    assert first is not None and second is not None
    report = build_report([first, second]).to_dict()
    assert report["evidence_count"] == 1
    assert report["candidates"][0]["evidence"][0]["hook"] == "new"


def test_report_candidate_order_is_score_then_id():
    first = normalize_record({"candidate_id": "b", "platform": "google_trends", "search_growth_signal": 0.2})
    second = normalize_record({"candidate_id": "a", "platform": "google_trends", "search_growth_signal": 0.2})
    assert first is not None and second is not None
    report = build_report([first, second]).to_dict()
    assert [item["candidate_id"] for item in report["candidates"]] == ["a", "b"]
