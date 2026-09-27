from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend.adapters.research.consumer_attention import normalize_record
from evaluation.commerce.consumer_attention import (
    ConsumerAttentionEvidence,
    build_report,
    score_candidate,
)


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "run_consumer_attention_intelligence.py"


def payload(**overrides):
    value = {
        "candidate_id": "candidate-neutral",
        "query": "customer outcome",
        "source": "manual-notes",
        "source_type": "manual_csv_import",
        "platform": "manual",
        "offering_kind": "unknown",
        "observed_at": "2026-09-01T00:00:00Z",
        "hook": "Explain the outcome",
        "pain_point": "slow handoff",
        "desired_outcome": "clear completion",
        "source_confidence": 0.75,
    }
    value.update(overrides)
    return value


def record(**overrides):
    result = normalize_record(payload(**overrides), mode="fixture")
    assert result is not None
    return result


@pytest.mark.parametrize("kind", ["goods", "service", "hybrid", "unknown"])
def test_offering_kind_matrix_is_explicit(kind):
    item = record(offering_kind=kind)
    report = build_report([item], as_of="2026-09-10T00:00:00Z").to_dict()
    assert report["offering_kinds"] == [kind]
    assert report["candidates"][0]["offering_kinds"] == [kind]


@pytest.mark.parametrize("kind", ["product", "subscription", "live", "launch"])
def test_unsupported_offering_kind_is_unavailable(kind):
    assert normalize_record(payload(offering_kind=kind), mode="fixture") is None


@pytest.mark.parametrize("language", ["english", "en_US", "e", "es-", "中文"])
def test_unsupported_language_is_unavailable(language):
    assert normalize_record(payload(language=language), mode="fixture") is None


@pytest.mark.parametrize("geography", ["MX\nUS", "MX\x00", {"country": "MX"}, ["MX"]])
def test_unsafe_geography_is_unavailable(geography):
    assert normalize_record(payload(geography=geography), mode="fixture") is None


@pytest.mark.parametrize("field", ["candidate_id", "observation_key", "observation_value"])
def test_identifier_controls_are_rejected_at_import_boundary(field):
    value = payload(observation_key="demand", observation_value="high")
    value[field] = "unsafe\x00value"
    assert normalize_record(value, mode="fixture") is None


@pytest.mark.parametrize(
    "secret_key",
    ["api_key", "access_token", "password", "authorization", "private_key", "cookie"],
)
def test_nested_secret_keys_are_dropped(secret_key):
    value = payload(content={secret_key: "fixture-secret"})
    assert normalize_record(value, mode="fixture") is None


@pytest.mark.parametrize("secret_value", ["Bearer fixture", "sk_live_fixture", "ghp_fixture", "-----BEGIN " + "PRIVATE KEY-----"])
def test_secret_shaped_values_are_dropped(secret_value):
    assert normalize_record(payload(content_text_excerpt=secret_value), mode="fixture") is None


@pytest.mark.parametrize("raw_field", ["raw_html", "raw_payload", "provider_payload"])
def test_raw_provider_payloads_are_dropped(raw_field):
    value = payload()
    value[raw_field] = "<html><body>fixture provider response</body></html>"
    assert normalize_record(value, mode="fixture") is None


def test_raw_html_excerpt_is_not_retained():
    assert normalize_record(payload(content_text_excerpt="<div>provider payload</div>"), mode="fixture") is None


def test_numeric_text_is_parsed_without_silent_character_stripping():
    item = normalize_record(payload(search_growth_signal="1e2"), mode="fixture")

    assert item is not None
    assert item.search_growth_signal == 100


def test_field_provenance_is_not_a_live_authority():
    value = payload(field_provenance={"hook": "live"})
    item = normalize_record(value, mode="fixture")
    assert item is not None
    assert item.field_provenance["hook"] == "malformed"
    assert item.evidence_mode == "fixture"


def test_direct_model_rejects_unsafe_provenance_and_mutation_flags():
    with pytest.raises(ValueError, match="provenance"):
        ConsumerAttentionEvidence("candidate", "query", "source", "fixture_demo", field_provenance={"hook": "live"})
    with pytest.raises(ValueError, match="offline"):
        ConsumerAttentionEvidence("candidate", "query", "source", "fixture_demo", network_calls=True)


def test_candidate_labels_do_not_change_identical_evidence_score():
    left = record(candidate_id="alpha-label")
    right = record(candidate_id="zulu-label")
    left_score = build_report([left], as_of="2026-09-10T00:00:00Z").to_dict()["candidates"][0]["score"]
    right_score = build_report([right], as_of="2026-09-10T00:00:00Z").to_dict()["candidates"][0]["score"]
    assert {key: value for key, value in left_score.items() if key != "candidate_id"} == {key: value for key, value in right_score.items() if key != "candidate_id"}


def test_explicit_supplier_proof_is_not_inferred_from_attention_rows():
    item = record()
    report = build_report([item], as_of="2026-09-10T00:00:00Z").to_dict()
    score = report["candidates"][0]["score"]
    assert "supplier_proof_not_observed" in score["reasons"]
    assert "advance_to_launch_draft" not in score["recommendation"]


def test_attention_never_authorizes_launch_even_when_supplier_proof_is_supplied():
    common = {
        "engagement_count": 100000,
        "view_count": 100000,
        "like_count": 100000,
        "comment_count": 1000,
        "share_count": 1000,
        "review_count": 1000,
        "search_growth_signal": 1,
        "ad_active_signal": True,
        "ad_platform": "meta",
        "ugc_scriptability": 1,
        "visual_demo_score": 1,
        "intent": "transactional",
        "source_confidence": 0.95,
    }
    items = [
        record(platform="youtube", hook="Solve the problem", **common),
        record(platform="tiktok", hook="Show the transformation", **common),
        record(platform="meta", hook="Make the outcome giftable", **common),
        record(platform="amazon", hook="Explain the messy handoff", **common),
    ]

    score = score_candidate("candidate-neutral", items, supplier_proof=True)

    assert score.overall_consumer_attention >= 0.7
    assert score.recommendation == "manual_review_required"
    assert "advance_to_launch_draft" not in score.recommendation


def test_quality_blocker_overrides_attractive_attention_score():
    item = record(
        engagement_count=100000,
        view_count=100000,
        search_growth_signal=1,
        review_count=1000,
        hook="Show the outcome",
    )
    score = score_candidate("candidate-neutral", [item], quality_blockers=("conflicting_consumer_observations",))
    assert score.overall_consumer_attention > 0
    assert score.recommendation == "reject_low_attention"
    assert "conflicting_consumer_observations" in score.reasons


def test_explicit_zero_engagement_count_is_not_replaced_by_a_derived_sum():
    """A caller who confirmed zero direct engagement events must get a low
    social_engagement_signal -- not the same score as an unknown
    engagement_count, which falls back to a like/comment/share proxy."""
    common = dict(candidate_id="c1", query="q", source="s", source_type="fixture_demo", view_count=1000, like_count=500, comment_count=200, share_count=100)
    zero = ConsumerAttentionEvidence(**common, engagement_count=0)
    missing = ConsumerAttentionEvidence(**common)
    zero_score = score_candidate("c1", [zero]).social_engagement_signal
    missing_score = score_candidate("c1", [missing]).social_engagement_signal
    assert zero_score == 0.0
    assert missing_score > zero_score


def test_explicit_zero_view_count_is_not_replaced_by_the_unknown_default():
    """A caller who confirmed zero views (denominator max(1, 0) == 1) must
    score differently from an unknown view_count (denominator 10000)."""
    zero = ConsumerAttentionEvidence(candidate_id="c1", query="q", source="s", source_type="fixture_demo", engagement_count=50, view_count=0)
    missing = ConsumerAttentionEvidence(candidate_id="c1", query="q", source="s", source_type="fixture_demo", engagement_count=50)
    zero_score = score_candidate("c1", [zero]).social_engagement_signal
    missing_score = score_candidate("c1", [missing]).social_engagement_signal
    assert zero_score == 1.0
    assert missing_score < zero_score


def test_report_json_round_trip_is_deterministic():
    report = build_report([record()], evidence_mode="fixture_demo", as_of="2026-09-10T00:00:00Z").to_dict()
    first = json.dumps(report, sort_keys=True, separators=(",", ":"))
    second = json.dumps(json.loads(first), sort_keys=True, separators=(",", ":"))
    assert first == second


def test_cli_output_summary_keeps_metadata_and_safety_flags(tmp_path):
    output = tmp_path / "consumer-output"
    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--candidate-seed",
            str(ROOT / "tests/fixtures/consumer_attention/service_market_generic.json"),
            "--as-of",
            "2026-09-10T00:00:00Z",
            "--output",
            str(output),
            "--json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    stdout = json.loads(result.stdout)
    summary = json.loads((output / "consumer_source_summary.json").read_text(encoding="utf8"))
    assert summary["freshness_status"] == stdout["freshness_status"] == "fresh"
    assert summary["offering_kinds"] == ["hybrid", "service"]
    assert summary["read_only"] is True
    assert summary["network_calls"] is False
    assert summary["mutated"] is False


def test_cli_bad_freshness_window_fails_without_writing_output(tmp_path):
    output = tmp_path / "should-not-exist"
    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--candidate-seed",
            str(ROOT / "tests/fixtures/consumer_attention/service_market_generic.json"),
            "--freshness-days",
            "0",
            "--output",
            str(output),
            "--json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "freshness-days must be positive" in result.stderr
    assert not output.exists()
