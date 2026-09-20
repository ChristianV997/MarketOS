"""Platform-neutral website, store, and funnel blueprints.

This module is intentionally a portable planning layer.  It borrows the
content and safety language from the existing commerce packets, then emits
route manifests, composable sections, CMS models, and draft-shaped platform
payloads.  It never writes to a platform, hosting account, domain, analytics
property, or storefront.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, Mapping

VERSION = "site-draft-builder-v1"
UNKNOWN = "TBD — confirm before publishing."
SITE_TYPES = frozenset(
    {
        "ecommerce_store",
        "single_product_landing_page",
        "category_validation_site",
        "service_business_website",
        "manufacturer_catalog_site",
        "lead_generation_funnel",
        "campaign_microsite",
    }
)
PROVENANCE = frozenset({"observed", "derived", "assumed", "unavailable", "fixture", "manual_import"})


def _safe(value: Any) -> Any:
    if "DraftPlatformPayload" in globals() and isinstance(value, DraftPlatformPayload):
        return _safe(value.payload)
    if is_dataclass(value):
        return {item.name: _safe(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_safe(item) for item in value]
    return value


def _text(value: Any, limit: int = 320) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _list(value: Any, limit: int = 12) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [_text(item, 180) for item in value if _text(item, 180)][:limit]


def _context(context: Mapping[str, Any] | None) -> dict[str, Any]:
    source = dict(context or {})
    return {
        "business_name": _text(source.get("business_name") or source.get("brand_name") or "MarketOS Draft", 100),
        "brand_name": _text(source.get("brand_name") or source.get("business_name") or "MarketOS Draft", 100),
        "industry": _text(source.get("industry") or "TBD industry", 100),
        "business_type": _text(source.get("business_type") or "ecommerce", 80),
        "site_type": _text(source.get("site_type") or "ecommerce_store", 80),
        "target_country": _text(source.get("target_country") or "TBD", 60),
        "target_language": _text(source.get("target_language") or source.get("language") or "en", 16),
        "target_customer": _text(source.get("target_customer") or "TBD customer segment", 160),
        "primary_goal": _text(source.get("primary_goal") or "validate the offer and collect qualified intent", 180),
        "secondary_goal": _text(source.get("secondary_goal") or "capture evidence for the next review", 180),
        "tone": _text(source.get("tone") or "clear and evidence-led", 100),
        "currency": _text(source.get("currency") or "USD", 8).upper(),
        "domain_status": _text(source.get("domain_status") or "TBD — confirm domain ownership.", 140),
        "preferred_platform": _text(source.get("preferred_platform") or "platform-neutral draft", 100),
        "preferred_stack": _text(source.get("preferred_stack") or "static or existing CMS", 100),
        "shipping_policy_text": _text(source.get("shipping_policy_text") or UNKNOWN, 240),
        "return_policy_text": _text(source.get("return_policy_text") or UNKNOWN, 240),
        "privacy_policy_status": _text(source.get("privacy_policy_status") or "TBD — policy review required.", 140),
        "terms_status": _text(source.get("terms_status") or "TBD — policy review required.", 140),
        "contact_email": _text(source.get("contact_email") or UNKNOWN, 140),
        "phone": _text(source.get("phone") or UNKNOWN, 80),
        "location": _text(source.get("location") or UNKNOWN, 140),
        "service_area": _text(source.get("service_area") or UNKNOWN, 140),
        "lead_capture_offer": _text(source.get("lead_capture_offer") or "Evidence-led guide or consultation request — confirm before publishing.", 180),
        "prohibited_claims": _list(source.get("prohibited_claims"), 30),
        "required_disclaimers": _list(source.get("required_disclaimers"), 30),
    }


def _candidate(source: Mapping[str, Any] | None, launch: Mapping[str, Any] | None) -> tuple[str, str, str, list[str], list[str], list[str]]:
    source = dict(source or {})
    launch = dict(launch or {})
    candidate_id = _text(source.get("top_candidate_id") or launch.get("candidate_id") or "candidate", 100)
    title = _text(source.get("top_candidate_title") or launch.get("candidate_title") or "Product or service candidate", 140)
    synthesis = source.get("candidates") or []
    candidate = next((item for item in synthesis if isinstance(item, Mapping) and item.get("candidate_id") == candidate_id), {})
    query = _text(candidate.get("query") or title, 160)
    hooks = _list(source.get("top_hooks") or launch.get("ad_creatives", {}).get("hooks"), 10)
    pains = _list(source.get("top_pain_points"), 6)
    angles = _list(source.get("top_ad_angles") or launch.get("ad_creatives", {}).get("angles"), 8)
    return candidate_id, title, query, hooks, pains, angles


@dataclass(frozen=True)
class RouteManifest:
    routes: tuple[Mapping[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return _safe(self)


@dataclass(frozen=True)
class SiteMapDraft:
    site_type: str
    primary_routes: tuple[str, ...]
    secondary_routes: tuple[str, ...]
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _safe(self)


@dataclass(frozen=True)
class NavigationDraft:
    primary_items: tuple[Mapping[str, str], ...]
    footer_items: tuple[Mapping[str, str], ...]
    utility_items: tuple[Mapping[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return _safe(self)


@dataclass(frozen=True)
class CMSBinding:
    model: str
    field: str
    provenance: str = "unavailable"

    def __post_init__(self) -> None:
        if self.provenance not in PROVENANCE:
            raise ValueError(f"unsupported CMS provenance: {self.provenance}")


@dataclass(frozen=True)
class SectionBlockDraft:
    block_type: str
    content: Mapping[str, Any]
    settings: Mapping[str, Any]
    asset_placeholder: str
    cms_binding: CMSBinding | None
    evidence_note: str
    approval_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _safe(self)


@dataclass(frozen=True)
class PageSectionDraft:
    section_id: str
    section_type: str
    headline: str
    body: str
    cta: str
    blocks: tuple[SectionBlockDraft, ...]
    asset_note: str
    evidence_source_note: str
    risk_note: str
    unknowns: tuple[str, ...]
    approval_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _safe(self)


@dataclass(frozen=True)
class PageDraft:
    page_id: str
    page_type: str
    route: str
    goal: str
    target_user: str
    sections: tuple[PageSectionDraft, ...]
    seo_title: str
    meta_description: str
    primary_keyword: str
    secondary_keywords: tuple[str, ...]
    conversion_goal: str
    required_assets: tuple[str, ...]
    evidence_notes: tuple[str, ...]
    approval_blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _safe(self)


@dataclass(frozen=True)
class SectionSchema:
    section_type: str
    required_blocks: tuple[str, ...]
    optional_blocks: tuple[str, ...]
    settings_schema: Mapping[str, Any]
    cms_bindings: tuple[CMSBinding, ...]
    asset_requirements: tuple[str, ...]
    approval_required_fields: tuple[str, ...]
    platform_mapping: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        return _safe(self)


@dataclass(frozen=True)
class BlockSchema:
    block_type: str
    fields: Mapping[str, Any]
    settings_schema: Mapping[str, Any]
    asset_requirements: tuple[str, ...]
    platform_mapping: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        return _safe(self)


@dataclass(frozen=True)
class PlatformMapping:
    platform: str
    section_name: str
    notes: str
    status: str = "draft"

    def to_dict(self) -> dict[str, Any]:
        return _safe(self)


@dataclass(frozen=True)
class CatalogDraft:
    products: tuple[Mapping[str, Any], ...]
    collections: tuple[Mapping[str, Any], ...]
    attributes: tuple[Mapping[str, Any], ...]
    unknowns: tuple[str, ...]


@dataclass(frozen=True)
class ProductPageDraft:
    title: str
    route: str
    fields: Mapping[str, Any]


@dataclass(frozen=True)
class CollectionPageDraft:
    title: str
    route: str
    fields: Mapping[str, Any]


@dataclass(frozen=True)
class ServicePageDraft:
    title: str
    route: str
    fields: Mapping[str, Any]


@dataclass(frozen=True)
class LeadCaptureDraft:
    offer: str
    fields: tuple[Mapping[str, Any], ...]
    consent_note: str
    thank_you_route: str


@dataclass(frozen=True)
class SEOPlanDraft:
    primary_keywords: tuple[str, ...]
    secondary_keywords: tuple[str, ...]
    page_titles: Mapping[str, str]
    meta_descriptions: Mapping[str, str]
    url_slugs: Mapping[str, str]
    schema_suggestions: tuple[str, ...]
    internal_linking_plan: tuple[str, ...]
    content_gaps: tuple[str, ...]
    seo_risks: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _safe(self)


@dataclass(frozen=True)
class AnalyticsPlanDraft:
    events_to_track: tuple[str, ...]
    conversion_events: tuple[str, ...]
    funnel_steps: tuple[str, ...]
    recommended_utm_fields: tuple[str, ...]
    ad_platform_pixel_placeholders: tuple[str, ...]
    privacy_consent_notes: tuple[str, ...]
    dashboard_metrics: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _safe(self)


@dataclass(frozen=True)
class ConversionTestPlan:
    tests: tuple[Mapping[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return _safe(self)


@dataclass(frozen=True)
class CMSModelDraft:
    model_name: str
    fields: Mapping[str, Any]
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...]
    unknown_fields: tuple[str, ...]
    approval_required_fields: tuple[str, ...]
    example_item: Mapping[str, Any]
    platform_mapping: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        return _safe(self)


@dataclass(frozen=True)
class CMSContentModel:
    models: tuple[CMSModelDraft, ...]

    def to_dict(self) -> dict[str, Any]:
        return _safe(self)


@dataclass(frozen=True)
class DraftPlatformPayload:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return _safe(self.payload)


class StaticSitePayload(DraftPlatformPayload):
    pass


class ShopifyThemeDraftPayload(DraftPlatformPayload):
    pass


class MedusaStorefrontDraftPayload(DraftPlatformPayload):
    pass


class WooCommerceDraftPayload(DraftPlatformPayload):
    pass


class WebflowCMSDraftPayload(DraftPlatformPayload):
    pass


class WixHeadlessDraftPayload(DraftPlatformPayload):
    pass


class SquarespaceDraftPayload(DraftPlatformPayload):
    pass


class CarrdMicrositePayload(DraftPlatformPayload):
    pass


@dataclass(frozen=True)
class DeploymentReadinessChecklist:
    checks: Mapping[str, Mapping[str, Any]]
    overall_status: str
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _safe(self)


@dataclass(frozen=True)
class SiteApprovalChecklist:
    items: tuple[str, ...]
    blockers: tuple[str, ...]
    publishing_authorized: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _safe(self)


@dataclass(frozen=True)
class SiteRiskReview:
    conversion_risk: tuple[str, ...]
    copy_claim_risk: tuple[str, ...]
    supplier_risk: tuple[str, ...]
    shipping_risk: tuple[str, ...]
    policy_legal_risk: tuple[str, ...]
    platform_readiness_risk: tuple[str, ...]
    asset_quality_risk: tuple[str, ...]
    tracking_privacy_risk: tuple[str, ...]
    seo_risk: tuple[str, ...]
    customer_support_risk: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _safe(self)


@dataclass(frozen=True)
class SiteDraftPack:
    report_version: str
    generated_at: str
    candidate_id: str
    candidate_title: str
    business_type: str
    site_type: str
    evidence_mode: str
    source_launch_draft_pack: str
    source_opportunity_synthesis: str
    site_strategy: Mapping[str, Any]
    route_manifest: RouteManifest
    site_map: SiteMapDraft
    navigation: NavigationDraft
    pages: tuple[PageDraft, ...]
    section_library: Mapping[str, Any]
    catalog: CatalogDraft
    cms_content_model: CMSContentModel
    lead_capture: LeadCaptureDraft
    seo_plan: SEOPlanDraft
    analytics_plan: AnalyticsPlanDraft
    conversion_test_plan: ConversionTestPlan
    platform_payloads: Mapping[str, DraftPlatformPayload]
    deployment_readiness: DeploymentReadinessChecklist
    approval_checklist: SiteApprovalChecklist
    risk_review: SiteRiskReview
    operator_notes: tuple[str, ...]
    client_summary: str
    market_access: Mapping[str, Any] = field(default_factory=dict)
    read_only: bool = True
    network_calls: bool = False
    mutated: bool = False
    published: bool = False
    domains_changed: bool = False
    hosting_changed: bool = False
    shopify_mutated: bool = False
    medusa_mutated: bool = False
    woocommerce_mutated: bool = False
    webflow_mutated: bool = False
    wix_mutated: bool = False
    squarespace_mutated: bool = False
    ads_launched: bool = False
    orders_created: bool = False
    payments_created: bool = False
    customer_messages_sent: bool = False

    def __post_init__(self) -> None:
        flags = (self.network_calls, self.mutated, self.published, self.domains_changed, self.hosting_changed, self.shopify_mutated, self.medusa_mutated, self.woocommerce_mutated, self.webflow_mutated, self.wix_mutated, self.squarespace_mutated, self.ads_launched, self.orders_created, self.payments_created, self.customer_messages_sent)
        if not self.read_only or any(flags):
            raise ValueError("site draft packs are offline, read-only, and unpublished")
        if self.site_type not in SITE_TYPES:
            raise ValueError(f"unsupported site type: {self.site_type}")

    def to_dict(self) -> dict[str, Any]:
        result = _safe(self)
        result.update({"read_only": True, "network_calls": False, "mutated": False, "published": False, "domains_changed": False, "hosting_changed": False, "shopify_mutated": False, "medusa_mutated": False, "woocommerce_mutated": False, "webflow_mutated": False, "wix_mutated": False, "squarespace_mutated": False, "ads_launched": False, "orders_created": False, "payments_created": False, "customer_messages_sent": False})
        return result


def _route_specs(site_type: str, title: str) -> list[dict[str, Any]]:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "candidate"
    maps = {
        "ecommerce_store": [("/", "home", "Home", "Orient visitors and route them to products", "product detail review"), (f"/products/{slug}", "product_page", title, "Explain the product and hand off to checkout", "checkout handoff"), ("/collections/all", "collection_page", "Catalog", "Group products for discovery", "collection exploration"), ("/search", "catalog_page", "Search", "Help visitors find relevant products", "product discovery"), ("/faq", "faq", "FAQ", "Resolve evidence-backed objections", "confidence"), ("/shipping-returns", "policy", "Shipping and Returns", "Set verified expectations", "policy review"), ("/contact", "contact", "Contact", "Offer a human contact path", "contact"), ("/privacy", "policy", "Privacy", "Provide policy placeholder", "policy review"), ("/terms", "policy", "Terms", "Provide terms placeholder", "policy review"), ("/cart", "cart_handoff", "Cart", "Hand off to a configured cart", "cart handoff")],
        "single_product_landing_page": [(f"/", "landing_page", title, "Present one product hypothesis", "lead or checkout handoff"), ("/faq", "faq", "FAQ", "Resolve objections", "confidence"), ("/checkout", "checkout_handoff", "Checkout Handoff", "Document the approved handoff", "checkout handoff"), ("/thank-you", "thank_you", "Thank You", "Confirm the next approved step", "follow-up")],
        "category_validation_site": [("/", "home", "Category Validation", "Explain the validation question", "email capture"), ("/category", "category_overview", "Category Overview", "Frame the category", "category exploration"), ("/candidates", "candidate_grid", "Top Candidates", "Compare candidates", "candidate review"), ("/compare", "comparison", "Comparison", "Make evidence gaps visible", "comparison"), ("/subscribe", "lead_capture", "Email Capture", "Collect permissioned interest", "lead capture"), ("/faq", "faq", "FAQ", "Answer validation questions", "confidence"), ("/results", "validation_results", "Validation Results", "Present approved findings", "results review")],
        "service_business_website": [("/", "home", "Home", "Explain the service and route to contact", "lead capture"), ("/services", "services", "Services", "Present service categories", "service exploration"), ("/services/detail", "service_detail", "Service Detail", "Explain one service", "lead capture"), ("/about", "about", "About", "Explain the business", "trust"), ("/proof", "proof_placeholder", "Proof", "Hold approved proof placeholders", "trust"), ("/service-area", "service_area", "Service Area", "Clarify coverage", "qualification"), ("/faq", "faq", "FAQ", "Resolve service objections", "confidence"), ("/contact", "contact", "Contact", "Capture a qualified inquiry", "lead capture")],
        "manufacturer_catalog_site": [("/", "home", "Home", "Explain catalog scope", "catalog exploration"), ("/catalog", "catalog", "Catalog", "Browse products", "product discovery"), ("/catalog/category", "category_detail", "Category Detail", "Describe a category", "category exploration"), (f"/catalog/{slug}", "product_spec", title, "Show verified technical information", "request quote"), ("/industries", "industries", "Industries Served", "Map use cases", "industry fit"), ("/request-quote", "quote_request", "Request Quote", "Capture a qualified request", "quote capture"), ("/distributors", "distributor_contact", "Distributor Contact", "Route channel inquiries", "contact")],
        "lead_generation_funnel": [("/", "landing_page", "Offer", "Present the lead offer", "lead capture"), ("/lead-magnet", "lead_magnet", "Lead Magnet", "Explain the exchange", "lead capture"), ("/qualify", "qualification_form", "Qualification", "Collect only necessary details", "qualification"), ("/thank-you", "thank_you", "Thank You", "Set follow-up expectations", "follow-up")],
        "campaign_microsite": [("/", "campaign_one_page", "Campaign", "Present the campaign", "campaign conversion"), ("#offer", "offer_event", "Offer / Event", "Explain the approved offer", "offer review"), ("#capture", "lead_capture", "Lead Capture", "Collect permissioned interest", "lead capture"), ("#embed", "embed_widget", "Embed / Widget", "Hold approved embed placeholder", "engagement"), ("#handoff", "qr_link_handoff", "QR / Link Handoff", "Document tracking handoff", "campaign attribution")],
    }
    return [{"route": route, "page_id": (re.sub(r"[^a-z0-9]+", "_", route.strip("/").lower()).strip("_") or "home") + "_page", "page_type": page_type, "title": page_title, "purpose": purpose, "conversion_goal": goal, "requires_approval": True, "platform_notes": "Conceptual route only; no platform route was created."} for route, page_type, page_title, purpose, goal in maps[site_type]]


def _section_types(page_type: str, site_type: str) -> tuple[str, ...]:
    if page_type in {"home", "landing_page", "campaign_one_page"}:
        return ("hero", "problem", "solution", "benefits", "demo_section", "social_proof_placeholder", "offer_section", "faq", "final_cta")
    if page_type in {"product_page", "product_spec", "service_detail"}:
        return ("hero", "benefits", "how_it_works", "comparison", "demo_section", "faq", "trust_policies", "final_cta")
    if page_type in {"collection_page", "catalog", "candidate_grid", "services", "category_overview", "category_detail"}:
        return ("hero", "collection_grid", "comparison", "faq", "final_cta")
    if page_type in {"contact", "lead_capture", "qualification_form", "quote_request", "request_quote"}:
        return ("hero", "lead_capture", "trust_policies", "contact", "final_cta")
    if page_type in {"faq", "policy", "thank_you", "checkout_handoff", "proof_placeholder", "validation_results", "about", "service_area", "industries", "distributor_contact", "lead_magnet", "offer_event", "embed_widget", "qr_link_handoff", "comparison"}:
        return ("hero", "problem", "faq", "final_cta")
    return ("hero", "benefits", "final_cta")


def _section(section_type: str, title: str, hooks: list[str], pains: list[str], site_type: str) -> PageSectionDraft:
    headlines = {"hero": title, "problem": "The customer task is worth making clearer", "solution": "A focused path from need to next step", "benefits": "What the draft should make easy to understand", "how_it_works": "Show the workflow", "product_grid": "Explore the catalog", "collection_grid": "Browse the collection", "comparison": "Compare the important trade-offs", "social_proof_placeholder": "Approved proof goes here", "demo_section": "Let the product or service demonstrate", "offer_section": "Review the offer", "faq": "Questions customers may ask", "lead_capture": "Get the next useful detail", "final_cta": "Review the next step", "contact": "Start a conversation", "trust_policies": "Clear policies build trust"}
    body = {"problem": pains[0] if pains else "Use the supplied customer language without exaggeration.", "hero": hooks[0] if hooks else f"Draft positioning for {title}", "lead_capture": "Collect only the information needed for the stated follow-up.", "contact": "Contact details remain TBD until the client supplies approved information."}.get(section_type, "Use verified evidence, clear provenance, and a human approval step.")
    block_type = {"hero": "hero", "benefits": "benefits_grid", "collection_grid": "collection_grid", "product_grid": "product_grid", "comparison": "comparison_table", "faq": "faq", "lead_capture": "lead_form", "offer_section": "pricing_offer", "social_proof_placeholder": "social_proof_placeholder", "demo_section": "demo", "final_cta": "final_cta", "contact": "contact", "trust_policies": "trust_policies", "problem": "problem_solution"}.get(section_type, "rich_text")
    block = SectionBlockDraft(block_type, {"headline": headlines.get(section_type, section_type), "body": body}, {"visibility": "draft", "alignment": "TBD"}, "TBD — approved asset required.", CMSBinding("Page", "section_content", "derived"), "Built from supplied synthesis/launch evidence; not a live proof claim.")
    unknowns = ("Approved assets are missing.", "Policy and platform details remain TBD.")
    if section_type in {"social_proof_placeholder", "comparison"}:
        unknowns = (*unknowns, "No testimonials, reviews, logos, or unsupported competitor claims are supplied.")
    return PageSectionDraft(section_type, section_type, headlines.get(section_type, section_type), body, "Review draft", (block,), "TBD — approved asset required.", "Existing evidence reports and client context only.", "Do not publish unsupported claims or proof.", unknowns)


def _page(spec: Mapping[str, Any], title: str, context: Mapping[str, Any], hooks: list[str], pains: list[str], site_type: str) -> PageDraft:
    sections = tuple(_section(item, title, hooks, pains, site_type) for item in _section_types(str(spec["page_type"]), site_type))
    return PageDraft(str(spec["page_id"]), str(spec["page_type"]), str(spec["route"]), str(spec["purpose"]), context["target_customer"], sections, _text(f"{spec['title']} | {context['brand_name']}", 70), _text(f"Draft page for {spec['purpose']}. Confirm claims, policies, and assets before publishing.", 155), _text(title, 70), tuple(dict.fromkeys([_text(title, 70), _text(context["industry"], 70), _text(context["target_customer"], 70)])), str(spec["conversion_goal"]), ("Approved hero asset", "Approved logo/brand asset", "Policy or proof asset where applicable"), ("Evidence is fixture/manual unless supplied otherwise.", "Unknowns remain visibly marked TBD."), ("Human approval required for copy, claims, assets, SEO, and publishing." ,))


def _section_library() -> dict[str, Any]:
    names = {"hero": ("headline", "body", "cta"), "problem_solution": ("problem", "solution"), "benefits_grid": ("benefit_items",), "comparison_table": ("rows",), "product_grid": ("items",), "collection_grid": ("collections",), "pricing_offer": ("price_band", "offer_copy"), "faq": ("questions",), "lead_form": ("fields", "consent"), "social_proof_placeholder": ("proof_type",), "demo": ("steps",), "final_cta": ("headline", "cta"), "contact": ("email", "phone", "location"), "trust_policies": ("privacy", "terms", "returns")}
    platforms = {platform: f"Conceptual {platform} section/block mapping; export remains draft." for platform in ("static", "shopify", "medusa", "woocommerce", "webflow", "wix", "squarespace", "carrd")}
    schemas = {}
    for name, required in names.items():
        schemas[name] = SectionSchema(name, required, ("asset", "settings"), {"visible": {"type": "boolean", "default": False}, "spacing": {"type": "string", "default": "TBD"}}, (CMSBinding("Page", "content", "derived"), CMSBinding("Asset", "reference", "unavailable")), ("Approved asset placeholder",), ("copy", "claims", "assets"), platforms).to_dict()
    schemas["block_schemas"] = {name: BlockSchema(name, {field: "TBD" for field in required}, {"visible": "boolean", "theme": "TBD"}, ("Approved asset placeholder",), platforms).to_dict() for name, required in names.items()}
    return schemas


def _cms_models() -> CMSContentModel:
    definitions = {
        "Product": ("title", "handle", "description", "sku", "price"), "Variant": ("title", "sku", "price", "inventory"), "Collection": ("title", "handle", "description"), "Offer": ("name", "price", "terms"), "FAQ": ("question", "answer"), "Policy": ("policy_type", "body"), "Page": ("title", "route", "sections"), "Section": ("section_type", "content", "settings"), "Asset": ("asset_type", "url_or_placeholder", "rights"), "LeadForm": ("name", "fields", "consent"), "Campaign": ("name", "tracking_fields", "dates"), "TestVariant": ("test_id", "hypothesis", "metric"), "Service": ("name", "description", "price_or_quote"), "ServiceArea": ("name", "coverage"), "QuoteRequest": ("name", "email", "requirements"),
    }
    models = []
    for name, required in definitions.items():
        optional = ("image", "notes", "status")
        models.append(CMSModelDraft(name, {field: "string_or_structured_value" for field in required + optional}, required, optional, ("provider_id", "verified_at"), ("copy", "claims", "policy"), {field: UNKNOWN for field in required}, {platform: f"Map {name} to {platform} CMS concept; export remains draft." for platform in ("static", "shopify", "medusa", "woocommerce", "webflow", "wix", "squarespace", "carrd")}))
    return CMSContentModel(tuple(models))


def _seo(title: str, context: Mapping[str, Any], pages: tuple[PageDraft, ...]) -> SEOPlanDraft:
    keywords = tuple(dict.fromkeys([_text(title, 70), _text(context["industry"], 70), _text(context["target_customer"], 70)]))
    titles = {page.route: _text(f"{page.seo_title}", 70) for page in pages}
    metas = {page.route: page.meta_description for page in pages}
    slugs = {page.page_id: page.route for page in pages}
    return SEOPlanDraft(keywords[:1], keywords[1:], titles, metas, slugs, ("Product or Service schema only after facts are confirmed.", "Organization or LocalBusiness schema only with client-approved data."), ("Link the home page to the primary conversion page.", "Link product/service detail pages to FAQ and contact/policy pages."), ("Verified specifications, policies, proof assets, and client-owned facts.",), ("No search volume, rank, or traffic claims are inferred.", "Schema and metadata require human approval."))


def _analytics(site_type: str) -> AnalyticsPlanDraft:
    steps = ("landing_view", "engaged_section", "primary_cta_view", "form_started", "form_submitted") if site_type in {"lead_generation_funnel", "campaign_microsite", "service_business_website"} else ("landing_view", "product_view", "collection_view", "add_to_cart_intent", "checkout_handoff")
    return AnalyticsPlanDraft(("page_view", "section_view", "cta_view", "form_start", "form_submit", "policy_view"), ("lead_submit", "quote_request", "checkout_handoff"), steps, ("utm_source", "utm_medium", "utm_campaign", "utm_content"), ("META_PIXEL_ID_TBD", "TIKTOK_PIXEL_ID_TBD", "ANALYTICS_ID_TBD"), ("Obtain consent where required before analytics or advertising measurement.", "No pixel is installed by this draft."), ("conversion rate", "CTA engagement", "form completion", "checkout handoff rate", "policy-page views"))


def _conversion(thresholds: Mapping[str, Any] | None, pages: tuple[PageDraft, ...]) -> ConversionTestPlan:
    thresholds = dict(thresholds or {})
    tests = []
    for index, page in enumerate(pages[:5], 1):
        tests.append({"test_id": f"site-test-{index}", "page": page.route, "variant": "headline_or_cta_v2", "hypothesis": "Clearer evidence-led copy will improve qualified next-step intent.", "traffic_source_note": "Traffic source is TBD; no spend or traffic is created.", "target_metric": page.conversion_goal, "kill_threshold": {"ctr_below": thresholds.get("kill_if_ctr_below", UNKNOWN), "cpa_above": thresholds.get("kill_if_cpa_above", UNKNOWN)}, "scale_threshold": {"cpa_below": thresholds.get("scale_if_cpa_below", UNKNOWN), "margin_above": thresholds.get("scale_if_margin_above", UNKNOWN)}, "required_sample_note": "Use a pre-approved sample plan; thresholds are planning assumptions.", "risk_note": "Review claims, privacy, policies, and supplier proof first."})
    return ConversionTestPlan(tuple(tests))


def _payloads(site_type: str, title: str, pages: tuple[PageDraft, ...], navigation: NavigationDraft, seo: SEOPlanDraft, analytics: AnalyticsPlanDraft) -> dict[str, DraftPlatformPayload]:
    route_data = [page.to_dict() for page in pages]
    static = StaticSitePayload({"site_config": {"site_type": site_type, "status": "draft", "domain": UNKNOWN}, "routes": route_data, "pages": route_data, "sections": [], "assets_placeholder": ["TBD"], "seo_metadata": seo.to_dict(), "analytics_placeholder": analytics.to_dict(), "forms_placeholder": [{"status": "draft"}], "status": "draft"})
    shopify = ShopifyThemeDraftPayload({"theme_config_placeholder": {"status": "draft"}, "templates": ["index", "product", "collection", "page"], "sections": ["hero", "product_grid", "faq", "final_cta"], "section_settings": {"status": "TBD"}, "navigation": navigation.to_dict(), "product_templates": ["TBD"], "collection_templates": ["TBD"], "metafields": {"marketos_draft": True}, "seo_fields": seo.to_dict(), "status": "draft"})
    medusa = MedusaStorefrontDraftPayload({"storefront_config": {"status": "draft", "stack": "TBD"}, "routes": [page.route for page in pages], "product_pages": [page.page_id for page in pages if page.page_type in {"product_page", "product_spec"}], "collection_pages": [page.page_id for page in pages if "collection" in page.page_type or "catalog" in page.page_type], "metadata": {"marketos_draft": True}, "sales_channel_placeholder": UNKNOWN, "cart_handoff": {"status": "TBD"}, "checkout_handoff": {"status": "TBD"}, "status": "draft"})
    woo = WooCommerceDraftPayload({"pages": [page.page_id for page in pages], "products_placeholder": [title], "categories_placeholder": ["TBD"], "attributes_placeholder": ["TBD"], "seo_fields": seo.to_dict(), "status": "draft"})
    webflow = WebflowCMSDraftPayload({"collections": ["Product", "Collection", "Page", "FAQ", "LeadForm"], "fields": {"status": "TBD"}, "items_placeholder": [title], "collection_pages": [page.route for page in pages], "status": "draft"})
    wix = WixHeadlessDraftPayload({"business_data_placeholders": {"business_name": UNKNOWN, "contact": UNKNOWN}, "products_or_services": [title], "content_collections": ["Page", "FAQ", "Service"], "lead_forms": ["TBD"], "visibility": "hidden_or_draft", "status": "draft"})
    squarespace = SquarespaceDraftPayload({"pages": [page.route for page in pages], "products": [title], "variants": ["TBD"], "images_placeholder": ["TBD"], "inventory_placeholder": ["TBD"], "status": "draft"})
    carrd = CarrdMicrositePayload({"one_page_sections": [section.section_type for section in pages[0].sections] if pages else [], "forms": ["TBD"], "embed_placeholders": ["TBD"], "custom_code_placeholder": "TBD — no code is installed.", "tracking_placeholder": analytics.to_dict(), "status": "draft"})
    return {"static_site": static, "shopify_theme": shopify, "medusa_storefront": medusa, "woocommerce": woo, "webflow_cms": webflow, "wix_headless": wix, "squarespace": squarespace, "carrd_microsite": carrd}


def _readiness(context: Mapping[str, Any], launch: Mapping[str, Any] | None, pages: tuple[PageDraft, ...]) -> DeploymentReadinessChecklist:
    supplier_ready = bool(launch and launch.get("evidence_mode") in {"live_readonly", "authenticated_live"} and "supplier proof" not in str(launch.get("approval_checklist", {}).get("blockers", [])).lower())
    checks = {
        "domain_ready": {"status": "configured" if not str(context["domain_status"]).startswith("TBD") else "not_configured", "detail": context["domain_status"]},
        "hosting_selected": {"status": "not_configured", "detail": "No hosting call or selection was made."},
        "platform_selected": {"status": "configured" if context["preferred_platform"] != "platform-neutral draft" else "not_configured", "detail": context["preferred_platform"]},
        "policies_ready": {"status": "ready" if not any(str(context[key]).startswith("TBD") for key in ("privacy_policy_status", "terms_status")) else "blocked", "detail": "Privacy, terms, shipping, and returns require approval."},
        "products_or_services_approved": {"status": "blocked", "detail": "Content remains draft."},
        "supplier_proof_ready": {"status": "ready" if supplier_ready else "blocked", "detail": "Supplier proof remains a launch gate."},
        "images_assets_ready": {"status": "blocked", "detail": "Assets are placeholders."},
        "analytics_approved": {"status": "not_configured", "detail": "Analytics plan only; no installation."},
        "claims_approved": {"status": "blocked", "detail": "Human claims review required."},
        "checkout_status": {"status": "not_configured", "detail": "Checkout handoff is conceptual."},
        "shipping_returns_approved": {"status": "ready" if not context["shipping_policy_text"].startswith("TBD") and not context["return_policy_text"].startswith("TBD") else "blocked", "detail": "Policy approval required."},
        "privacy_terms_approved": {"status": "ready" if checks_placeholder(context) else "blocked", "detail": "Privacy and terms status is client-supplied only."},
    }
    blockers = tuple(key for key, value in checks.items() if value["status"] in {"blocked", "not_configured"})
    return DeploymentReadinessChecklist(checks, "ready" if not blockers else "partially_ready", blockers)


def checks_placeholder(context: Mapping[str, Any]) -> bool:
    return not str(context["privacy_policy_status"]).startswith("TBD") and not str(context["terms_status"]).startswith("TBD")


def _approval(context: Mapping[str, Any], readiness: DeploymentReadinessChecklist, launch: Mapping[str, Any] | None) -> SiteApprovalChecklist:
    items = ("client approved copy", "client approved claims", "supplier proof confirmed", "pricing approved", "shipping window approved", "return policy approved", "images/assets approved", "SEO metadata approved", "analytics/privacy approved", "draft payload approved", "publishing not authorized until final approval")
    blockers = list(readiness.blockers)
    if launch and launch.get("approval_checklist", {}).get("blockers"):
        blockers.extend(_list(launch["approval_checklist"]["blockers"], 8))
    return SiteApprovalChecklist(items, tuple(dict.fromkeys(blockers)), False)


def _risks(context: Mapping[str, Any], readiness: DeploymentReadinessChecklist) -> SiteRiskReview:
    return SiteRiskReview(("The primary conversion goal is a draft hypothesis.",), ("Claims and proof require approval.",), ("Supplier proof remains a blocker when absent.",), ("Shipping timing remains TBD until verified.",), ("Privacy, terms, and policy review are required.",), tuple(readiness.blockers), ("Assets are placeholders until approved.",), ("Consent and analytics configuration are not installed.", "No traffic or ranking claim is inferred."), ("SEO metadata and schema require review.",), ("Prepare support answers for objections and policies.",))


def build_site_draft_pack(*, launch_draft_pack: Mapping[str, Any] | None = None, opportunity_synthesis: Mapping[str, Any] | None = None, product_validation: Mapping[str, Any] | None = None, marketplace_trends: Mapping[str, Any] | None = None, supplier_feasibility: Mapping[str, Any] | None = None, consumer_attention: Mapping[str, Any] | None = None, client_context: Mapping[str, Any] | None = None, site_type: str | None = None) -> SiteDraftPack:
    context = _context(client_context)
    synthesis = dict(opportunity_synthesis or {})
    launch = dict(launch_draft_pack or {})
    selected_type = _text(site_type or context.get("site_type") or "ecommerce_store", 80)
    if selected_type not in SITE_TYPES:
        raise ValueError(f"unsupported site type: {selected_type}")
    candidate_id, title, query, hooks, pains, angles = _candidate(synthesis, launch)
    specs = _route_specs(selected_type, title)
    route_manifest = RouteManifest(tuple(specs))
    pages = tuple(_page(spec, title, context, hooks, pains, selected_type) for spec in specs)
    primary = tuple({"label": spec["title"], "route": spec["route"]} for spec in specs[:5])
    footer = ({"label": "Privacy", "route": "/privacy"}, {"label": "Terms", "route": "/terms"}, {"label": "Contact", "route": "/contact"})
    navigation = NavigationDraft(primary, footer, ({"label": "Review draft", "route": specs[0]["route"]},))
    primary_routes = tuple(spec["route"] for spec in specs)
    site_map = SiteMapDraft(selected_type, primary_routes[:5], primary_routes[5:], ("Routes are a portable manifest, not deployed routes.", "Each page requires human approval."))
    seo = _seo(title, context, pages)
    analytics = _analytics(selected_type)
    thresholds = synthesis.get("decision_thresholds") if isinstance(synthesis.get("decision_thresholds"), Mapping) else {}
    conversion = _conversion(thresholds, pages)
    readiness = _readiness(context, launch, pages)
    approval = _approval(context, readiness, launch)
    catalog = CatalogDraft(({"title": title, "sku": UNKNOWN, "price": UNKNOWN, "status": "draft"},), ({"title": "TBD category", "status": "draft"},), ({"name": "TBD attribute", "values": []},), ("Verified product/service facts", "Approved assets", "Policies",))
    lead = LeadCaptureDraft(context["lead_capture_offer"], ({"name": "name", "required": True}, {"name": "email", "required": True}, {"name": "consent", "required": True}), "Obtain consent before follow-up or measurement.", "/thank-you")
    payloads = _payloads(selected_type, title, pages, navigation, seo, analytics)
    strategy = {"primary_goal": context["primary_goal"], "secondary_goal": context["secondary_goal"], "tone": context["tone"], "preferred_platform": context["preferred_platform"], "preferred_stack": context["preferred_stack"], "evidence_note": "Site planning uses existing sanitized reports; it does not create new evidence."}
    evidence_mode = _text(synthesis.get("evidence_mode") or launch.get("evidence_mode") or "fixture_demo", 50)
    summary = f"{title} has a {selected_type} blueprint for {context['business_name']} based on {evidence_mode} evidence. It is implementation-ready planning material, not a published site or launch authorization."
    notes = ("No network calls were made.", "No route, domain, hosting, analytics, or platform mutation occurred.", "Replace every TBD field and complete approval blockers before implementation.")
    market_access = launch.get("market_access") or synthesis.get("market_access") or {}
    return SiteDraftPack(VERSION, "deterministic", candidate_id, title, context["business_type"], selected_type, evidence_mode, "launch_draft_pack" if launch else "not_supplied", "opportunity_synthesis" if synthesis else "not_supplied", strategy, route_manifest, site_map, navigation, pages, _section_library(), catalog, _cms_models(), lead, seo, analytics, conversion, payloads, readiness, approval, _risks(context, readiness), notes, summary, market_access=market_access)


def markdown(pack: Mapping[str, Any]) -> str:
    pages = pack.get("pages", [])
    lines = ["# Site Draft Pack", "", f"**Candidate:** {pack.get('candidate_title', UNKNOWN)}  ", f"**Site type:** `{pack.get('site_type', UNKNOWN)}`  ", f"**Evidence mode:** `{pack.get('evidence_mode', 'missing')}` — draft-only  ", f"**Status:** `{pack.get('deployment_readiness', {}).get('overall_status', 'partially_ready')}`", "", "## Site Strategy", "", str(pack.get("site_strategy", {})), "", "## Route Manifest", "", *[f"- `{item.get('route')}` — {item.get('page_type')}: {item.get('title')} → {item.get('conversion_goal')}" for item in pack.get("route_manifest", {}).get("routes", [])], "", "## Pages", "", *[f"### {page.get('title')}\n`{page.get('route')}` — {page.get('goal')}\nSections: {', '.join(section.get('section_type') for section in page.get('sections', []))}" for page in pages], "", "## CMS Content Model", "", *[f"- **{model.get('model_name')}**: {', '.join(model.get('required_fields', []))}" for model in pack.get("cms_content_model", {}).get("models", [])], "", "## SEO Plan", "", str(pack.get("seo_plan", {})), "", "## Analytics Plan", "", str(pack.get("analytics_plan", {})), "", "## Conversion Tests", "", *[f"- {test.get('test_id')}: {test.get('hypothesis')}" for test in pack.get("conversion_test_plan", {}).get("tests", [])], "", "## Deployment Blockers", "", *[f"- {item}" for item in pack.get("deployment_readiness", {}).get("blockers", [])], "", "## Approval Checklist", "", *[f"- [ ] {item}" for item in pack.get("approval_checklist", {}).get("items", [])], "", "This is a read-only blueprint. No platform, domain, hosting, analytics, advertising, checkout, order, payment, or messaging action occurred.", ""]
    return "\n".join(lines)


__all__ = ["CMSBinding", "CMSContentModel", "CMSModelDraft", "CatalogDraft", "CarrdMicrositePayload", "CollectionPageDraft", "ConversionTestPlan", "DeploymentReadinessChecklist", "LeadCaptureDraft", "MedusaStorefrontDraftPayload", "NavigationDraft", "PageDraft", "PageSectionDraft", "PlatformMapping", "ProductPageDraft", "RouteManifest", "SectionBlockDraft", "SectionSchema", "ServicePageDraft", "SiteApprovalChecklist", "SiteDraftPack", "SiteMapDraft", "SiteRiskReview", "StaticSitePayload", "ShopifyThemeDraftPayload", "WebflowCMSDraftPayload", "WixHeadlessDraftPayload", "WooCommerceDraftPayload", "SquarespaceDraftPayload", "build_site_draft_pack", "markdown"]
