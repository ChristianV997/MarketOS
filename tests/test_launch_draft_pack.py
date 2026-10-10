from __future__ import annotations

import json

import pytest

from evaluation.commerce.launch_draft_pack import build_launch_draft_pack
from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis
from evaluation.commerce.product_validation_report import generate, markdown as report_markdown
from scripts.run_product_opportunity_synthesis import _default_reports


@pytest.fixture()
def reports():
    market, supplier, consumer = _default_reports()
    synthesis = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    return synthesis, market, supplier, consumer


@pytest.fixture()
def pack(reports):
    synthesis, market, supplier, consumer = reports
    return build_launch_draft_pack(synthesis=synthesis, marketplace_trend=market, supplier_feasibility=supplier, consumer_attention=consumer).to_dict()


def test_pack_is_real_draft_output(pack):
    assert pack["candidate_id"]
    assert pack["launch_draft_status"] == "draft_only_pending_human_approval"
    assert pack["offer_stack"]["core_offer"]
    assert pack["product_listing"]["title"]
    assert pack["landing_page"]["sections"]


@pytest.mark.parametrize("flag", ["read_only", "network_calls", "mutated", "published", "ads_launched", "orders_created", "payments_created", "customer_messages_sent"])
def test_safety_flags_are_enforced(pack, flag):
    assert pack[flag] is (True if flag == "read_only" else False)


@pytest.mark.parametrize("section", ["hero", "problem", "solution", "how_it_works", "benefits", "proof_or_demo_section", "comparison_section", "offer_section", "faq", "risk_reversal", "final_cta"])
def test_landing_page_contains_required_section(pack, section):
    item = pack["landing_page"]["sections"][section]
    assert {"headline", "body_copy", "asset_note", "evidence_source_note", "risk_note"} <= set(item)
    assert item["draft_only"] is True


@pytest.mark.parametrize("key", ["core_offer", "headline_value_proposition", "primary_promise", "secondary_benefits", "bundle_suggestions", "pricing_suggestion", "discount_suggestion", "risk_reversal", "shipping_return_notes", "urgency_scarcity_guidance", "claim_safety_notes"])
def test_offer_stack_has_sellable_but_safe_field(pack, key):
    assert pack["offer_stack"].get(key) not in (None, "")


@pytest.mark.parametrize("key", ["title", "subtitle", "short_description", "long_description", "bullet_benefits", "features", "specifications", "what_is_included", "shipping_note", "return_note", "risk_disclaimer", "seo_keywords", "image_brief"])
def test_listing_has_required_field(pack, key):
    assert key in pack["product_listing"]


def test_unknown_product_facts_are_not_invented(pack):
    specs = pack["product_listing"]["specifications"]
    assert specs["sku"].startswith("TBD")
    assert specs["dimensions"].startswith("TBD")
    assert specs["certifications"].startswith("TBD")
    assert pack["shopify_draft_payload"]["variants"][0]["inventory_quantity"] == "TBD"


def test_supplier_missing_disclaimer_is_present(reports):
    synthesis, market, _supplier, consumer = reports
    pack = build_launch_draft_pack(synthesis=synthesis, marketplace_trend=market, consumer_attention=consumer, supplier_feasibility=None).to_dict()
    assert pack["approval_checklist"]["launch_authorized"] is False
    assert any("supplier" in blocker.lower() for blocker in pack["approval_checklist"]["blockers"])
    assert "not a launch authorization" in pack["client_summary"]


def test_context_is_applied_and_sanitized(reports):
    synthesis, market, supplier, consumer = reports
    pack = build_launch_draft_pack(synthesis=synthesis, marketplace_trend=market, supplier_feasibility=supplier, consumer_attention=consumer, client_context={"brand_name": "Mi Marca", "currency": "MXN", "target_customer": "viajeros", "language": "es", "prohibited_claims": ["guaranteed", "cure"], "shipping_policy_text": "Entrega por confirmar."}).to_dict()
    assert pack["shopify_draft_payload"]["vendor"] == "Mi Marca"
    assert pack["offer_stack"]["pricing_suggestion"]["currency"] == "MXN"
    assert "guaranteed" not in json.dumps(pack).lower()
    assert "cure" not in json.dumps(pack).lower()


def test_missing_context_uses_conservative_defaults(pack):
    assert pack["shopify_draft_payload"]["vendor"] == "MarketOS Draft"
    assert "TBD" in pack["product_listing"]["shipping_note"]


def _pack_with_unit_economics(synthesis, unit_economics):
    candidate_id = synthesis["top_candidate_id"]
    candidates = []
    matched = False
    for item in synthesis["candidates"]:
        candidate = dict(item)
        if candidate.get("candidate_id") == candidate_id:
            candidate["unit_economics_summary"] = dict(unit_economics)
            matched = True
        candidates.append(candidate)
    assert matched
    variant_synthesis = {**synthesis, "unit_economics_summary": {}, "candidates": candidates}
    return build_launch_draft_pack(synthesis=variant_synthesis).to_dict()


@pytest.mark.parametrize(
    ("unit_economics", "expected_payload_price"),
    [({}, "TBD"), ({"target_sell_price": 0.0}, 0.0)],
)
def test_missing_zero_and_positive_prices_remain_distinct_in_draft_payloads(reports, unit_economics, expected_payload_price):
    synthesis, _market, _supplier, _consumer = reports
    pack = _pack_with_unit_economics(synthesis, unit_economics)

    expected_offer_price = unit_economics.get("target_sell_price")
    assert pack["offer_stack"]["pricing_suggestion"]["target_price"] == expected_offer_price
    assert pack["shopify_draft_payload"]["variants"][0]["price"] == expected_payload_price
    assert pack["medusa_draft_payload"]["variants"][0]["price"] == expected_payload_price
    if not unit_economics:
        missing_explicitly = _pack_with_unit_economics(synthesis, {"target_sell_price": None})
        positive = _pack_with_unit_economics(synthesis, {"target_sell_price": 24.95})
        assert missing_explicitly["shopify_draft_payload"]["variants"][0]["price"] == "TBD"
        assert missing_explicitly["medusa_draft_payload"]["variants"][0]["price"] == "TBD"
        assert positive["offer_stack"]["pricing_suggestion"]["target_price"] == 24.95
        assert positive["shopify_draft_payload"]["variants"][0]["price"] == 24.95
        assert positive["medusa_draft_payload"]["variants"][0]["price"] == 24.95


def test_creative_counts_meet_pack_contract(pack):
    ads = pack["ad_creatives"]
    assert len(ads["angles"]) >= 5
    assert len(ads["hooks"]) >= 10
    assert len(ads["short_form_video_scripts"]) >= 5
    assert len(ads["static_ad_concepts"]) >= 5
    assert len(ads["meta_primary_text_options"]) == 3
    assert len(ads["tiktok_reels_captions"]) == 3
    assert len(ads["headline_options"]) == 3


@pytest.mark.parametrize("brief_type", ["hands_only_demo", "problem_solution", "before_after_or_comparison"])
def test_ugc_brief_has_required_controls(pack, brief_type):
    brief = next(item for item in pack["ugc_briefs"] if item["brief_type"] == brief_type)
    assert brief["opening_hook"]
    assert brief["shot_list"]
    assert brief["objection_handling_moment"]
    assert brief["cta"]
    assert brief["do_not_say_claims"]
    assert brief["required_disclosures"]


@pytest.mark.parametrize("field", ["angle", "hook", "format", "asset_required", "hypothesis", "target_metric", "kill_threshold", "scale_threshold", "budget_note", "risk_note"])
def test_creative_matrix_has_planning_fields(pack, field):
    assert all(field in row for row in pack["creative_test_matrix"]["rows"])


@pytest.mark.parametrize("item", ["supplier proof confirmed", "landed cost confirmed", "shipping window confirmed", "inventory confirmed", "return/refund policy reviewed", "claims/compliance reviewed", "price band approved", "break-even CPA approved", "ad budget cap approved", "creative claims approved", "Shopify draft approved", "launch not authorized until final approval"])
def test_approval_checklist_covers_gate(item, pack):
    assert item in pack["approval_checklist"]["items"]


@pytest.mark.parametrize("field", ["supplier_risk", "shipping_risk", "margin_risk", "claim_compliance_risk", "creative_risk", "market_saturation_risk", "customer_support_risk", "refund_risk", "platform_policy_risk"])
def test_risk_review_covers_required_category(pack, field):
    assert pack["risk_review"][field]


def test_payloads_are_draft_only(pack):
    assert pack["shopify_draft_payload"]["status"] == "draft"
    assert pack["medusa_draft_payload"]["status"] == "draft"
    assert pack["shopify_draft_payload"]["metafields"]["marketos_launch_authorized"] is False
    assert pack["medusa_draft_payload"]["metadata"]["marketos_launch_authorized"] is False


def test_report_includes_launch_summary(reports, pack):
    synthesis, market, supplier, consumer = reports
    report = generate(opportunity_synthesis=synthesis, marketplace_trends=market, supplier_feasibility=supplier, consumer_attention=consumer, launch_draft_pack=pack).to_dict()
    summary = report["executive_summary"]["launch_draft_pack"]
    assert summary["candidate_id"] == pack["candidate_id"]
    assert summary["shopify_status"] == "draft"
    assert summary["creative_tests"] == len(pack["creative_test_matrix"]["rows"])
    output = report_markdown(report)
    assert "Launch Draft Pack Summary" in output
    assert "Approval blockers" in output


def test_report_without_launch_pack_preserves_clean_degradation(reports):
    synthesis, market, supplier, consumer = reports
    report = generate(opportunity_synthesis=synthesis, marketplace_trends=market, supplier_feasibility=supplier, consumer_attention=consumer).to_dict()
    assert "launch_draft_pack" not in report["executive_summary"]
    assert report["source_reports"]["launch_draft_pack"] == "missing"


def test_pack_serialization_contains_no_network_or_provider_actions(pack):
    raw = json.dumps(pack).lower()
    assert "api call" not in raw
    assert "publish" in raw
    assert pack["network_calls"] is False
    assert pack["mutated"] is False


def test_pack_is_deterministic(reports):
    synthesis, market, supplier, consumer = reports
    first = build_launch_draft_pack(synthesis=synthesis, marketplace_trend=market, supplier_feasibility=supplier, consumer_attention=consumer).to_dict()
    second = build_launch_draft_pack(synthesis=synthesis, marketplace_trend=market, supplier_feasibility=supplier, consumer_attention=consumer).to_dict()
    assert first == second


def test_listing_does_not_invent_reviews_or_certifications(pack):
    raw = json.dumps(pack["product_listing"]).lower()
    assert "review count" not in raw
    assert "certified" not in raw


def test_draft_pack_does_not_contain_activation_instructions(pack):
    raw = json.dumps(pack).lower()
    assert "shopify api" not in raw
    assert "launch ads" not in raw


def test_matching_customer_language_becomes_platform_neutral_draft_copy(reports):
    synthesis, market, supplier, consumer = reports
    pack = build_launch_draft_pack(synthesis=synthesis, marketplace_trend=market, supplier_feasibility=supplier, consumer_attention=consumer).to_dict()
    short = pack["product_listing"]["short_description"]
    hero = pack["landing_page"]["sections"]["hero"]["body_copy"]
    assert "quick portable printing" in short
    assert "quick portable printing" in hero
    assert "not a verified product promise" in short
    assert "prints labels without ink" not in json.dumps(pack)
    assert "visible print test" not in json.dumps(pack)
    assert pack["product_listing"]["specifications"]["certifications"].startswith("TBD")
    assert pack["launch_draft_status"] == "draft_only_pending_human_approval"
    assert pack["approval_checklist"]["launch_authorized"] is False
    assert pack["shopify_draft_payload"]["status"] == "draft"
    assert pack["medusa_draft_payload"]["status"] == "draft"
    assert pack["published"] is False
    assert pack["ads_launched"] is False


def test_missing_customer_evidence_does_not_invent_draft_language(reports):
    synthesis, market, supplier, _consumer = reports
    pack = build_launch_draft_pack(synthesis=synthesis, marketplace_trend=market, supplier_feasibility=supplier, consumer_attention=None).to_dict()
    assert "quick portable printing" not in json.dumps(pack["product_listing"])
    assert "customers who want" in pack["product_listing"]["short_description"]
    assert any("Consumer attention evidence was not supplied" in note for note in pack["operator_notes"])
    assert pack["approval_checklist"]["launch_authorized"] is False
    assert pack["published"] is False


def test_mismatched_evidence_is_not_copied_and_cannot_clear_draft_gates(reports):
    synthesis, _market, _supplier, _consumer = reports
    foreign_attention = {
        "top_candidate_id": "other-product",
        "candidates": [{
            "candidate_id": "other-product",
            "score": {
                "landing_page_copy_hints": ["Lead with: FOREIGN_CUSTOMER_LANGUAGE"],
                "voice_of_customer": {"desired_outcomes": ["FOREIGN_OUTCOME"], "claims": ["FOREIGN_CLAIM"], "proof_signals": ["FOREIGN_PROOF"]},
            },
        }],
    }
    foreign_supplier = {"top_candidate_id": "other-product", "candidates": [{"candidate_id": "other-product", "score": {"economics": {"target_sell_price": 1}}}]}
    pack = build_launch_draft_pack(synthesis=synthesis, consumer_attention=foreign_attention, supplier_feasibility=foreign_supplier).to_dict()
    raw = json.dumps(pack)
    assert "FOREIGN_CUSTOMER_LANGUAGE" not in raw
    assert "FOREIGN_OUTCOME" not in raw
    assert "FOREIGN_CLAIM" not in raw
    assert "FOREIGN_PROOF" not in raw
    assert "other-product" not in raw
    assert any("supplier proof is not live-observed" in item for item in pack["approval_checklist"]["blockers"])
    assert any("does not match this draft candidate" in note for note in pack["operator_notes"])
    assert pack["approval_checklist"]["launch_authorized"] is False
    assert pack["published"] is False
    assert pack["ads_launched"] is False
    assert pack["orders_created"] is False
    assert pack["payments_created"] is False
    assert pack["customer_messages_sent"] is False
    assert pack["shopify_draft_payload"]["status"] == "draft"
    assert pack["medusa_draft_payload"]["status"] == "draft"


def test_no_real_candidate_identity_cannot_bind_to_a_placeholder_sentinel(reports):
    """A draft with no real candidate id (no top_candidate_id, no candidate
    row id) must never match evidence keyed by the internal "candidate"
    display placeholder -- that would let an unrelated report's row bind by
    coincidence rather than by real product identity."""
    synthesis, _market, _supplier, _consumer = reports
    synthesis = {**synthesis, "top_candidate_id": None, "candidates": [{}]}
    sentinel_attention = {"candidates": [{"candidate_id": "candidate", "score": {"landing_page_copy_hints": ["STOLEN CUSTOMER LANGUAGE FROM OTHER PRODUCT"]}}]}
    pack = build_launch_draft_pack(synthesis=synthesis, consumer_attention=sentinel_attention).to_dict()
    raw = json.dumps(pack)
    assert "STOLEN CUSTOMER LANGUAGE FROM OTHER PRODUCT" not in raw
    assert any("was not supplied" in note for note in pack["operator_notes"] if "Consumer attention" in note)
    assert pack["approval_checklist"]["launch_authorized"] is False


def test_matching_evidence_binds_regardless_of_case_or_surrounding_whitespace(reports):
    """The synthesis/candidate id and the evidence report's own id come from
    independent pipelines and are not guaranteed to agree on casing or
    padding for the same real candidate -- matching must not silently drop
    genuine evidence over that alone."""
    synthesis, _market, _supplier, _consumer = reports
    synthesis = {**synthesis, "top_candidate_id": " Widget-1 ", "candidates": [{"candidate_id": " Widget-1 "}]}
    same_candidate_attention = {"candidates": [{"candidate_id": "widget-1", "score": {"landing_page_copy_hints": ["real matching language"]}}]}
    pack = build_launch_draft_pack(synthesis=synthesis, consumer_attention=same_candidate_attention).to_dict()
    assert "real matching language" in pack["product_listing"]["short_description"]
    assert any("matches this draft candidate" in note for note in pack["operator_notes"] if "Consumer attention" in note)


@pytest.mark.parametrize("malformed_id", [True, False, ["a", "b"], {"nested": "id"}])
def test_malformed_non_string_identity_can_never_bind_an_unrelated_evidence_row(reports, malformed_id):
    """A non-string top_candidate_id/candidate_id (bool, list, dict, ...) is
    never a real product identifier. Coercing it with str() would still
    produce a stable-looking key that could coincidentally collide with an
    equally malformed candidate_id on an unrelated evidence row -- malformed
    identity must bind nothing, exactly like the missing-identity case."""
    synthesis, _market, _supplier, _consumer = reports
    synthesis = {**synthesis, "top_candidate_id": malformed_id, "candidates": [{}]}
    colliding_attention = {"candidates": [{"candidate_id": malformed_id, "score": {"landing_page_copy_hints": ["MALFORMED IDENTITY COLLISION LANGUAGE"]}}]}
    pack = build_launch_draft_pack(synthesis=synthesis, consumer_attention=colliding_attention).to_dict()
    raw = json.dumps(pack)
    assert "MALFORMED IDENTITY COLLISION LANGUAGE" not in raw
    assert any("was not supplied" in note for note in pack["operator_notes"] if "Consumer attention" in note)
    assert pack["approval_checklist"]["launch_authorized"] is False
    assert pack["published"] is False
    assert pack["shopify_draft_payload"]["status"] == "draft"
    assert pack["medusa_draft_payload"]["status"] == "draft"
