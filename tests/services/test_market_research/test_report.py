"""services.market_research — no mocks. Every test drives the real
build_product_opportunity_synthesis fusion authority through
build_market_research_report; none re-implement or bypass it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.market_research import (
    MarketResearchRequest,
    build_market_research_report,
    render_market_research_markdown,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "market_research"

_MARKETPLACE = {
    "evidence_mode": "sanitized_report",
    "marketplaces_observed": ["ebay", "amazon"],
    "candidates": [{"candidate_id": "c1", "title": "Widget", "score": {"overall_marketplace_opportunity": 0.7, "saturation_score": 0.4}}],
}
_SUPPLIER = {
    "evidence_mode": "sanitized_report",
    "candidates": [{
        "candidate_id": "c1",
        "assumptions": ["shipping_cost_missing"],
        "score": {"overall_supplier_feasibility": 0.6, "recommendation": "validate_live_supplier_first", "risk_flags": [], "economics": {"gross_margin_percent": 0.3}},
    }],
}
_SUPPLIER_WITH_SHIPPING = {
    "evidence_mode": "sanitized_report",
    "candidates": [{
        "candidate_id": "c1",
        "score": {"overall_supplier_feasibility": 0.7, "recommendation": "validate_live_supplier_first", "risk_flags": [], "economics": {"gross_margin_percent": 0.35, "shipping_cost": 4.5, "shipping_speed_score": 0.6, "moq": 50}},
    }],
}
_CONSUMER = {
    "evidence_mode": "sanitized_report",
    "platforms_observed": ["tiktok"],
    "candidates": [{"candidate_id": "c1", "score": {"overall_consumer_attention": 0.65, "recommendation": "expand_consumer_research", "voice_of_customer": {}}}],
}


def _request(**overrides) -> MarketResearchRequest:
    base = dict(candidate_id="c1", offering_kind="goods", geography="MX", language="es", as_of="2026-09-22")
    base.update(overrides)
    return MarketResearchRequest(**base)


# ---------------------------------------------------------------------------
# offering_kind support
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("offering_kind,expected,recognized", [
    ("goods", "goods", True),
    ("service", "service", True),
    ("hybrid", "hybrid", True),
    ("unknown", "unknown", True),
    ("digital_download", "unknown", False),
    ("", "unknown", True),
])
def test_offering_kind_is_recognized_or_fails_closed(offering_kind, expected, recognized):
    result = build_market_research_report(_request(offering_kind=offering_kind, marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER, consumer_report=_CONSUMER))
    assert result.offering_kind == expected
    assert result.offering_kind_recognized is recognized
    if not recognized:
        assert any("was not recognized" in item for item in result.limitations)


def test_service_and_hybrid_offerings_still_compose_the_same_evidence():
    """This service never branches its composition logic on offering_kind
    for goods/service/hybrid -- it passes the raw evidence pillars through
    to the one existing fusion authority unchanged, and only surfaces
    offering_kind as metadata plus a follow-up-module hint. No
    product-specific branch exists in this module for any offering kind."""
    goods = build_market_research_report(_request(offering_kind="goods", marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER, consumer_report=_CONSUMER))
    service = build_market_research_report(_request(offering_kind="service", marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER, consumer_report=_CONSUMER))
    assert goods.executive_summary == service.executive_summary
    assert goods.blockers == service.blockers
    assert "service_delivery_feasibility_when_a_canonical_evaluator_exists" in service.follow_up_modules
    assert "service_delivery_feasibility_when_a_canonical_evaluator_exists" not in goods.follow_up_modules


# ---------------------------------------------------------------------------
# missing evidence -- never defaulted to a positive or "clear" result
# ---------------------------------------------------------------------------


def test_all_pillars_missing_is_reported_as_missing_everywhere_not_guessed():
    result = build_market_research_report(_request())
    assert {row.pillar: row.status for row in result.evidence_matrix} == {
        "marketplace": "missing",
        "supplier": "missing",
        "consumer_attention": "missing",
        "public_market_benchmark": "missing",
        "product_validation": "missing",
    }
    assert result.demand_and_customer_evidence["status"] == "consumer_attention_not_supplied"
    assert result.competitor_and_substitute_evidence["status"] == "marketplace_trends_not_supplied"
    assert result.supplier_feasibility["status"] == "supplier_feasibility_not_relevant_or_not_supplied"
    assert result.executive_summary["overall_recommendation"] != "advance_to_launch_draft"


def test_missing_shipping_cost_is_reported_as_missing_never_as_zero():
    result = build_market_research_report(_request(supplier_report=_SUPPLIER))
    assert result.delivery_and_logistics_feasibility["shipping_cost"] == "missing"
    assert result.delivery_and_logistics_feasibility["shipping_cost"] != 0
    assert "note" in result.delivery_and_logistics_feasibility


def test_supplied_shipping_cost_is_reported_as_the_real_number():
    result = build_market_research_report(_request(supplier_report=_SUPPLIER_WITH_SHIPPING))
    assert result.delivery_and_logistics_feasibility["shipping_cost"] == 4.5


def test_explicit_null_moq_and_shipping_speed_are_reported_as_missing_not_none():
    """An explicit `null` in the input economics dict must render the same
    'missing' sentinel as an absent key -- not a raw None/JSON null, which
    would be a different, inconsistent 'missing' representation."""
    supplier = {
        "evidence_mode": "sanitized_report",
        "candidates": [{
            "candidate_id": "c1", "query": "q",
            "offers": [{"supplier": "s", "shipping_cost": 4.5}],
            "score": {
                "overall_supplier_feasibility": 0.6,
                "economics": {"shipping_cost": 4.5, "moq": None, "shipping_speed_score": None},
            },
        }],
    }
    result = build_market_research_report(_request(supplier_report=supplier))
    assert result.delivery_and_logistics_feasibility["moq"] == "missing"
    assert result.delivery_and_logistics_feasibility["shipping_speed_score"] == "missing"


# ---------------------------------------------------------------------------
# never treat attention as supplier proof, trends as launch authorization,
# supplier claims as validation, or fixture/manual evidence as live proof
# ---------------------------------------------------------------------------


def test_consumer_attention_is_explicitly_never_supplier_proof():
    result = build_market_research_report(_request(consumer_report=_CONSUMER))
    assert result.demand_and_customer_evidence["warning"] == "consumer_attention_is_not_supplier_proof"
    assert any("attention_is_not_supplier_proof" in item for item in result.limitations)


def test_marketplace_trends_are_explicitly_never_launch_authorization():
    result = build_market_research_report(_request(marketplace_report=_MARKETPLACE))
    assert "not_launch_authorization" in result.competitor_and_substitute_evidence["warning"]
    assert any("trends_are_not_launch_authorization" in item for item in result.limitations)


def test_supplier_claim_is_explicitly_never_validation():
    result = build_market_research_report(_request(supplier_report=_SUPPLIER))
    assert "is_not_validation" in result.supplier_feasibility["warning"]


@pytest.mark.parametrize("evidence_mode", ["fixture", "fixture_demo", "manual_import", "manual"])
def test_fixture_and_manual_evidence_modes_are_flagged_never_silently_treated_as_live(evidence_mode):
    marketplace = {**_MARKETPLACE, "evidence_mode": evidence_mode}
    result = build_market_research_report(_request(marketplace_report=marketplace))
    row = next(r for r in result.evidence_matrix if r.pillar == "marketplace")
    assert row.status == "supplied"
    assert any(f"not_live_proof" in note for note in row.notes)


def test_never_reports_compliant_or_launch_authorized_language_anywhere():
    """Negative control: no field of the composed report, and no line of
    its rendered markdown, ever claims a product/service is compliant,
    validated, or launch-authorized -- this service has no authority to
    say so."""
    result = build_market_research_report(_request(marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER, consumer_report=_CONSUMER))
    blob = json.dumps(result.to_dict()).lower()
    for forbidden in ("is_compliant", "launch_authorized", "certified_compliant", "guaranteed_profit"):
        assert forbidden not in blob
    md = render_market_research_markdown(result).lower()
    for forbidden in ("is compliant", "launch authorized", "certified compliant", "guaranteed profit"):
        assert forbidden not in md


# ---------------------------------------------------------------------------
# freshness / stale / future evidence (fixture-driven)
# ---------------------------------------------------------------------------


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_stale_evidence_is_flagged_via_the_stale_and_future_fixture():
    fixture = _load_fixture("stale_and_future.json")
    result = build_market_research_report(MarketResearchRequest(
        candidate_id="stale-1", as_of=fixture["as_of"], marketplace_report=fixture["stale_marketplace_report"],
    ))
    row = next(r for r in result.evidence_matrix if r.pillar == "marketplace")
    assert row.status == "stale"
    assert any("exceeds" in note for note in row.notes)


def test_future_dated_evidence_is_flagged_via_the_stale_and_future_fixture():
    fixture = _load_fixture("stale_and_future.json")
    result = build_market_research_report(MarketResearchRequest(
        candidate_id="future-1", as_of=fixture["as_of"], marketplace_report=fixture["future_marketplace_report"],
    ))
    row = next(r for r in result.evidence_matrix if r.pillar == "marketplace")
    assert row.status == "future"
    assert any("after_as_of" in note for note in row.notes)


def test_evidence_within_the_freshness_window_is_supplied_not_stale():
    result = build_market_research_report(_request(marketplace_report=_MARKETPLACE))
    # _MARKETPLACE's candidate has no observed_at at all -- absent, not stale.
    row = next(r for r in result.evidence_matrix if r.pillar == "marketplace")
    assert row.status == "supplied"


# ---------------------------------------------------------------------------
# source conflicts -- surfaced from the existing alias-collision detector,
# never recomputed by this service
# ---------------------------------------------------------------------------


def test_conflicting_evidence_is_surfaced_via_the_conflict_fixture():
    fixture = _load_fixture("conflict.json")
    result = build_market_research_report(MarketResearchRequest(candidate_id="conflict-a", marketplace_report=fixture["marketplace_report"]))
    assert result.source_conflicts, "the conflicting-score alias note from opportunity_synthesis must surface here"
    assert any("conflicting scores" in note for note in result.source_conflicts)


# ---------------------------------------------------------------------------
# provenance / assumptions vs facts / confidence / next action / plan
# ---------------------------------------------------------------------------


def test_assumptions_and_observed_facts_are_kept_distinct():
    result = build_market_research_report(_request(marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER, consumer_report=_CONSUMER))
    assert "shipping_cost_missing" in result.assumptions
    assert "ebay" in result.observed_facts or "amazon" in result.observed_facts
    assert set(result.assumptions).isdisjoint(result.observed_facts)


def test_one_prioritized_next_action_is_always_a_single_string():
    result = build_market_research_report(_request())
    assert isinstance(result.next_action, str) and result.next_action


def test_bounded_validation_plan_is_never_empty():
    result = build_market_research_report(_request())
    assert len(result.validation_plan) >= 1
    result_with_evidence = build_market_research_report(_request(marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER, consumer_report=_CONSUMER))
    assert len(result_with_evidence.validation_plan) >= 1


def test_follow_up_modules_name_only_missing_pillars():
    result = build_market_research_report(_request(marketplace_report=_MARKETPLACE))
    assert "supplier_feasibility" in result.follow_up_modules
    assert "consumer_attention" in result.follow_up_modules
    assert "public_market_benchmark" in result.follow_up_modules


# ---------------------------------------------------------------------------
# geography / language / provenance pass-through
# ---------------------------------------------------------------------------


def test_geography_and_language_are_preserved_verbatim():
    result = build_market_research_report(_request(geography="CA", language="fr"))
    assert result.geography == "CA"
    assert result.language == "fr"


# ---------------------------------------------------------------------------
# deterministic fingerprint
# ---------------------------------------------------------------------------


def test_fingerprint_is_stable_for_identical_input():
    r1 = build_market_research_report(_request(marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER, consumer_report=_CONSUMER))
    r2 = build_market_research_report(_request(marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER, consumer_report=_CONSUMER))
    assert r1.fingerprint == r2.fingerprint
    assert len(r1.fingerprint) == 64


def test_fingerprint_changes_when_evidence_changes():
    r1 = build_market_research_report(_request(marketplace_report=_MARKETPLACE))
    r2 = build_market_research_report(_request(marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER))
    assert r1.fingerprint != r2.fingerprint


def test_fingerprint_is_independent_of_generated_at():
    r1 = build_market_research_report(_request(marketplace_report=_MARKETPLACE))
    import time

    time.sleep(0.01)
    r2 = build_market_research_report(_request(marketplace_report=_MARKETPLACE))
    assert r1.generated_at != r2.generated_at
    assert r1.fingerprint == r2.fingerprint


# ---------------------------------------------------------------------------
# markdown / JSON report completeness (consulting-ready)
# ---------------------------------------------------------------------------


def test_markdown_report_contains_every_required_section():
    result = build_market_research_report(_request(marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER, consumer_report=_CONSUMER))
    md = render_market_research_markdown(result)
    for heading in (
        "Executive Decision Summary", "Evidence Matrix", "Demand & Customer Evidence",
        "Competitor & Substitute Evidence", "Marketplace & Public-Market Signals",
        "Supplier Feasibility", "Delivery & Logistics Feasibility",
        "Pricing & Willingness-to-Pay Hypotheses", "Assumptions (not yet observed)",
        "Observed Facts", "Source Conflicts", "Confidence & Limitations",
        "Blockers", "Risks", "Prioritized Next Action", "Bounded Validation Plan",
        "Optional Follow-Up Modules", "Report Fingerprint", "Disclaimer",
    ):
        assert f"## {heading}" in md, heading


def test_json_report_is_json_safe_and_complete():
    result = build_market_research_report(_request(marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER, consumer_report=_CONSUMER))
    blob = json.dumps(result.to_dict())
    parsed = json.loads(blob)
    assert parsed["candidate_id"] == "c1"
    assert parsed["read_only"] is True
    assert parsed["network_calls"] is False
    assert parsed["mutated"] is False


def test_report_is_read_only_and_never_claims_network_calls():
    result = build_market_research_report(_request(marketplace_report=_MARKETPLACE))
    assert result.read_only is True
    assert result.network_calls is False
    assert result.mutated is False
    assert result.dry_run is True


# ---------------------------------------------------------------------------
# integrated evidence-authority contract
# ---------------------------------------------------------------------------


def _bound_request(**overrides) -> MarketResearchRequest:
    base = dict(
        candidate_id="c1",
        workspace_id="workspace-1",
        offering_kind="goods",
        geography="MX",
        language="es",
        as_of="2026-09-22",
    )
    base.update(overrides)
    return MarketResearchRequest(**base)


def test_integrated_report_exposes_one_bound_evidence_contract():
    result = build_market_research_report(_bound_request(
        marketplace_report=_MARKETPLACE,
        supplier_report=_SUPPLIER_WITH_SHIPPING,
        consumer_report=_CONSUMER,
    ))

    payload = result.to_dict()
    assert payload["candidate_id"] == "c1"
    assert payload["workspace_id"] == "workspace-1"
    assert payload["observation_source_identity"]
    assert payload["source_provenance"]
    assert payload["freshness"]
    assert payload["evidence_class"] == "sanitized_report"
    assert payload["client_safe_export_status"] == "ready_for_trustos_review"
    assert payload["client_safe_projection"]["live_proof"] is False
    assert payload["client_safe_projection"]["external_actions_authorized"] is False


def test_integrated_report_does_not_turn_absent_score_into_zero():
    result = build_market_research_report(_bound_request())

    assert result.executive_summary["combined_opportunity_score"] == "missing"
    assert result.evidence_class == "missing"
    assert result.missing_data


def test_cross_pillar_conflict_is_distinct_from_alias_notes():
    supplier = {
        "evidence_mode": "sanitized_report",
        "candidates": [{
            "candidate_id": "c1",
            "offers": [{"supplier": "supplier-a", "shipping_cost": 4.5}],
            "score": {"overall_supplier_feasibility": 0.6},
        }],
    }
    public_market = {
        "evidence_mode": "sanitized_report",
        "candidate_results": [{
            "candidate_id": "c1",
            "evidence": [{"source_domain": "example.com", "shipping_cost": 6.0}],
        }],
    }
    result = build_market_research_report(_bound_request(
        supplier_report=supplier,
        public_market_benchmark_report=public_market,
    ))

    assert result.conflict_findings
    assert any(item["field"] == "shipping_cost" for item in result.conflict_findings)
    assert result.blockers.count("evidence_conflict") == 1
    assert result.client_safe_export_status == "ready_for_trustos_review"


def test_missing_and_explicit_zero_shipping_remain_distinct():
    missing = build_market_research_report(_bound_request(supplier_report=_SUPPLIER))
    explicit_zero = {
        **_SUPPLIER_WITH_SHIPPING,
        "candidates": [{
            **_SUPPLIER_WITH_SHIPPING["candidates"][0],
            "offers": [{"supplier": "supplier-a", "shipping_cost": 0}],
            "score": {
                **_SUPPLIER_WITH_SHIPPING["candidates"][0]["score"],
                "economics": {"shipping_cost": 0},
            },
        }],
    }
    supplied_zero = build_market_research_report(_bound_request(supplier_report=explicit_zero))

    assert "supplier.shipping_cost" in missing.missing_data
    assert missing.delivery_and_logistics_feasibility["shipping_cost"] == "missing"
    assert supplied_zero.delivery_and_logistics_feasibility["shipping_cost"] == 0
    assert "supplier.shipping_cost" not in supplied_zero.missing_data


def test_stale_and_future_evidence_block_integrated_report():
    stale = {
        "evidence_mode": "sanitized_report",
        "candidates": [{"candidate_id": "c1", "observed_at": "2024-01-01", "score": {"overall_marketplace_opportunity": 0.7}}],
    }
    future = {
        "evidence_mode": "sanitized_report",
        "candidates": [{"candidate_id": "c1", "observed_at": "2027-01-01", "score": {"overall_marketplace_opportunity": 0.7}}],
    }

    for report in (stale, future):
        result = build_market_research_report(_bound_request(marketplace_report=report))
        assert result.client_safe_export_status == "ready_for_trustos_review"
        assert "evidence_freshness_unresolved" in result.blockers
        assert any(row["status"] in {"stale", "future"} for row in result.freshness)
        assert "refresh_or_reject_temporally_invalid_evidence" in result.next_research_actions


def test_workspace_mismatch_and_unsafe_payloads_fail_closed_without_reflection():
    mismatched = {**_MARKETPLACE, "workspace_id": "workspace-other"}
    with pytest.raises(ValueError, match="workspace_mismatch"):
        build_market_research_report(_bound_request(marketplace_report=mismatched))

    for unsafe in (
        {"api_key": "not-a-real-secret"},
        {"provider_payload": {"value": "fixture"}},
        {"notes": "<html><script>internal</script>"},
    ):
        with pytest.raises(ValueError, match="unsafe_evidence_input"):
            build_market_research_report(_bound_request(marketplace_report=unsafe))

    with pytest.raises(ValueError, match="invalid workspace_id") as error:
        build_market_research_report(_bound_request(workspace_id="workspace;secret"))
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("unsafe_query", [
    "<img src=x onerror=alert(1)>",
    "sk_live_51N0REALSECRETEXAMPLE",
    "eyJhbGciOiJIUzI1NiJ9.payload.signature",
])
def test_html_and_secret_shaped_values_are_rejected_before_synthesis(unsafe_query):
    marketplace = {
        "evidence_mode": "sanitized_report",
        "candidates": [{
            "candidate_id": "c1",
            "query": unsafe_query,
            "score": {"overall_marketplace_opportunity": 0.7},
        }],
    }

    with pytest.raises(ValueError, match="unsafe_evidence_input"):
        build_market_research_report(_request(marketplace_report=marketplace))


def test_trustos_boundary_blocks_leakage_this_module_own_input_filter_misses():
    """Genuine defense-in-depth, not duplicate checking: this module's own
    _validate_safe_inputs marker list does not cover words like "pricing"
    or "formula" in a free-text query field, so this input passes it. The
    TrustOS check_workspace_leakage boundary at the client-safe-projection
    stage does cover them and must still catch this before export."""
    marketplace = {
        "evidence_mode": "sanitized_report",
        "candidates": [
            {
                "candidate_id": "c1",
                "query": "our internal pricing formula for a competitor",
                "observed_at": "2026-08-01",
                "score": {"overall_marketplace_opportunity": 0.7, "saturation_score": 0.4},
            }
        ],
    }
    with pytest.raises(ValueError, match="unsafe_evidence_input"):
        build_market_research_report(_bound_request(marketplace_report=marketplace))


def test_candidate_identity_does_not_follow_a_template_candidate():
    marketplace = {
        "evidence_mode": "sanitized_report",
        "candidates": [
            {"candidate_id": "template-candidate", "title": "Template", "score": {"overall_marketplace_opportunity": 0.99}},
            {"candidate_id": "c1", "title": "Selected Candidate", "score": {"overall_marketplace_opportunity": 0.6}},
        ],
    }
    result = build_market_research_report(_bound_request(
        marketplace_report=marketplace,
        client_context={"template_candidate_id": "template-candidate"},
    ))

    assert result.candidate_id == "c1"
    assert result.candidate_title == "Selected Candidate"
    assert result.workspace_id == "workspace-1"
    assert all(item["observation"]["candidate_id"] == "c1" for item in result.observation_source_identity)


def test_candidate_identity_scopes_synthesis_summary_and_actions():
    marketplace = {
        "evidence_mode": "sanitized_report",
        "candidates": [
            {"candidate_id": "template-candidate", "title": "Template", "score": {"overall_marketplace_opportunity": 0.99}},
            {"candidate_id": "c1", "title": "Selected Candidate", "score": {"overall_marketplace_opportunity": 0.10}},
        ],
    }
    result = build_market_research_report(_bound_request(marketplace_report=marketplace))

    assert "template-candidate" not in result.executive_summary["headline"]
    assert result.executive_summary["combined_opportunity_score"] == 0.055
    assert result.next_action == "run_readonly_supplier_validation"


def test_duplicate_candidate_rows_fail_closed_before_synthesis():
    marketplace = {
        "evidence_mode": "sanitized_report",
        "candidates": [
            {"candidate_id": "c1", "title": "First", "score": {"overall_marketplace_opportunity": 0.10}},
            {"candidate_id": "c1", "title": "Second", "score": {"overall_marketplace_opportunity": 0.90}},
        ],
    }

    with pytest.raises(ValueError, match="ambiguous_candidate_identity"):
        build_market_research_report(_bound_request(marketplace_report=marketplace))


@pytest.mark.parametrize("candidate_id", ["../other", "bad/id", "candidate with spaces"])
def test_decoy_candidate_rows_require_safe_identity(candidate_id):
    marketplace = {
        "evidence_mode": "sanitized_report",
        "candidates": [{"candidate_id": candidate_id, "score": {"overall_marketplace_opportunity": 0.99}}],
    }

    with pytest.raises(ValueError, match="invalid candidate_id"):
        build_market_research_report(_bound_request(marketplace_report=marketplace))


def test_aggregate_product_validation_is_not_candidate_evidence():
    validation = {
        "evidence_mode": "sanitized_report",
        "top_candidates": [{"candidate": {"candidate_id": "decoy", "title": "Decoy"}}],
        "risk_flags": ["decoy_risk"],
        "open_questions": ["decoy_question"],
    }

    result = build_market_research_report(_bound_request(product_validation_report=validation))

    row = next(item for item in result.evidence_matrix if item.pillar == "product_validation")
    assert row.status == "missing"
    assert "product_validation_candidate_binding_unavailable" in result.blockers
    assert "decoy_risk" not in result.observed_facts
    assert "decoy_question" not in result.assumptions


def test_candidate_bound_product_validation_is_preserved():
    validation = {
        "evidence_mode": "sanitized_report",
        "top_candidates": [{"candidate": {"candidate_id": "c1", "title": "Selected"}}],
        "risk_flags": ["selected_risk"],
        "open_questions": ["selected_question"],
    }

    result = build_market_research_report(_bound_request(product_validation_report=validation))

    row = next(item for item in result.evidence_matrix if item.pillar == "product_validation")
    assert row.status == "supplied"
    assert "product_validation_candidate_binding_unavailable" not in result.blockers
    assert "selected_risk" in result.observed_facts
    assert "selected_question" in result.assumptions


def test_candidate_mismatch_is_missing_in_the_evidence_matrix():
    marketplace = {
        "evidence_mode": "sanitized_report",
        "candidates": [{"candidate_id": "other", "score": {"overall_marketplace_opportunity": 0.99}}],
    }
    result = build_market_research_report(_bound_request(marketplace_report=marketplace))

    row = next(item for item in result.evidence_matrix if item.pillar == "marketplace")
    assert row.status == "missing"
    assert "candidate_not_matched" in " ".join(row.notes)
    assert "evidence_missing" in result.blockers
    assert result.competitor_and_substitute_evidence["status"] == "candidate_not_matched"


def test_public_market_candidate_results_preserve_identity_and_zero():
    public_market = {
        "evidence_mode": "sanitized_report",
        "candidate_results": [{"candidate_id": "c1", "evidence": [{"price": 0, "shipping_cost": 0, "observed_at": "2026-09-20"}]}],
    }
    result = build_market_research_report(_bound_request(public_market_benchmark_report=public_market))

    row = next(item for item in result.evidence_matrix if item.pillar == "public_market_benchmark")
    assert row.status == "supplied"
    assert result.marketplace_and_public_signals["status"] == "supplied"
    assert any(item["observation"]["field"] == "price" for item in result.source_provenance)
    assert any(item["observation"]["field"] == "shipping_cost" for item in result.source_provenance)


def test_workspace_claim_requires_an_explicit_request_identity():
    report = {**_MARKETPLACE, "workspace_id": "workspace-claimed"}

    with pytest.raises(ValueError, match="workspace_identity_required"):
        build_market_research_report(_request(marketplace_report=report))


def test_unbound_candidate_identity_and_nested_nonfinite_input_fail_closed():
    with pytest.raises(ValueError, match="invalid candidate_id"):
        build_market_research_report(MarketResearchRequest(candidate_id="bad id", marketplace_report=_MARKETPLACE))

    nested: dict = {"value": 1}
    for _ in range(20):
        nested = {"nested": nested}
    with pytest.raises(ValueError, match="evidence_input_bounds_exceeded"):
        build_market_research_report(_request(marketplace_report=nested))

    with pytest.raises(ValueError, match="malformed_evidence_input"):
        build_market_research_report(_request(marketplace_report={"score": {"value": float("nan")}}))


def test_non_mapping_pillar_is_rejected_before_canonical_synthesis():
    with pytest.raises(ValueError, match="malformed_evidence_input"):
        build_market_research_report(_request(marketplace_report="not-an-object"))


def test_consumer_attention_cannot_satisfy_supplier_or_launch_gates():
    result = build_market_research_report(_bound_request(consumer_report=_CONSUMER))
    serialized = json.dumps(result.to_dict()).lower()

    assert "supplier_feasibility" in result.next_research_actions
    assert "evidence_missing" in result.blockers
    assert "attention_is_not_supplier_proof" in serialized
    assert result.client_safe_projection["live_proof"] is False
    assert result.client_safe_projection["external_actions_authorized"] is False


def test_integrated_serialization_and_markdown_are_deterministic():
    """generated_at is real wall-clock time (see
    test_fingerprint_is_independent_of_generated_at) and legitimately
    differs between any two calls, so it is excluded here rather than
    special-cased to a fixed sentinel in production code just to make two
    calls compare byte-for-byte equal. Every other field must still match
    exactly."""
    request = _bound_request(
        marketplace_report=_MARKETPLACE,
        supplier_report=_SUPPLIER_WITH_SHIPPING,
        consumer_report=_CONSUMER,
    )
    first = build_market_research_report(request)
    second = build_market_research_report(request)

    first_dict = first.to_dict()
    second_dict = second.to_dict()
    first_dict.pop("generated_at")
    second_dict.pop("generated_at")
    assert json.dumps(first_dict, sort_keys=True) == json.dumps(second_dict, sort_keys=True)

    first_markdown = render_market_research_markdown(first).split("_Generated at", 1)[-1]
    second_markdown = render_market_research_markdown(second).split("_Generated at", 1)[-1]
    assert first_markdown.split("_\n", 1)[-1] == second_markdown.split("_\n", 1)[-1]
