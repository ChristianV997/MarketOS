"""Brief-driven product research runner — fixture/fake-client integration tests."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.commerce.brief_driven_research import (
    FakeAttentionClient,
    FakeMarketplaceClient,
    FakeSupplierClient,
    ResearchBrief,
    StatusOnlyClient,
    derive_queries,
    evaluate_authority_gates,
    render_markdown,
    run_brief_driven_research,
)

ROOT = Path(__file__).resolve().parents[1]


def _brief(**overrides) -> ResearchBrief:
    base = {
        "product_query": "portable espresso maker",
        "category": "kitchen appliances",
        "target_region": "US",
        "language": "en",
        "intended_buyer": "home baristas",
    }
    base.update(overrides)
    return ResearchBrief(**base)


def _success_clients(brief: ResearchBrief | None = None):
    brief = brief or _brief()
    queries = derive_queries(brief)
    market_rows = (
        {
            "candidate_id": queries.candidate_id,
            "query": queries.marketplace_query,
            "marketplace": "amazon",
            "source_type": "amazon_best_sellers_snapshot",
            "price": 49.0,
            "currency": "USD",
            "review_count": 220,
            "rating": 4.4,
            "rank_position": 8,
            "search_growth_signal": 0.5,
            "field_provenance": {"price": "fixture"},
        },
    )
    supplier_rows = (
        {
            "candidate_id": queries.candidate_id,
            "query": queries.supplier_query,
            "supplier": "cj",
            "source_type": "fixture_demo",
            "unit_cost": 12.0,
            "currency": "USD",
            "shipping_cost": 3.5,
            "shipping_currency": "USD",
            "inventory_quantity": 100,
            "inventory_status": "in_stock",
            "destination_region": brief.target_region,
            "field_provenance": {"unit_cost": "fixture", "shipping_cost": "fixture"},
        },
    )
    attention_rows = (
        {
            "candidate_id": queries.candidate_id,
            "query": queries.attention_query,
            "source": "fixture",
            "source_type": "tiktok_creative_center_snapshot",
            "platform": "tiktok",
            "hook": "Brew anywhere",
            "angle": "portability",
            "pain_point": "bulky machines",
            "view_count": 9000,
            "like_count": 700,
            "geography": brief.target_region,
            "language": brief.language,
        },
    )
    return (
        FakeMarketplaceClient(rows=market_rows),
        FakeSupplierClient(rows=supplier_rows),
        FakeAttentionClient(rows=attention_rows),
    )


def test_derive_queries_from_brief_without_urls_or_csvs():
    brief = _brief()
    queries = derive_queries(brief)
    assert queries.candidate_id == "portable-espresso-maker"
    assert "portable espresso maker" in queries.marketplace_query
    assert "supplier" in queries.supplier_query
    assert "home baristas" in queries.attention_query
    assert "no_manual_competitor_urls_required" in queries.notes


def test_happy_path_brief_to_synthesis_with_fake_clients():
    brief = _brief()
    market, supplier, attention = _success_clients(brief)
    report = run_brief_driven_research(
        brief,
        marketplace_client=market,
        supplier_client=supplier,
        attention_client=attention,
    )
    payload = report.to_dict()
    assert payload["execution_authorized"] is False
    assert payload["live_provider_calls"] is False
    assert payload["network_calls"] is False
    assert payload["source_outcomes"]["marketplace"]["status"] == "collected"
    assert payload["source_outcomes"]["supplier"]["status"] == "collected"
    assert payload["source_outcomes"]["consumer_attention"]["status"] == "collected"
    assert payload["synthesis"] is not None
    assert payload["synthesis"]["report_version"]
    assert payload["source_outcomes"]["marketplace"]["record_count"] >= 1
    assert "marketplace_listing_is_not_verified_demand" in payload["assumptions"]
    assert "consumer_attention_is_not_supplier_proof" in payload["assumptions"]
    assert payload["authority"]["provider_pull_authorized"] is False


def test_partial_failure_preserves_successful_sources():
    brief = _brief()
    market, supplier, _ = _success_clients(brief)
    report = run_brief_driven_research(
        brief,
        marketplace_client=market,
        supplier_client=supplier,
        attention_client=StatusOnlyClient("unavailable", "attention"),
    )
    outcomes = report.to_dict()["source_outcomes"]
    assert outcomes["marketplace"]["status"] == "collected"
    assert outcomes["supplier"]["status"] == "collected"
    assert outcomes["consumer_attention"]["status"] == "unavailable"
    assert outcomes["marketplace"]["report_present"] is True
    assert outcomes["consumer_attention"]["report_present"] is False
    assert outcomes["consumer_attention"]["empty_placeholder_report"] is True
    assert report.synthesis is not None
    assert "consumer_attention_status:unavailable" in report.limitations
    # Missing attention must not drop the 25% weight (would inflate marketplace/supplier).
    top = (report.synthesis or {}).get("candidates") or []
    if top:
        weights = top[0].get("score", {}).get("score_breakdown") or top[0].get("score", {})
        # combined uses consumer weight; raw consumer component stays at zero
        assert float(top[0]["score"].get("consumer_attention", 0)) == 0.0


def test_not_configured_and_disabled_by_policy_are_explicit():
    brief = _brief()
    report = run_brief_driven_research(
        brief,
        marketplace_client=StatusOnlyClient("not_configured", "marketplace"),
        supplier_client=StatusOnlyClient("disabled_by_policy", "supplier"),
        attention_client=StatusOnlyClient("quota_exhausted", "attention"),
    )
    outcomes = report.to_dict()["source_outcomes"]
    assert outcomes["marketplace"]["status"] == "not_configured"
    assert outcomes["supplier"]["status"] == "disabled_by_policy"
    assert outcomes["consumer_attention"]["status"] == "quota_exhausted"
    for outcome in outcomes.values():
        assert outcome["record_count"] == 0
        assert outcome["report_present"] is False
        assert outcome["empty_placeholder_report"] is True
        assert "missing_evidence_not_treated_as_zero_or_positive" in outcome["warnings"]


def test_timeout_handling():
    brief = _brief()
    market, supplier, attention = _success_clients(brief)
    market.sleep_s = 5.0
    report = run_brief_driven_research(
        brief,
        marketplace_client=market,
        supplier_client=supplier,
        attention_client=attention,
        timeout_s=0.05,
    )
    assert report.source_outcomes["marketplace"].status == "timed_out"
    assert report.source_outcomes["supplier"].status == "collected"
    assert report.source_outcomes["consumer_attention"].status == "collected"


def test_provenance_and_freshness_preserved():
    brief = _brief()
    market, supplier, attention = _success_clients(brief)
    report = run_brief_driven_research(
        brief,
        marketplace_client=market,
        supplier_client=supplier,
        attention_client=attention,
    )
    market_outcome = report.source_outcomes["marketplace"]
    assert "fake_marketplace_client" in market_outcome.provenance
    assert "normalize_record" in market_outcome.provenance
    assert market_outcome.freshness_label == "fixture_deterministic"
    assert market_outcome.evidence_mode in {"fixture_demo", "fixture"}


def test_mixed_currencies_are_not_converted():
    brief = _brief()
    queries = derive_queries(brief)
    market = FakeMarketplaceClient(
        rows=(
            {
                "candidate_id": queries.candidate_id,
                "query": queries.marketplace_query,
                "marketplace": "amazon",
                "source_type": "amazon_best_sellers_snapshot",
                "price": 40.0,
                "currency": "USD",
                "field_provenance": {"price": "fixture"},
            },
        )
    )
    supplier = FakeSupplierClient(
        rows=(
            {
                "candidate_id": queries.candidate_id,
                "query": queries.supplier_query,
                "supplier": "cj",
                "source_type": "fixture_demo",
                "unit_cost": 200.0,
                "currency": "MXN",
                "shipping_cost": 50.0,
                "shipping_currency": "MXN",
                "inventory_quantity": 10,
                "inventory_status": "in_stock",
                "field_provenance": {"unit_cost": "fixture", "shipping_cost": "fixture"},
            },
        )
    )
    report = run_brief_driven_research(
        brief,
        marketplace_client=market,
        supplier_client=supplier,
        attention_client=StatusOnlyClient("not_configured", "attention"),
    )
    joined = " ".join(report.currency_notes + report.assumptions)
    assert "currencies_are_not_converted" in joined
    assert "no_exchange_rate_invented" in joined
    assert "MXN" in joined and "USD" in joined
    assert "mixed_currencies" in joined
    assert "target_sell_prices_omitted_due_to_currency_mismatch" in joined


def test_missing_data_never_becomes_positive_evidence():
    brief = _brief()
    report = run_brief_driven_research(brief)  # default not_configured clients
    payload = report.to_dict()
    for outcome in payload["source_outcomes"].values():
        assert outcome["status"] == "not_configured"
        assert outcome["record_count"] == 0
        assert outcome["report_present"] is False
        assert outcome["empty_placeholder_report"] is True
    synthesis = payload["synthesis"]
    assert synthesis is not None
    # No invented favorable candidates from empty pillars.
    assert synthesis.get("candidate_count", len(synthesis.get("candidates", []))) == 0 or synthesis.get("candidates") == []


def test_missing_attention_keeps_three_pillar_weights():
    brief = _brief()
    market, supplier, _ = _success_clients(brief)
    with_attention = run_brief_driven_research(
        brief,
        marketplace_client=market,
        supplier_client=supplier,
        attention_client=_success_clients(brief)[2],
    )
    without_attention = run_brief_driven_research(
        brief,
        marketplace_client=market,
        supplier_client=supplier,
        attention_client=StatusOnlyClient("timed_out", "attention"),
    )
    scored = (without_attention.synthesis or {}).get("candidates") or []
    assert scored
    score = scored[0]["score"]
    assert score["consumer_attention"] == 0.0
    # Must not renormalize to marketplace 0.55 / supplier 0.45.
    expected = round(score["marketplace_opportunity"] * 0.4 + score["supplier_feasibility"] * 0.35 + 0.0, 4)
    assert score["combined_opportunity_score"] == expected
    assert with_attention.source_outcomes["consumer_attention"].status == "collected"


def test_allow_live_is_rejected():
    with pytest.raises(ValueError, match="live_provider_calls_disabled"):
        run_brief_driven_research(_brief(), allow_live=True, use_default_fixture_clients=True)


def test_authority_gate_blocks_provider_pull_authorization():
    gate = evaluate_authority_gates()
    assert gate.provider_pull_authorized is False
    assert "approval_ledger_simulation_is_not_live_authority" in gate.notes


def test_partial_status_keeps_records_and_labels_partial():
    brief = _brief()
    queries = derive_queries(brief)
    market = FakeMarketplaceClient(
        status="partial",
        rows=(
            {
                "candidate_id": queries.candidate_id,
                "query": queries.marketplace_query,
                "marketplace": "amazon",
                "source_type": "amazon_best_sellers_snapshot",
                "price": 20.0,
                "currency": "USD",
                "field_provenance": {"price": "fixture"},
            },
        ),
    )
    report = run_brief_driven_research(
        brief,
        marketplace_client=market,
        supplier_client=StatusOnlyClient("not_configured", "supplier"),
        attention_client=StatusOnlyClient("not_configured", "attention"),
    )
    assert report.source_outcomes["marketplace"].status == "partial"
    assert report.source_outcomes["marketplace"].record_count == 1


def test_markdown_and_cli_fixture_demo(tmp_path):
    brief = _brief()
    market, supplier, attention = _success_clients(brief)
    report = run_brief_driven_research(
        brief,
        marketplace_client=market,
        supplier_client=supplier,
        attention_client=attention,
    )
    md = render_markdown(report)
    assert "Brief-Driven Product Opportunity Research" in md
    assert "Source statuses" in md
    assert "Future approval" in md

    out = tmp_path / "out"
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_brief_driven_product_research.py"),
            "--product-query",
            "desk cable organizer",
            "--category",
            "office accessories",
            "--region",
            "US",
            "--language",
            "en",
            "--intended-buyer",
            "remote workers",
            "--use-fixture-demo",
            "--json",
            "--output",
            str(out),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["report_version"] == "brief-driven-product-research-v1"
    assert payload["execution_authorized"] is False
    assert (out / "brief_driven_research_report.json").is_file()
    assert (out / "brief_driven_research_report.md").is_file()


def test_brief_validation_requires_core_fields():
    with pytest.raises(ValueError):
        ResearchBrief(
            product_query="",
            category="x",
            target_region="US",
            language="en",
            intended_buyer="buyer",
        )
