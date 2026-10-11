from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.commerce.site_draft_builder import (
    CLAIM_ROLES,
    EVIDENCE_CLASSES,
    EvidenceAttribution,
    SITE_TYPES,
    build_site_draft_pack,
    markdown,
)
from evaluation.commerce.product_validation_report import generate as generate_validation_report, markdown as validation_markdown
from scripts.generate_site_draft_pack import _defaults

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "site_draft_builder"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf8"))


def _all_attributions(pack: dict) -> list[dict]:
    return [
        attr
        for page in pack.get("pages", [])
        for section in page.get("sections", [])
        for attr in section.get("evidence_attributions", [])
    ]


@pytest.fixture(scope="module")
def inputs():
    launch, synthesis, market, supplier, consumer = _defaults()
    return launch, synthesis, market, supplier, consumer


@pytest.fixture()
def pack(inputs):
    launch, synthesis, market, supplier, consumer = inputs
    return build_site_draft_pack(launch_draft_pack=launch, opportunity_synthesis=synthesis, marketplace_trends=market, supplier_feasibility=supplier, consumer_attention=consumer, site_type="ecommerce_store").to_dict()


@pytest.mark.parametrize("flag", ["read_only", "network_calls", "mutated", "published", "domains_changed", "hosting_changed", "shopify_mutated", "medusa_mutated", "woocommerce_mutated", "webflow_mutated", "wix_mutated", "squarespace_mutated", "ads_launched", "orders_created", "payments_created", "customer_messages_sent"])
def test_safety_flags_are_fixed(pack, flag):
    assert pack[flag] is (True if flag == "read_only" else False)


@pytest.mark.parametrize("site_type", sorted(SITE_TYPES))
def test_every_site_type_generates_distinct_routes(inputs, site_type):
    launch, synthesis, market, supplier, consumer = inputs
    output = build_site_draft_pack(launch_draft_pack=launch, opportunity_synthesis=synthesis, marketplace_trends=market, supplier_feasibility=supplier, consumer_attention=consumer, site_type=site_type).to_dict()
    assert output["site_type"] == site_type
    assert output["route_manifest"]["routes"]
    assert output["pages"]
    assert output["approval_checklist"]["publishing_authorized"] is False


def test_missing_context_degrades_safely(inputs):
    launch, synthesis, *_ = inputs
    output = build_site_draft_pack(launch_draft_pack=launch, opportunity_synthesis=synthesis).to_dict()
    assert output["site_strategy"]["preferred_platform"] == "platform-neutral draft"
    assert "TBD" in json.dumps(output)
    assert output["deployment_readiness"]["overall_status"] == "partially_ready"


def test_client_context_is_applied(inputs):
    launch, synthesis, *_ = inputs
    output = build_site_draft_pack(launch_draft_pack=launch, opportunity_synthesis=synthesis, client_context={"business_name": "Demo Studio", "industry": "consulting", "business_type": "service", "site_type": "service_business_website", "target_customer": "local operators", "preferred_platform": "Webflow", "contact_email": "hello@example.invalid", "location": "TBD"}, site_type="service_business_website").to_dict()
    assert output["site_strategy"]["preferred_platform"] == "Webflow"
    assert output["pages"][0]["target_user"] == "local operators"
    assert output["candidate_title"]


def test_unknown_contact_and_legal_details_are_not_invented(pack):
    raw = json.dumps(pack)
    assert "555-" not in raw
    assert "123 Main" not in raw
    assert "certified" not in raw.lower()
    assert "TBD" in raw


@pytest.mark.parametrize("field", ["route", "page_id", "page_type", "title", "purpose", "conversion_goal", "requires_approval", "platform_notes"])
def test_route_manifest_has_required_fields(pack, field):
    assert all(field in item for item in pack["route_manifest"]["routes"])


@pytest.mark.parametrize("field", ["page_id", "page_type", "route", "goal", "target_user", "sections", "seo_title", "meta_description", "primary_keyword", "secondary_keywords", "conversion_goal", "required_assets", "evidence_notes", "approval_blockers"])
def test_pages_have_required_fields(pack, field):
    assert all(field in page for page in pack["pages"])


@pytest.mark.parametrize("section_type", ["hero", "problem", "solution", "benefits", "how_it_works", "product_grid", "collection_grid", "comparison", "social_proof_placeholder", "demo_section", "offer_section", "faq", "lead_capture", "final_cta", "contact", "trust_policies"])
def test_section_drafts_have_safety_and_evidence_notes(pack, section_type):
    sections = [section for page in pack["pages"] for section in page["sections"] if section["section_type"] == section_type]
    if sections:
        for section in sections:
            assert section["evidence_source_note"]
            assert section["risk_note"]
            assert section["approval_required"] is True
            assert section["blocks"]


@pytest.mark.parametrize("field", ["block_type", "content", "settings", "asset_placeholder", "cms_binding", "evidence_note", "approval_required"])
def test_section_blocks_have_required_fields(pack, field):
    blocks = [block for page in pack["pages"] for section in page["sections"] for block in section["blocks"]]
    assert all(field in block for block in blocks)


@pytest.mark.parametrize("schema", ["hero", "problem_solution", "benefits_grid", "comparison_table", "product_grid", "collection_grid", "pricing_offer", "faq", "lead_form", "social_proof_placeholder", "demo", "final_cta", "contact", "trust_policies"])
def test_section_library_contains_schema(schema, pack):
    assert schema in pack["section_library"]
    assert pack["section_library"][schema]["required_blocks"]
    assert set(pack["section_library"][schema]["platform_mapping"]) == {"static", "shopify", "medusa", "woocommerce", "webflow", "wix", "squarespace", "carrd"}


@pytest.mark.parametrize("model", ["Product", "Variant", "Collection", "Offer", "FAQ", "Policy", "Page", "Section", "Asset", "LeadForm", "Campaign", "TestVariant", "Service", "ServiceArea", "QuoteRequest"])
def test_cms_model_is_portable_and_approval_aware(model, pack):
    item = next(value for value in pack["cms_content_model"]["models"] if value["model_name"] == model)
    assert item["required_fields"]
    assert item["approval_required_fields"]
    assert item["unknown_fields"]
    assert len(item["platform_mapping"]) == 8


@pytest.mark.parametrize("platform", ["static_site", "shopify_theme", "medusa_storefront", "woocommerce", "webflow_cms", "wix_headless", "squarespace", "carrd_microsite"])
def test_all_platform_payloads_are_draft(pack, platform):
    payload = pack["platform_payloads"][platform]
    assert payload["status"] == "draft"
    assert "api" not in json.dumps(payload).lower()


def test_wix_visibility_is_safe(pack):
    assert pack["platform_payloads"]["wix_headless"]["visibility"] == "hidden_or_draft"


def test_static_payload_contains_routes_pages_and_plans(pack):
    payload = pack["platform_payloads"]["static_site"]
    assert payload["routes"]
    assert payload["pages"]
    assert payload["seo_metadata"]
    assert payload["analytics_placeholder"]
    assert payload["status"] == "draft"


@pytest.mark.parametrize("field", ["primary_keywords", "secondary_keywords", "page_titles", "meta_descriptions", "url_slugs", "schema_suggestions", "internal_linking_plan", "content_gaps", "seo_risks"])
def test_seo_plan_has_required_field(pack, field):
    assert pack["seo_plan"][field]


@pytest.mark.parametrize("field", ["events_to_track", "conversion_events", "funnel_steps", "recommended_utm_fields", "ad_platform_pixel_placeholders", "privacy_consent_notes", "dashboard_metrics"])
def test_analytics_plan_has_required_field(pack, field):
    assert pack["analytics_plan"][field]


@pytest.mark.parametrize("field", ["test_id", "page", "variant", "hypothesis", "traffic_source_note", "target_metric", "kill_threshold", "scale_threshold", "required_sample_note", "risk_note"])
def test_conversion_plan_has_required_field(pack, field):
    assert all(field in item for item in pack["conversion_test_plan"]["tests"])


@pytest.mark.parametrize("item", ["client approved copy", "client approved claims", "supplier proof confirmed", "pricing approved", "shipping window approved", "return policy approved", "images/assets approved", "SEO metadata approved", "analytics/privacy approved", "draft payload approved", "publishing not authorized until final approval"])
def test_approval_checklist_covers_required_item(pack, item):
    assert item in pack["approval_checklist"]["items"]


@pytest.mark.parametrize("field", ["conversion_risk", "copy_claim_risk", "supplier_risk", "shipping_risk", "policy_legal_risk", "platform_readiness_risk", "asset_quality_risk", "tracking_privacy_risk", "seo_risk", "customer_support_risk"])
def test_risk_review_covers_required_category(pack, field):
    assert pack["risk_review"][field]


def test_supplier_blocker_propagates(inputs):
    launch, synthesis, *_ = inputs
    output = build_site_draft_pack(launch_draft_pack=launch, opportunity_synthesis=synthesis).to_dict()
    assert "supplier_proof_ready" in output["deployment_readiness"]["blockers"]
    assert any("supplier" in item.lower() for item in output["approval_checklist"]["blockers"])


def test_no_fake_social_proof(pack):
    raw = json.dumps(pack).lower()
    assert "customer testimonial" not in raw
    assert "verified review" not in raw
    assert "fake logo" not in raw


def test_deterministic_serialization(inputs):
    launch, synthesis, market, supplier, consumer = inputs
    first = build_site_draft_pack(launch_draft_pack=launch, opportunity_synthesis=synthesis, marketplace_trends=market, supplier_feasibility=supplier, consumer_attention=consumer).to_dict()
    second = build_site_draft_pack(launch_draft_pack=launch, opportunity_synthesis=synthesis, marketplace_trends=market, supplier_feasibility=supplier, consumer_attention=consumer).to_dict()
    assert first == second


def test_invalid_site_type_fails_closed(inputs):
    launch, synthesis, *_ = inputs
    with pytest.raises(ValueError, match="unsupported site type"):
        build_site_draft_pack(launch_draft_pack=launch, opportunity_synthesis=synthesis, site_type="live_store")


def test_product_validation_report_includes_site_summary(pack, inputs):
    _launch, synthesis, market, supplier, consumer = inputs
    report = generate_validation_report(opportunity_synthesis=synthesis, marketplace_trends=market, supplier_feasibility=supplier, consumer_attention=consumer, site_draft_pack=pack).to_dict()
    summary = report["executive_summary"]["site_draft_pack"]
    assert summary["site_type"] == "ecommerce_store"
    assert summary["routes"] == len(pack["route_manifest"]["routes"])
    assert "platform_payloads" in summary
    assert "Website / Store / Funnel Draft Summary" in validation_markdown(report)


def test_report_without_site_pack_degrades_cleanly(inputs):
    _launch, synthesis, market, supplier, consumer = inputs
    report = generate_validation_report(opportunity_synthesis=synthesis, marketplace_trends=market, supplier_feasibility=supplier, consumer_attention=consumer).to_dict()
    assert "site_draft_pack" not in report["executive_summary"]
    assert report["source_reports"]["site_draft_pack"] == "missing"


class TestMatchedCustomerLanguage:
    def test_matched_candidate_carries_customer_language_into_hero(self):
        synthesis = {
            "top_candidate_id": "printer-pro-1",
            "top_candidate_title": "Printer Pro",
            "candidates": [{"candidate_id": "printer-pro-1", "title": "Printer Pro"}],
        }
        launch = {
            "candidate_id": "printer-pro-1",
            "candidate_title": "Printer Pro",
            "customer_language": "print shipping labels in under three seconds without ink",
        }
        pack = build_site_draft_pack(
            launch_draft_pack=launch,
            opportunity_synthesis=synthesis,
        ).to_dict()
        hero_sections = [
            sec for page in pack["pages"] for sec in page["sections"] if sec["section_type"] == "hero"
        ]
        assert hero_sections
        for hero in hero_sections:
            assert "print shipping labels in under three seconds without ink" in hero["body"]
            assert "Use this only as draft customer language; do not publish it as a result promise." in hero["body"]
            assert hero["evidence_source_note"] == "Matching consumer-attention landing hint or desired outcome"
            assert hero["blocks"][0]["content"]["body"] == hero["body"]

    def test_matched_landing_hint_or_desired_outcome_from_launch(self):
        synthesis = {
            "top_candidate_id": "printer-pro-1",
            "top_candidate_title": "Printer Pro",
        }
        launch = {
            "candidate_id": "printer-pro-1",
            "landing_hint": "reliable label printing on the go",
        }
        pack = build_site_draft_pack(launch_draft_pack=launch, opportunity_synthesis=synthesis).to_dict()
        hero = pack["pages"][0]["sections"][0]
        assert hero["section_type"] == "hero"
        assert "reliable label printing on the go" in hero["body"]

    def test_matched_landing_page_hero_extraction(self):
        synthesis = {
            "top_candidate_id": "printer-pro-1",
            "top_candidate_title": "Printer Pro",
        }
        launch = {
            "candidate_id": "printer-pro-1",
            "landing_page": {
                "sections": {
                    "hero": {
                        "body_copy": "fast wireless thermal printing Use this only as draft customer language; do not publish it as a result promise.",
                        "evidence_source_note": "Matching consumer-attention landing hint or desired outcome",
                    }
                }
            },
        }
        pack = build_site_draft_pack(launch_draft_pack=launch, opportunity_synthesis=synthesis).to_dict()
        hero = pack["pages"][0]["sections"][0]
        assert "fast wireless thermal printing" in hero["body"]
        # Ensure disclaimer is not doubled
        assert hero["body"].count("Use this only as draft customer language") == 1

    def test_matched_consumer_attention_fallback(self):
        synthesis = {
            "top_candidate_id": "printer-pro-1",
            "top_candidate_title": "Printer Pro",
        }
        launch = {
            "candidate_id": "printer-pro-1",
            "candidate_title": "Printer Pro",
        }
        attention = {
            "candidates": [
                {
                    "candidate_id": "printer-pro-1",
                    "score": {
                        "landing_page_copy_hints": ["Lead with: compact and battery powered"],
                        "voice_of_customer": {
                            "desired_outcomes": ["print receipts anywhere"],
                            "claims": ["10x faster than traditional printers"],
                            "proof_signals": ["tested by 5000 businesses"],
                        },
                    },
                }
            ]
        }
        pack = build_site_draft_pack(
            launch_draft_pack=launch,
            opportunity_synthesis=synthesis,
            consumer_attention=attention,
        ).to_dict()
        hero = pack["pages"][0]["sections"][0]
        assert "Lead with: compact and battery powered" in hero["body"]
        # Claims and proof signals must NEVER be promoted into page copy
        raw_text = json.dumps(pack["pages"])
        assert "10x faster than traditional printers" not in raw_text
        assert "tested by 5000 businesses" not in raw_text

    def test_mismatched_candidate_blocks_foreign_customer_language(self):
        synthesis = {
            "top_candidate_id": "canonical-candidate-1",
            "top_candidate_title": "Canonical Product",
            "top_hooks": ["Original verified hook"],
        }
        launch = {
            "candidate_id": "foreign-candidate-2",
            "candidate_title": "Foreign Product",
            "customer_language": "foreign customer language that must be blocked",
        }
        pack = build_site_draft_pack(launch_draft_pack=launch, opportunity_synthesis=synthesis).to_dict()
        raw_pages = json.dumps(pack["pages"])
        assert "foreign customer language that must be blocked" not in raw_pages
        # Falls back to canonical hook
        hero = pack["pages"][0]["sections"][0]
        assert hero["body"] == "Original verified hook"
        assert hero["evidence_source_note"] == "Existing evidence reports and client context only."

    def test_placeholder_candidate_id_blocks_language(self):
        synthesis = {"top_candidate_id": "candidate"}
        launch = {
            "candidate_id": "candidate",
            "customer_language": "unbound language with placeholder id",
        }
        pack = build_site_draft_pack(launch_draft_pack=launch, opportunity_synthesis=synthesis).to_dict()
        assert "unbound language with placeholder id" not in json.dumps(pack["pages"])

    @pytest.mark.parametrize("malformed_id", [True, False, 123, ["printer-pro-1"], {"id": "printer-pro-1"}])
    def test_malformed_candidate_id_cannot_bind(self, malformed_id):
        synthesis = {"top_candidate_id": "printer-pro-1"}
        launch = {
            "candidate_id": malformed_id,
            "customer_language": "malformed identity leak attempt",
        }
        pack = build_site_draft_pack(launch_draft_pack=launch, opportunity_synthesis=synthesis).to_dict()
        assert "malformed identity leak attempt" not in json.dumps(pack["pages"])

    def test_prohibited_claims_and_safety_words_are_scrubbed(self):
        synthesis = {"top_candidate_id": "health-widget-1", "top_candidate_title": "Health Widget"}
        launch = {
            "candidate_id": "health-widget-1",
            "customer_language": "Guaranteed 100% cure clinically proven risk-free relief with miracle results",
        }
        client_context = {"prohibited_claims": ["miracle"]}
        pack = build_site_draft_pack(
            launch_draft_pack=launch,
            opportunity_synthesis=synthesis,
            client_context=client_context,
        ).to_dict()
        hero = pack["pages"][0]["sections"][0]
        body = hero["body"]
        for blocked in ["guaranteed", "cure", "clinically proven", "risk-free", "miracle"]:
            assert blocked not in body.lower()
        assert "evidence-led" in body


class TestMarketAccessContractAndSupplierReadiness:
    """market_access is a shared compliance projection; supplier presence must not leak into it."""

    _MARKET_ACCESS = {
        "overall_status": "needs_evidence",
        "offering_kind": "goods",
        "jurisdictions": [{"jurisdiction": "mexico", "assessment_state": "needs_evidence"}],
    }

    def _launch(self, **extra):
        launch = {"candidate_id": "mx-1", "market_access": json.loads(json.dumps(self._MARKET_ACCESS))}
        launch.update(extra)
        return launch

    def test_market_access_is_contract_identical_whether_or_not_supplier_evidence_is_supplied(self):
        synthesis = {"top_candidate_id": "mx-1", "top_candidate_title": "Mx Widget"}
        supplier = {"evidence_mode": "sanitized_report", "candidates": [{"candidate_id": "mx-1"}]}
        with_supplier = build_site_draft_pack(launch_draft_pack=self._launch(), opportunity_synthesis=synthesis, supplier_feasibility=supplier).to_dict()
        without_supplier = build_site_draft_pack(launch_draft_pack=self._launch(), opportunity_synthesis=synthesis).to_dict()
        assert with_supplier["market_access"] == self._MARKET_ACCESS
        assert without_supplier["market_access"] == self._MARKET_ACCESS
        assert "supplier_present" not in with_supplier["market_access"]

    def test_market_access_from_synthesis_is_passed_through_unchanged(self):
        synthesis = {"top_candidate_id": "mx-1", "top_candidate_title": "Mx Widget", "market_access": json.loads(json.dumps(self._MARKET_ACCESS))}
        pack = build_site_draft_pack(opportunity_synthesis=synthesis, supplier_feasibility={"candidates": []}).to_dict()
        assert pack["market_access"] == self._MARKET_ACCESS

    def test_caller_owned_market_access_is_not_mutated_and_top_level_is_not_shared(self):
        # The copy is intentionally shallow (pre-existing behavior): top-level isolation only.
        launch = self._launch()
        synthesis = {"top_candidate_id": "mx-1", "top_candidate_title": "Mx Widget", "market_access": json.loads(json.dumps(self._MARKET_ACCESS))}
        snapshot = json.loads(json.dumps([launch, synthesis]))
        pack = build_site_draft_pack(launch_draft_pack=launch, opportunity_synthesis=synthesis, supplier_feasibility={"candidates": []})
        assert [launch, synthesis] == snapshot
        assert pack.market_access is not launch["market_access"]
        pack.market_access["injected"] = True  # a consumer writing to the pack cannot reach the caller's mapping
        assert "injected" not in launch["market_access"]

    @pytest.mark.parametrize(
        ("launch_extra", "expected_status", "supplier_blocked"),
        [
            ({"evidence_mode": "fixture_demo", "approval_checklist": {"blockers": ["supplier proof is not live-observed"]}}, "blocked", True),
            ({"evidence_mode": "live_readonly", "approval_checklist": {"blockers": ["supplier proof is not live-observed"]}}, "blocked", True),
            ({"evidence_mode": "live_readonly", "approval_checklist": {"blockers": ["human approval is required"]}}, "ready", False),
        ],
    )
    def test_supplier_readiness_blocker_follows_the_launch_checklist_not_market_access(self, launch_extra, expected_status, supplier_blocked):
        pack = build_site_draft_pack(
            launch_draft_pack=self._launch(**launch_extra),
            opportunity_synthesis={"top_candidate_id": "mx-1", "top_candidate_title": "Mx Widget"},
            supplier_feasibility={"candidates": [{"candidate_id": "mx-1"}]},
        ).to_dict()
        readiness = pack["deployment_readiness"]
        assert readiness["checks"]["supplier_proof_ready"]["status"] == expected_status
        assert ("supplier_proof_ready" in readiness["blockers"]) is supplier_blocked
        assert pack["market_access"] == self._MARKET_ACCESS
        assert pack["approval_checklist"]["publishing_authorized"] is False


class TestEvidenceAttributions:
    def test_happy_path_sections_carry_structured_attributions(self, pack):
        attrs = _all_attributions(pack)
        assert attrs
        assert pack["evidence_attribution_summary"]["attribution_count"] == len(attrs)
        for attr in attrs:
            assert set(attr) >= {"source_ref", "evidence_class", "claim_role", "note"}
            assert attr["source_ref"]
            assert attr["evidence_class"] in EVIDENCE_CLASSES
            assert attr["claim_role"] in CLAIM_ROLES
        summary = pack["evidence_attribution_summary"]
        assert summary["supplier_live_claims"] is False
        assert summary["fixture_or_manual_treated_as_live"] is False
        assert summary["assumptions_remain_assumptions"] is True
        assert "fixture" in summary["evidence_class_counts"]
        assert pack["report_version"] == "site-draft-builder-v1.1"
        assert pack["published"] is False
        assert all(payload["status"] == "draft" for payload in pack["platform_payloads"].values())

    def test_markdown_includes_attribution_summary(self, pack):
        md = markdown(pack)
        assert "## Evidence Attributions" in md
        assert "Supplier live claims: `False`" in md
        assert "## Sample Section Attributions" in md
        assert "[fixture/" in md or "[assumed/" in md or "[derived/" in md

    def test_evidence_attribution_dataclass_rejects_invalid_class_and_role(self):
        with pytest.raises(ValueError, match="unsupported evidence class"):
            EvidenceAttribution("opportunity_synthesis", "supplier_live_proof", "synthesis_context")
        with pytest.raises(ValueError, match="unsupported claim role"):
            EvidenceAttribution("opportunity_synthesis", "fixture", "live_fact")

    def test_secret_shaped_keys_are_redacted_from_pack_output(self):
        data = _load_fixture("adversarial_secret_shaped_sources.json")
        pack = build_site_draft_pack(
            launch_draft_pack=data["launch_draft_pack"],
            opportunity_synthesis=data["opportunity_synthesis"],
            supplier_feasibility=data["supplier_feasibility"],
            client_context=data["client_context"],
        ).to_dict()
        raw = json.dumps(pack)
        for token in (
            "shpat_fixture_must_not_appear",
            "cj-secret-must-not-appear",
            "Bearer fixture-secret",
            "should-never-leak",
            "supplier-secret-must-not-appear",
            "client-access-token-must-not-appear",
        ):
            assert token not in raw
        redacted = pack["evidence_attribution_summary"]["secret_shaped_keys_redacted"]
        assert redacted
        assert any("access_token" in item.casefold() or "api_key" in item.casefold() or "secret" in item.casefold() for item in redacted)
        assert pack["evidence_attribution_summary"]["supplier_live_claims"] is False

    def test_malformed_evidence_modes_fail_closed(self):
        data = _load_fixture("adversarial_malformed_evidence.json")
        pack = build_site_draft_pack(
            launch_draft_pack=data["launch_draft_pack"],
            opportunity_synthesis=data["opportunity_synthesis"],
            marketplace_trends=data["marketplace_trends"],
            supplier_feasibility=data["supplier_feasibility"],
            consumer_attention=data["consumer_attention"],
        ).to_dict()
        classes = {attr["evidence_class"] for attr in _all_attributions(pack)}
        assert "malformed" in classes or "missing" in classes
        assert "observed" not in classes
        sources = pack["evidence_attribution_summary"]["sources"]
        assert sources["opportunity_synthesis"]["evidence_class"] == "malformed"
        assert sources["launch_draft_pack"]["evidence_class"] == "malformed"
        assert sources["marketplace_trends"]["evidence_class"] == "malformed"
        assert pack["evidence_attribution_summary"]["supplier_live_claims"] is False
        assert pack["approval_checklist"]["publishing_authorized"] is False

    def test_unsupported_live_labels_never_become_supplier_live_claims(self):
        data = _load_fixture("adversarial_unsupported_evidence_class.json")
        pack = build_site_draft_pack(
            launch_draft_pack=data["launch_draft_pack"],
            opportunity_synthesis=data["opportunity_synthesis"],
            marketplace_trends=data["marketplace_trends"],
            supplier_feasibility=data["supplier_feasibility"],
        ).to_dict()
        attrs = _all_attributions(pack)
        assert attrs
        assert all(attr["evidence_class"] != "observed" for attr in attrs)
        assert "unsupported" in {attr["evidence_class"] for attr in attrs}
        summary = pack["evidence_attribution_summary"]
        assert summary["supplier_live_claims"] is False
        assert summary["fixture_or_manual_treated_as_live"] is False
        assert summary["sources"]["supplier_feasibility"]["evidence_class"] == "unsupported"
        assert pack["evidence_mode"] == "unsupported"
        raw = json.dumps(pack).lower()
        assert "supplier-live proof" not in raw or "never" in raw

    def test_contradictory_candidate_ids_are_labeled_and_do_not_bind_customer_language(self):
        data = _load_fixture("adversarial_contradictory_sources.json")
        pack = build_site_draft_pack(
            launch_draft_pack=data["launch_draft_pack"],
            opportunity_synthesis=data["opportunity_synthesis"],
            consumer_attention=data["consumer_attention"],
            supplier_feasibility=data["supplier_feasibility"],
        ).to_dict()
        assert pack["evidence_attribution_summary"]["contradictory_candidate_ids"] is True
        attrs = _all_attributions(pack)
        assert any(attr["evidence_class"] == "contradictory" for attr in attrs)
        pages_raw = json.dumps(pack["pages"])
        assert "beta-only customer language must not bind" not in pages_raw
        assert "beta landing hint must not bind" not in pages_raw
        assert pack["evidence_attribution_summary"]["supplier_live_claims"] is False

    def test_stale_fixture_and_manual_supplier_never_become_live_proof(self):
        data = _load_fixture("adversarial_stale_fixture_as_live.json")
        pack = build_site_draft_pack(
            launch_draft_pack=data["launch_draft_pack"],
            opportunity_synthesis=data["opportunity_synthesis"],
            marketplace_trends=data["marketplace_trends"],
            supplier_feasibility=data["supplier_feasibility"],
            consumer_attention=data["consumer_attention"],
        ).to_dict()
        sources = pack["evidence_attribution_summary"]["sources"]
        assert sources["opportunity_synthesis"]["evidence_class"] == "stale"
        assert sources["marketplace_trends"]["evidence_class"] == "stale"
        assert sources["supplier_feasibility"]["evidence_class"] == "stale"
        assert sources["consumer_attention"]["evidence_class"] == "manual_import"
        # launch may say live_readonly, but site drafts must not emit observed supplier-live proof
        assert sources["launch_draft_pack"]["evidence_class"] == "derived"
        attrs = _all_attributions(pack)
        supplier_attrs = [attr for attr in attrs if attr["claim_role"] == "supplier_context"]
        assert supplier_attrs
        assert all(attr["evidence_class"] in {"stale", "missing", "fixture", "manual_import", "derived", "unavailable"} for attr in supplier_attrs)
        assert pack["evidence_attribution_summary"]["supplier_live_claims"] is False
        assert pack["evidence_attribution_summary"]["fixture_or_manual_treated_as_live"] is False
        assert "supplier_proof_ready" in pack["deployment_readiness"]["blockers"]
        assert pack["approval_checklist"]["publishing_authorized"] is False

    def test_missing_sources_surface_missing_or_assumed_classes(self, inputs):
        launch, synthesis, *_ = inputs
        pack = build_site_draft_pack(launch_draft_pack=launch, opportunity_synthesis=synthesis).to_dict()
        sources = pack["evidence_attribution_summary"]["sources"]
        assert sources["marketplace_trends"]["evidence_class"] == "missing"
        assert sources["supplier_feasibility"]["evidence_class"] == "missing"
        assert sources["consumer_attention"]["evidence_class"] == "missing"
        classes = {attr["evidence_class"] for attr in _all_attributions(pack)}
        assert "missing" in classes or "assumed" in classes
        assert pack["evidence_attribution_summary"]["supplier_live_claims"] is False
