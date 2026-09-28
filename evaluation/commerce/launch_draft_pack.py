"""Deterministic, draft-only launch assets built from existing evidence.

The launch pack is a consulting deliverable, not a publishing or activation
engine.  It turns the Product Opportunity Synthesis into human-reviewable copy,
creative briefs, and explicitly draft Shopify/Medusa-shaped payloads.  No
provider is called and no asset is published from this module.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Mapping

VERSION = "launch-draft-pack-v1"
UNKNOWN = "TBD — confirm before publishing."
SAFE_CLAIM_WORDS = frozenset({"guaranteed", "cure", "treat", "diagnose", "prevent", "FDA", "clinically proven", "risk-free"})


def _value(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _value(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_value(item) for item in value]
    return value


def _text(value: Any, limit: int = 320) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _list(value: Any, limit: int = 10) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [_text(item, 180) for item in value if _text(item, 180)][:limit]


def _number(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _money(value: Any, currency: str = "USD") -> str:
    number = _number(value)
    return f"{currency} {number:.2f}" if number is not None else UNKNOWN


def _candidate(synthesis: Mapping[str, Any]) -> Mapping[str, Any]:
    candidate_id = synthesis.get("top_candidate_id")
    candidates = synthesis.get("candidates") or []
    for item in candidates:
        if isinstance(item, Mapping) and item.get("candidate_id") == candidate_id:
            return item
    return candidates[0] if candidates and isinstance(candidates[0], Mapping) else {}


def _context(context: Mapping[str, Any] | None) -> dict[str, Any]:
    source = dict(context or {})
    prohibited = _list(source.get("prohibited_claims"), 30)
    return {
        "brand_name": _text(source.get("brand_name") or "MarketOS Draft", 80),
        "tone": _text(source.get("tone") or "clear and evidence-led", 100),
        "target_country": _text(source.get("target_country") or "TBD", 80),
        "currency": _text(source.get("currency") or "USD", 8).upper(),
        "target_customer": _text(source.get("target_customer") or "TBD customer segment", 140),
        "prohibited_claims": prohibited,
        "preferred_platform": _text(source.get("preferred_platform") or "Shopify or Medusa draft", 80),
        "language": _text(source.get("language") or "en", 12),
        "offer_constraints": _list(source.get("offer_constraints"), 20),
        "shipping_policy_text": _text(source.get("shipping_policy_text") or UNKNOWN, 240),
        "return_policy_text": _text(source.get("return_policy_text") or UNKNOWN, 240),
    }


def _safe_copy(value: str, prohibited: list[str]) -> str:
    result = _text(value)
    blocked = [*SAFE_CLAIM_WORDS, *prohibited]
    for word in blocked:
        if word and re.search(re.escape(word), result, re.IGNORECASE):
            result = re.sub(re.escape(word), "evidence-led", result, flags=re.IGNORECASE)
    return result


def _field(source: Mapping[str, Any], key: str, default: Any = UNKNOWN) -> Any:
    value = source.get(key)
    return default if value in (None, "", [], {}) else value


@dataclass(frozen=True)
class OfferStack:
    core_offer: str
    headline_value_proposition: str
    primary_promise: str
    secondary_benefits: tuple[str, ...]
    bundle_suggestions: tuple[str, ...]
    pricing_suggestion: Mapping[str, Any]
    discount_suggestion: str
    risk_reversal: str
    shipping_return_notes: tuple[str, ...]
    urgency_scarcity_guidance: str
    claim_safety_notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _value(self)


@dataclass(frozen=True)
class ProductListingDraft:
    title: str
    subtitle: str
    short_description: str
    long_description: str
    bullet_benefits: tuple[str, ...]
    features: tuple[str, ...]
    specifications: Mapping[str, Any]
    what_is_included: tuple[str, ...]
    shipping_note: str
    return_note: str
    risk_disclaimer: str
    seo_keywords: tuple[str, ...]
    image_brief: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _value(self)


@dataclass(frozen=True)
class LandingPageDraft:
    sections: Mapping[str, Mapping[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return _value(self)


@dataclass(frozen=True)
class AdCreativeDraft:
    angles: tuple[Mapping[str, Any], ...]
    hooks: tuple[str, ...]
    short_form_video_scripts: tuple[Mapping[str, Any], ...]
    static_ad_concepts: tuple[Mapping[str, Any], ...]
    meta_primary_text_options: tuple[str, ...]
    tiktok_reels_captions: tuple[str, ...]
    headline_options: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _value(self)


@dataclass(frozen=True)
class UGCBrief:
    brief_type: str
    creator_brief: str
    shot_list: tuple[str, ...]
    script_outline: tuple[str, ...]
    opening_hook: str
    demo_moments: tuple[str, ...]
    objection_handling_moment: str
    cta: str
    do_not_say_claims: tuple[str, ...]
    required_disclosures: tuple[str, ...]
    asset_checklist: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _value(self)


@dataclass(frozen=True)
class CreativeTestMatrix:
    rows: tuple[Mapping[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return _value(self)


@dataclass(frozen=True)
class FAQAndObjectionDraft:
    faqs: tuple[Mapping[str, str], ...]
    objections: tuple[Mapping[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return _value(self)


@dataclass(frozen=True)
class ShopifyDraftPayload:
    title: str
    body_html_or_markdown: str
    vendor: str
    product_type: str
    tags: tuple[str, ...]
    status: str
    variants: tuple[Mapping[str, Any], ...]
    options: tuple[Mapping[str, Any], ...]
    images_placeholder: tuple[Mapping[str, str], ...]
    seo_title: str
    seo_description: str
    metafields: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.status != "draft":
            raise ValueError("Shopify payload must remain draft")

    def to_dict(self) -> dict[str, Any]:
        return _value(self)


@dataclass(frozen=True)
class MedusaDraftPayload:
    title: str
    subtitle: str
    description: str
    handle: str
    status: str
    variants: tuple[Mapping[str, Any], ...]
    options: tuple[Mapping[str, Any], ...]
    metadata: Mapping[str, Any]
    sales_channels_placeholder: tuple[str, ...]
    images_placeholder: tuple[Mapping[str, str], ...]

    def __post_init__(self) -> None:
        if self.status != "draft":
            raise ValueError("Medusa payload must remain draft")

    def to_dict(self) -> dict[str, Any]:
        return _value(self)


@dataclass(frozen=True)
class LaunchApprovalChecklist:
    items: tuple[str, ...]
    blockers: tuple[str, ...]
    launch_authorized: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _value(self)


@dataclass(frozen=True)
class LaunchRiskReview:
    supplier_risk: tuple[str, ...]
    shipping_risk: tuple[str, ...]
    margin_risk: tuple[str, ...]
    claim_compliance_risk: tuple[str, ...]
    creative_risk: tuple[str, ...]
    market_saturation_risk: tuple[str, ...]
    customer_support_risk: tuple[str, ...]
    refund_risk: tuple[str, ...]
    platform_policy_risk: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _value(self)


@dataclass(frozen=True)
class LaunchDraftPack:
    report_version: str
    generated_at: str
    candidate_id: str
    candidate_title: str
    evidence_mode: str
    source_synthesis_report: str
    overall_recommendation: str
    launch_draft_status: str
    offer_stack: OfferStack
    product_listing: ProductListingDraft
    landing_page: LandingPageDraft
    ad_creatives: AdCreativeDraft
    ugc_briefs: tuple[UGCBrief, ...]
    creative_test_matrix: CreativeTestMatrix
    faq_and_objections: FAQAndObjectionDraft
    shopify_draft_payload: ShopifyDraftPayload
    medusa_draft_payload: MedusaDraftPayload
    approval_checklist: LaunchApprovalChecklist
    risk_review: LaunchRiskReview
    operator_notes: tuple[str, ...]
    client_summary: str
    market_access: Mapping[str, Any] = field(default_factory=dict)
    read_only: bool = True
    network_calls: bool = False
    mutated: bool = False
    published: bool = False
    ads_launched: bool = False
    orders_created: bool = False
    payments_created: bool = False
    customer_messages_sent: bool = False

    def __post_init__(self) -> None:
        if not self.read_only or self.network_calls or self.mutated or self.published or self.ads_launched or self.orders_created or self.payments_created or self.customer_messages_sent:
            raise ValueError("launch draft packs are offline, read-only, and unpublished")

    def to_dict(self) -> dict[str, Any]:
        result = _value(self)
        for key in ("read_only", "network_calls", "mutated", "published", "ads_launched", "orders_created", "payments_created", "customer_messages_sent"):
            result[key] = False if key != "read_only" else True
        return result


def _hooks(synthesis: Mapping[str, Any], candidate: Mapping[str, Any]) -> list[str]:
    return _list(synthesis.get("top_hooks") or candidate.get("top_hooks"), 10) or [f"See {candidate.get('title') or synthesis.get('top_candidate_title') or 'the product'} in use"]


def _pains(synthesis: Mapping[str, Any], candidate: Mapping[str, Any]) -> list[str]:
    return _list(synthesis.get("top_pain_points") or candidate.get("top_pain_points"), 6) or ["A common task still takes more effort than customers want."]


def _objections(synthesis: Mapping[str, Any], candidate: Mapping[str, Any]) -> list[str]:
    return _list(synthesis.get("top_objections") or candidate.get("top_objections"), 6) or ["Confirm product quality, delivery timing, and returns before publishing."]


def _angles(synthesis: Mapping[str, Any], candidate: Mapping[str, Any]) -> list[str]:
    return _list(synthesis.get("top_ad_angles") or candidate.get("top_ad_angles"), 8) or ["problem_solution", "demo", "convenience", "comparison", "travel_portability"]


def _economics(synthesis: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    value = candidate.get("unit_economics_summary") or synthesis.get("unit_economics_summary") or {}
    return dict(value) if isinstance(value, Mapping) else {}


def _thresholds(synthesis: Mapping[str, Any]) -> dict[str, Any]:
    value = synthesis.get("decision_thresholds") or {}
    return dict(value) if isinstance(value, Mapping) else {}


def _offer_stack(title: str, hooks: list[str], pains: list[str], economics: Mapping[str, Any], context: Mapping[str, Any], recommendation: str) -> OfferStack:
    currency = str(context["currency"])
    price = _number(economics.get("target_sell_price"))
    if price is None:
        price = _number(economics.get("recommended_price_band_min"))
    promise = _safe_copy(f"Make {pains[0].lower()} easier with a focused, practical {title}.", context["prohibited_claims"])
    return OfferStack(
        core_offer=f"{title} — a draft offer for {context['target_customer']}",
        headline_value_proposition=_safe_copy(hooks[0], context["prohibited_claims"]),
        primary_promise=promise,
        secondary_benefits=tuple(_safe_copy(item, context["prohibited_claims"]) for item in ["simple to demonstrate", "designed around a clear customer task", "supported by an evidence-led offer brief"]),
        bundle_suggestions=(f"Single {title}", f"{title} + practical accessory bundle (confirm supplier availability)", "Multi-unit bundle only after landed cost is confirmed"),
        pricing_suggestion={"target_price": price, "currency": currency, "status": "draft_assumption" if price is None else "from_synthesis_or_supplier_scenario", "recommended_price_band": {"min": economics.get("recommended_price_band_min", UNKNOWN), "max": economics.get("recommended_price_band_max", UNKNOWN)}},
        discount_suggestion="Test a modest introductory offer only after price band and margin approval; do not imply permanent scarcity.",
        risk_reversal="Use a clearly documented return policy after the operator confirms supplier and storefront terms.",
        shipping_return_notes=(context["shipping_policy_text"], context["return_policy_text"]),
        urgency_scarcity_guidance="Use urgency only when it reflects a real, approved deadline or offer window.",
        claim_safety_notes=("Draft copy does not promise a specific outcome.", "Confirm product specifications and regulated-claim restrictions before use.", f"Current recommendation is {recommendation}; this pack does not authorize launch."),
    )


def _listing(title: str, offer: OfferStack, pains: list[str], context: Mapping[str, Any], customer_language: str = "") -> ProductListingDraft:
    safe_title = _safe_copy(f"{title}: a simpler way to handle the task", context["prohibited_claims"])
    if customer_language:
        short_description = _safe_copy(
            f"{customer_language} Draft copy from matching customer evidence, not a verified product promise.",
            context["prohibited_claims"],
        )
    else:
        short_description = _safe_copy(f"A draft listing for customers who want {pains[0].lower()}.", context["prohibited_claims"])
    return ProductListingDraft(
        title=safe_title,
        subtitle=_safe_copy(offer.primary_promise, context["prohibited_claims"]),
        short_description=short_description,
        long_description=_safe_copy(f"{title} is presented here as a draft solution for {context['target_customer']}. Use the demonstrated workflow as the product story, then replace every TBD field with verified supplier and policy information before publishing.", context["prohibited_claims"]),
        bullet_benefits=tuple(offer.secondary_benefits),
        features=("Product demonstration-friendly format", "Evidence-led positioning", "Specifications pending supplier confirmation"),
        specifications={"material": UNKNOWN, "dimensions": UNKNOWN, "weight": UNKNOWN, "power_or_compatibility": UNKNOWN, "sku": UNKNOWN, "certifications": UNKNOWN},
        what_is_included=(title, "Packaging and accessories: TBD — confirm before publishing."),
        shipping_note=context["shipping_policy_text"],
        return_note=context["return_policy_text"],
        risk_disclaimer="Draft only. Do not publish until supplier, claims, shipping, and return details are reviewed.",
        seo_keywords=tuple(dict.fromkeys([_text(title, 60), *[_text(item, 60) for item in pains], "product validation"])),
        image_brief=("Hero product image with no unsupported badges", "Hands-on demonstration showing the core task", "Comparison or context image using verified dimensions only"),
    )


def _landing(title: str, offer: OfferStack, pains: list[str], objections: list[str], recommendation: str, customer_language: str = "") -> LandingPageDraft:
    sections: dict[str, Mapping[str, Any]] = {}
    hero_body = offer.primary_promise
    hero_evidence = "Consumer hooks and synthesis"
    if customer_language:
        hero_body = f"{customer_language} Use this only as draft customer language; do not publish it as a result promise."
        hero_evidence = "Matching consumer-attention landing hint or desired outcome"
    templates = {
        "hero": (offer.headline_value_proposition, hero_body, "Verified product image or demo still", hero_evidence, "Keep the promise specific and evidence-led."),
        "problem": ("The everyday friction is clear", f"Customers may be trying to solve: {pains[0]}.", "Customer-language quote or clean scenario photo", "Pain-point evidence", "Do not exaggerate severity."),
        "solution": (f"A focused way to approach {title}", offer.primary_promise, "Simple three-step product explanation", "Offer stack and creative hooks", "Confirm functionality before publishing."),
        "how_it_works": ("Show the workflow", "Use a short, observable sequence so the customer can judge the product for themselves.", "Hands-only demo or annotated storyboard", "Demo/UGC hypothesis", "No invented performance data."),
        "benefits": ("What the draft offer emphasizes", "Convenience, clarity, and a visible use case lead the draft positioning.", "Benefit icons only after feature verification", "Pain points and desired outcomes", "Benefits must remain tied to observed or confirmed features."),
        "proof_or_demo_section": ("Let the product demonstrate", "Use evidence, demonstration, and clear provenance instead of unsupported testimonials.", "Demo asset; no fake reviews", "Consumer evidence and source notes", "Do not present fixture evidence as customer proof."),
        "comparison_section": ("Make the trade-off easy to understand", "Compare the workflow and verified features, not unsupported competitor claims.", "Comparison table with TBD fields", "Marketplace price and competition evidence", "Avoid disparagement and unverified claims."),
        "offer_section": (offer.core_offer, offer.discount_suggestion, "Price-band and bundle visual", "Synthesis thresholds", "Price and margin need approval."),
        "faq": ("Questions customers may ask", "Address delivery, returns, what is included, and compatibility with verified answers.", "FAQ block", "Objection evidence", "Leave unknown answers as TBD."),
        "risk_reversal": ("Clear policies build trust", offer.risk_reversal, "Policy link or approved copy", "Client policy context", "Do not promise a policy that is not approved."),
        "final_cta": ("Review the draft offer", "Invite the next human review step; do not imply that the product is already live.", "CTA mockup", "Operator approval checklist", "Draft CTA only; no publishing action."),
    }
    for key, (headline, body, asset, evidence, risk) in templates.items():
        sections[key] = {"headline": headline, "body_copy": body, "asset_note": asset, "evidence_source_note": evidence, "risk_note": risk, "draft_only": True}
    return LandingPageDraft(sections)


def _ad_creatives(title: str, hooks: list[str], pains: list[str], objections: list[str], angles: list[str], context: Mapping[str, Any]) -> AdCreativeDraft:
    angle_rows = tuple({"angle": angle, "concept": _safe_copy(f"Show {title} through a {angle.replace('_', ' ')} lens.", context["prohibited_claims"]), "evidence_note": "Use only verified product behavior and supplied evidence."} for angle in (angles + ["problem_solution", "demo", "comparison", "convenience", "travel_portability"])[:5])
    hooks10 = tuple(dict.fromkeys([*hooks, f"A closer look at {title}", "See the workflow before you decide", "Could this simplify the routine?", "One small product, one visible task", "Compare the process, not the hype", "The draft demo starts here", "One question before you buy", "Make the next step visible", "A practical look at the product", "From task to demonstration"]))[:10]
    videos = tuple({"script_id": f"video_{index}", "opening_hook": hook, "beats": ("state the task", "show the product in use", "address one objection", "invite review of the draft offer"), "cta": "Review the product details", "disclosure": "Draft creative; verify claims before use."} for index, hook in enumerate(hooks10[:5], 1))
    statics = tuple({"concept_id": f"static_{index}", "headline": hook, "visual": "Clean product/demo composition", "supporting_copy": _safe_copy(pains[(index - 1) % len(pains)], context["prohibited_claims"]), "asset_status": "brief_only"} for index, hook in enumerate(hooks10[:5], 1))
    meta = tuple(_safe_copy(text, context["prohibited_claims"]) for text in (f"See how {title} fits the task — review the draft details before launch.", f"A practical {title} demo built from customer language and evidence.", f"Compare the workflow, check the policies, then decide whether {title} merits the next validation step."))
    captions = tuple(_safe_copy(text, context["prohibited_claims"]) for text in (f"A closer look at {title}. Draft demo only.", "Show the task. Show the product. Keep the claim grounded.", "Evidence-led creative testing starts with a clear use case."))
    headlines = tuple(hooks10[:3])
    return AdCreativeDraft(angle_rows, hooks10, videos, statics, meta, captions, headlines)


def _ugc(title: str, hooks: list[str], pains: list[str], objections: list[str], context: Mapping[str, Any]) -> tuple[UGCBrief, ...]:
    briefs = ("hands_only_demo", "problem_solution", "before_after_or_comparison")
    result = []
    for index, brief_type in enumerate(briefs):
        result.append(UGCBrief(
            brief_type=brief_type,
            creator_brief=f"Create a simple, honest {brief_type.replace('_', ' ')} for {title}; the creator should show the task without unsupported claims.",
            shot_list=("Opening task context", "Product close-up", "Hands-on use", "Result or comparison frame", "Policy/disclosure end card"),
            script_outline=("Name the task", f"Show the moment where {pains[index % len(pains)].lower()}", "Demonstrate one verified behavior", "Answer one question", "Invite the viewer to review details"),
            opening_hook=hooks[index % len(hooks)],
            demo_moments=("Unboxing or setup", "Core use step", "Before/after workflow comparison without an unsupported outcome promise"),
            objection_handling_moment=f"Address: {objections[index % len(objections)]}",
            cta="Review the product details and policies",
            do_not_say_claims=("Do not promise a specific result", "Do not make medical, financial, or certification claims", "Do not imply verified reviews or stock"),
            required_disclosures=("Draft asset for human review", "Disclose material creator relationship if used", "Use only approved product and policy facts"),
            asset_checklist=("Vertical video", "Clean audio or captions", "Product close-ups", "Policy/disclosure frame", "Source note for any quoted evidence"),
        ))
    return tuple(result)


def _matrix(title: str, hooks: list[str], angles: list[str], thresholds: Mapping[str, Any]) -> CreativeTestMatrix:
    kill_cpa = thresholds.get("kill_if_cpa_above", UNKNOWN)
    scale_cpa = thresholds.get("scale_if_cpa_below", UNKNOWN)
    rows = tuple({"angle": angle, "hook": hooks[index % len(hooks)], "format": "short_form_video" if index % 2 == 0 else "static", "asset_required": "demo asset brief", "hypothesis": f"The {angle.replace('_', ' ')} angle will make the task and product fit easier to understand.", "target_metric": "qualified engagement and add-to-cart rate", "kill_threshold": {"cpa_above": kill_cpa, "ctr_below": thresholds.get("kill_if_ctr_below", UNKNOWN)}, "scale_threshold": {"cpa_below": scale_cpa, "margin_above": thresholds.get("scale_if_margin_above", UNKNOWN)}, "budget_note": "Planning threshold only; no spend is authorized by this pack.", "risk_note": "Validate claim, price, shipping, and supplier proof before any test."} for index, angle in enumerate((angles + ["demo", "problem_solution", "comparison"])[:5]))
    return CreativeTestMatrix(rows)


def _faq(objections: list[str], context: Mapping[str, Any]) -> FAQAndObjectionDraft:
    faqs = ({"question": "When will it arrive?", "answer": context["shipping_policy_text"]}, {"question": "What is included?", "answer": UNKNOWN}, {"question": "What is the return policy?", "answer": context["return_policy_text"]}, {"question": "Will the product deliver a specific result?", "answer": "No outcome is promised; confirm product facts and use instructions before publishing."})
    return FAQAndObjectionDraft(faqs, tuple({"objection": item, "response": "Answer with a verified fact, policy, or transparent TBD rather than an unsupported claim."} for item in objections))


def _payloads(title: str, offer: OfferStack, context: Mapping[str, Any]) -> tuple[ShopifyDraftPayload, MedusaDraftPayload]:
    tags = tuple(dict.fromkeys(["marketos-draft", "human-review-required", _text(title, 40).lower().replace(" ", "-")]))
    variant = {"title": "Default", "sku": "TBD", "price": offer.pricing_suggestion.get("target_price") or "TBD", "inventory_quantity": "TBD", "weight": "TBD", "option_values": {}}
    images = ({"role": "hero", "src": "TBD — add approved image reference."}, {"role": "demo", "src": "TBD — add approved demo asset."})
    body = f"{offer.primary_promise}\n\nDraft only. Confirm supplier facts, policies, and claims before publishing."
    shopify = ShopifyDraftPayload(title=title, body_html_or_markdown=body, vendor=context["brand_name"], product_type="TBD", tags=tags, status="draft", variants=(variant,), options=(), images_placeholder=images, seo_title=_text(title, 70), seo_description=_text(offer.primary_promise, 155), metafields={"marketos_evidence_mode": "draft_only", "marketos_launch_authorized": False})
    handle = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "product-draft"
    medusa = MedusaDraftPayload(title=title, subtitle=offer.headline_value_proposition, description=body, handle=handle, status="draft", variants=(variant,), options=(), metadata={"marketos_evidence_mode": "draft_only", "marketos_launch_authorized": False}, sales_channels_placeholder=("TBD — confirm approved sales channel.",), images_placeholder=images)
    return shopify, medusa


def _checklist(synthesis: Mapping[str, Any], supplier_present: bool) -> LaunchApprovalChecklist:
    items = ("supplier proof confirmed", "landed cost confirmed", "shipping window confirmed", "inventory confirmed", "return/refund policy reviewed", "claims/compliance reviewed", "price band approved", "break-even CPA approved", "ad budget cap approved", "creative claims approved", "Shopify draft approved", "launch not authorized until final approval")
    blockers = []
    if not supplier_present or "supplier_proof_missing" in str(synthesis.get("risk_profile", {})):
        blockers.append("supplier proof is not live-observed")
    if synthesis.get("confidence_grade") in {"C_fixture_or_partial", "D_low_confidence", "F_reject_or_missing"}:
        blockers.append(f"evidence confidence is {synthesis.get('confidence_grade')}")
    blockers.append("human approval is required before any publishing, spend, or provider action")
    return LaunchApprovalChecklist(items, tuple(dict.fromkeys(blockers)), False)


def _risks(synthesis: Mapping[str, Any], candidate: Mapping[str, Any], objections: list[str]) -> LaunchRiskReview:
    profile = synthesis.get("risk_profile") if isinstance(synthesis.get("risk_profile"), Mapping) else {}
    supplier = tuple(_list(synthesis.get("top_supplier_risks") or profile.get("supplier_risks"), 8) or ["supplier proof and landed cost need confirmation"])
    market = tuple(_list(synthesis.get("top_marketplace_risks") or profile.get("marketplace_risks"), 8) or ["market saturation and pricing need review"])
    consumer = tuple(_list(synthesis.get("top_consumer_risks") or profile.get("consumer_risks"), 8) or ["creative claims and objections need review"])
    margin = ("Margin is scenario-based until supplier cost, shipping, and fees are verified.",) if not candidate.get("unit_economics_summary") else ("Review margin sensitivity against verified supplier and fee inputs.",)
    return LaunchRiskReview(supplier, ("Delivery window is not a publishing promise until confirmed.",), margin, ("Use approved, evidence-led claims only.",), consumer, market, ("Prepare support answers for the listed objections.",), ("Confirm return/refund terms before offer approval.",), ("Review platform policies before any future activation.",))


def _bound_candidate(report: Mapping[str, Any] | None, candidate_id: str) -> tuple[Mapping[str, Any] | None, str]:
    """Bind a source report to the draft candidate without reading foreign rows.

    ``candidate_id`` must be a real identifier from the synthesis/candidate,
    never the display-only placeholder used when no candidate id exists --
    matching against a placeholder would let an unrelated report's row bind
    by coincidence rather than by real product identity. Comparison is
    case/whitespace-insensitive since the synthesis and evidence pipelines
    are independent sources that are not guaranteed to agree on casing for
    the same id.
    """
    normalized_id = candidate_id.strip().casefold()
    if not normalized_id:
        return None, "missing"
    if not isinstance(report, Mapping) or not report:
        return None, "missing"
    candidates = [item for item in report.get("candidates") or [] if isinstance(item, Mapping)]
    if not candidates:
        return None, "missing"
    matched = next((item for item in candidates if str(item.get("candidate_id") or "").strip().casefold() == normalized_id), None)
    if matched is None:
        return None, "mismatched"
    return matched, "matched"


def _customer_language(candidate: Mapping[str, Any] | None) -> str:
    """Platform-neutral customer wording only. Claims and proof signals stay out."""
    if not isinstance(candidate, Mapping):
        return ""
    score = candidate.get("score") if isinstance(candidate.get("score"), Mapping) else {}
    voice = score.get("voice_of_customer") if isinstance(score.get("voice_of_customer"), Mapping) else {}
    hints = _list(score.get("landing_page_copy_hints"), 3)
    if hints:
        return hints[0]
    outcomes = _list(voice.get("desired_outcomes"), 3)
    return outcomes[0] if outcomes else ""


def _evidence_note(label: str, status: str) -> str:
    if status == "matched":
        return f"{label} matches this draft candidate and remains draft-only."
    if status == "mismatched":
        return f"{label} does not match this draft candidate and was not copied into the draft."
    return f"{label} was not supplied; missing product facts stay TBD."


def build_launch_draft_pack(*, synthesis: Mapping[str, Any], product_validation: Mapping[str, Any] | None = None, consumer_attention: Mapping[str, Any] | None = None, supplier_feasibility: Mapping[str, Any] | None = None, marketplace_trend: Mapping[str, Any] | None = None, client_context: Mapping[str, Any] | None = None) -> LaunchDraftPack:
    """Build one deterministic launch draft for the synthesis leader."""
    ctx = _context(client_context)
    candidate = _candidate(synthesis)
    title = _text(synthesis.get("top_candidate_title") or candidate.get("title") or candidate.get("query") or "Product candidate", 120)
    candidate_id = _text(synthesis.get("top_candidate_id") or candidate.get("candidate_id") or "candidate", 100)
    # Evidence binding must use a real identifier only -- never the "candidate"
    # display placeholder above, which would let an unrelated report's row
    # (e.g. one that also happens to say candidate_id: "candidate") bind by
    # coincidence when this draft has no real candidate identity at all.
    evidence_candidate_id = str(synthesis.get("top_candidate_id") or candidate.get("candidate_id") or "").strip()
    hooks, pains, objections, angles = _hooks(synthesis, candidate), _pains(synthesis, candidate), _objections(synthesis, candidate), _angles(synthesis, candidate)
    econ, thresholds = _economics(synthesis, candidate), _thresholds(synthesis)
    recommendation = _text(synthesis.get("overall_recommendation") or "hold_for_manual_review", 80)
    consumer_candidate, consumer_status = _bound_candidate(consumer_attention, evidence_candidate_id)
    _supplier_candidate, supplier_status = _bound_candidate(supplier_feasibility, evidence_candidate_id)
    customer_language = _safe_copy(_customer_language(consumer_candidate), ctx["prohibited_claims"])
    offer = _offer_stack(title, hooks, pains, econ, ctx, recommendation)
    listing = _listing(title, offer, pains, ctx, customer_language)
    landing = _landing(title, offer, pains, objections, recommendation, customer_language)
    ads = _ad_creatives(title, hooks, pains, objections, angles, ctx)
    ugc = _ugc(title, hooks, pains, objections, ctx)
    matrix = _matrix(title, list(ads.hooks), angles, thresholds)
    faq = _faq(objections, ctx)
    shopify, medusa = _payloads(title, offer, ctx)
    live_on_candidate = any(item.get("evidence_mode") in {"live_readonly", "authenticated_live"} for item in candidate.get("evidence", []) if isinstance(item, Mapping))
    supplier_present = supplier_status == "matched" or live_on_candidate
    checklist = _checklist(synthesis, supplier_present)
    risks = _risks(synthesis, candidate, objections)
    mode = _text(synthesis.get("evidence_mode") or "fixture_demo", 40)
    market_access = candidate.get("market_access") or synthesis.get("market_access") or {}
    operator_notes = ["No live calls were made.", "Draft payloads are not connected to Shopify or Medusa.", "Replace TBD fields with verified evidence before publishing.", "Next consulting upsell: generate a platform-agnostic website/store/funnel draft.", _evidence_note("Consumer attention evidence", consumer_status), _evidence_note("Supplier feasibility evidence", supplier_status)]
    if market_access:
        mx = next((item for item in market_access.get("jurisdictions", []) if item.get("jurisdiction") == "mexico"), None)
        if mx and mx.get("assessment_state") != "compliant":
            operator_notes.append(f"Market access: Mexico import/compliance evidence is `{mx.get('assessment_state')}` -- see the market_access section before approving a Mexico launch. Not legal advice.")
    return LaunchDraftPack(VERSION, "deterministic", candidate_id, title, mode, "opportunity_synthesis", recommendation, "draft_only_pending_human_approval", offer, listing, landing, ads, ugc, matrix, faq, shopify, medusa, checklist, risks, tuple(operator_notes), f"{title} has a draft launch package based on {mode} evidence. It is a consulting work product for review, not a launch authorization or profit claim.", market_access=market_access)


def markdown(pack: Mapping[str, Any]) -> str:
    offer = pack.get("offer_stack", {})
    listing = pack.get("product_listing", {})
    ads = pack.get("ad_creatives", {})
    checklist = pack.get("approval_checklist", {})
    lines = ["# Launch Draft Pack", "", f"**Candidate:** {pack.get('candidate_title', 'TBD')}  ", f"**Evidence mode:** `{pack.get('evidence_mode', 'missing')}` — draft-only, not launch authorization  ", f"**Recommendation:** `{pack.get('overall_recommendation', 'hold_for_manual_review')}`", "", "## Offer Stack", "", f"**Headline:** {offer.get('headline_value_proposition', UNKNOWN)}", f"**Core offer:** {offer.get('core_offer', UNKNOWN)}", f"**Primary promise:** {offer.get('primary_promise', UNKNOWN)}", f"**Pricing:** {offer.get('pricing_suggestion', {})}", "", "## Product Listing Draft", "", f"**Title:** {listing.get('title', UNKNOWN)}", listing.get('short_description', UNKNOWN), "", "### Benefits", *[f"- {item}" for item in listing.get("bullet_benefits", [])], "", "## Landing Page Draft", "", *[f"### {key.replace('_', ' ').title()}\n{value.get('headline', UNKNOWN)}\n\n{value.get('body_copy', UNKNOWN)}\n\n*Asset:* {value.get('asset_note', UNKNOWN)}  \n*Evidence:* {value.get('evidence_source_note', UNKNOWN)}" for key, value in (pack.get("landing_page", {}).get("sections", {}) or {}).items()], "", "## Ad Creative Drafts", "", f"Angles: {', '.join(item.get('angle', '') for item in ads.get('angles', []))}", *[f"- {item}" for item in ads.get("hooks", [])], "", "## UGC Briefs", "", *[f"### {item.get('brief_type')}\n{item.get('creator_brief')}\nOpening hook: {item.get('opening_hook')}" for item in pack.get("ugc_briefs", [])], "", "## Creative Test Matrix", "", *[f"- {item.get('angle')} / {item.get('format')}: {item.get('hypothesis')}" for item in pack.get("creative_test_matrix", {}).get("rows", [])], "", "## Approval Blockers", "", *[f"- {item}" for item in checklist.get("blockers", [])], "", "## Safety", "", "This pack is read-only. It does not publish products, launch ads, send messages, create orders, collect payments, or call Shopify/Medusa.", ""]
    return "\n".join(lines)


__all__ = ["AdCreativeDraft", "CreativeTestMatrix", "FAQAndObjectionDraft", "LandingPageDraft", "LaunchApprovalChecklist", "LaunchDraftPack", "LaunchRiskReview", "MedusaDraftPayload", "OfferStack", "ProductListingDraft", "ShopifyDraftPayload", "UGCBrief", "build_launch_draft_pack", "markdown"]
