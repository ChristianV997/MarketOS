from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from evaluation.commerce.consumer_attention import ConsumerAttentionEvidence
from evaluation.commerce.consumer_attention_insights import (
    build_consumer_attention_insights,
    questions_for_opportunity,
    signal_family,
)
from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis
from evaluation.commerce.product_validation_report import generate


def _row(**overrides) -> ConsumerAttentionEvidence:
    payload = {
        "candidate_id": "fixture-lamp",
        "query": "portable lamp",
        "source": "fixture source",
        "source_type": "google_trends_fixture",
        "platform": "google_trends",
        "keyword": "portable lamp",
        "search_growth_signal": 0.4,
        "trend_label": "rising",
        "evidence_mode": "fixture",
        "source_confidence": 0.5,
    }
    payload.update(overrides)
    return ConsumerAttentionEvidence(**payload)


def test_search_ads_and_reviews_stay_separate_and_are_not_purchase_intent():
    records = [
        _row(observed_at="2026-09-01T00:00:00Z", geography="MX", language="es"),
        _row(
            source="Meta Ad Library snapshot",
            source_type="meta_ad_library_snapshot",
            platform="meta",
            hook="A five-minute setup",
            ad_active_signal=True,
            ad_platform="meta",
            engagement_count=1200,
            observed_at="2026-09-02T00:00:00Z",
            geography="MX",
            language="es",
        ),
        _row(
            source="Amazon reviews snapshot",
            source_type="amazon_reviews_snapshot",
            platform="amazon",
            pain_point="battery fades quickly",
            objection="battery life",
            review_count=40,
            observed_at="2026-09-03T00:00:00Z",
            geography="MX",
            language="es",
        ),
    ]

    report = build_consumer_attention_insights(records, as_of="2026-09-10T00:00:00Z")
    body = json.dumps(report.to_dict())

    assert signal_family(records[0]) == "search_trend"
    assert signal_family(records[1]) == "ad_library"
    assert signal_family(records[2]) == "review"
    assert report.signal_families == ("ad_library", "review", "search_trend")
    assert {item.signal_family for item in report.demand_themes} == {"ad_library", "review", "search_trend"}
    assert report.authority["purchase_intent"] is False
    assert report.authority["supplier_proof"] is False
    assert report.authority["opportunity_rescore"] is False
    assert "engagement_count_is_not_purchase_intent" in report.warnings
    assert "customers will buy" not in body
    assert "supplier verified" not in body
    assert all(item.aggregate_counts["interpretation"].endswith("not_purchase_intent_or_supplier_proof") for item in report.demand_themes)
    assert any(item.aggregate_counts["engagement_count"] == 1200 for item in report.demand_themes)


def test_stale_conflicting_missing_context_duplicate_and_unsupported_claims():
    records = [
        _row(observed_at="2025-01-01T00:00:00Z", observation_key="trend", observation_value="rising"),
        _row(
            source="second trends import",
            observed_at="2026-09-01T00:00:00Z",
            observation_key="trend",
            observation_value="falling",
            geography="MX",
        ),
        _row(source="duplicate trends import", observed_at="2026-09-01T00:00:00Z", content_title="same title"),
        _row(source="duplicate trends import", observed_at="2026-09-01T00:00:00Z", content_title="same title"),
        _row(
            source="Amazon reviews snapshot",
            source_type="amazon_reviews_snapshot",
            platform="amazon",
            objection="app setup friction",
            claim="proven demand and supplier verified",
            review_count=12,
        ),
    ]

    report = build_consumer_attention_insights(records, as_of="2026-09-10T00:00:00Z")
    blob = json.dumps(report.to_dict())

    assert "conflicting_consumer_observations" in report.warnings
    assert any("conflicting_observation:trend" in item.contradictions for item in report.demand_themes)
    assert any("stale_observation" in item.uncertainty for item in report.demand_themes)
    assert any("geography_missing" in item.uncertainty for item in report.audience_hints)
    assert any("observation_time_missing" in item.uncertainty for item in report.audience_hints)
    assert any(note.startswith("duplicate_source:") for item in report.demand_themes for note in item.uncertainty)
    assert any(item.unsupported_claims for item in report.product_questions)
    assert "proven demand" not in blob
    assert "supplier verified" not in blob
    assert any("Which market" in item.statement for item in report.product_questions)
    assert any("stale" in item.statement.lower() for item in report.product_questions)


def test_missing_evidence_fails_closed_without_inventing_demand():
    report = build_consumer_attention_insights([])

    assert report.evidence_count == 0
    assert report.demand_themes == ()
    assert report.product_questions == ()
    assert "consumer_attention_insights_not_supplied" in report.warnings


def test_opportunity_workflow_receives_questions_without_rescoring():
    records = [
        _row(geography="MX", language="es-MX", observed_at="2026-09-01T00:00:00Z"),
        _row(
            source="Amazon reviews snapshot",
            source_type="amazon_reviews_snapshot",
            platform="amazon",
            objection="battery life",
            review_count=8,
            geography="MX",
            language="es-MX",
            observed_at="2026-09-01T00:00:00Z",
        ),
    ]
    insights = build_consumer_attention_insights(records, as_of="2026-09-10T00:00:00Z").to_dict()
    consumer = {
        "evidence_mode": "fixture",
        "candidates": [{
            "candidate_id": "fixture-lamp",
            "query": "portable lamp",
            "score": {
                "overall_consumer_attention": 0.2,
                "recommendation": "expand_consumer_research",
                "voice_of_customer": {"pain_points": [], "objections": ["battery life"]},
            },
        }],
    }
    market = {"evidence_mode": "fixture", "candidates": [{"candidate_id": "fixture-lamp", "query": "portable lamp", "score": {"overall_marketplace_opportunity": 0.4}}]}

    plain = build_product_opportunity_synthesis(market, None, consumer)
    attached = build_product_opportunity_synthesis(market, None, consumer, consumer_insights=insights)

    assert plain.overall_recommendation == attached.overall_recommendation
    assert plain.combined_opportunity_score == attached.combined_opportunity_score
    assert attached.consumer_attention_insights["status"] == "supplied"
    assert attached.consumer_attention_insights["authority"]["opportunity_rescore"] is False
    assert questions_for_opportunity(insights)
    assert "Attention questions:" in attached.operator_summary
    validation = generate(consumer_insights=insights)
    assert any("opportunity review" in item or "Which market" in item or "objection" in item.lower() for item in validation.open_questions)
    assert validation.operator_disclaimer.startswith("This report is validation guidance")


def test_cli_prints_operator_json_without_writing_by_default(tmp_path):
    payload = json.dumps([_row().to_dict()])
    completed = subprocess.run(
        [sys.executable, "scripts/run_consumer_attention_insights.py", "--as-of", "2026-09-10T00:00:00Z"],
        input=payload,
        text=True,
        capture_output=True,
        cwd=Path(__file__).parents[1],
        env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": str(Path(__file__).parents[1])},
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["authority"]["purchase_intent"] is False
    assert report["demand_themes"]
    assert not list(tmp_path.iterdir())
