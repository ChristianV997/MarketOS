"""backend.stack_planner.strategies — the 7 original spec presets.

All 7 are reachable as of Phase 2 (Chatwoot/Mautic/Activepieces/PostHog-
backend/Hostinger adapters + CRM/Conversation/Analytics/MarketingAutomation/
Hosting Protocols). The 3 lead-gen/agency strategies use
`ECOMMERCE_STRATEGIES` vs `LEAD_GEN_STRATEGIES` to pick which branch of
`backend.stack_planner.planner.recommend_stack` applies — lead-gen strategies
have no commerce/payment provider (no checkout), only CRM/conversation/
marketing-automation recommendations. Twenty CRM (the one low-cost CRM
candidate) stays deferred pending legal review (AGPL-3.0) — see
`docs/COST_AWARE_INTEGRATION_AUDIT.md` — so `high_ticket_lead_gen_low_cost`
recommends Chatwoot + Mautic and reports the CRM gap honestly rather than
recommending Twenty or fabricating a CRM pick.
"""
from __future__ import annotations

ECOMMERCE_STRATEGIES = (
    "own_ecommerce_low_cost",
    "client_ecommerce_low_cost",
    "client_ecommerce_shopify_premium",
    "marketos_owned_stack",
)

LEAD_GEN_STRATEGIES = (
    "high_ticket_lead_gen_low_cost",
    "high_ticket_lead_gen_gohighlevel_fast",
    "agency_white_label_fast",
)

# Kept for backwards compatibility with Phase 1 callers/tests.
REACHABLE_STRATEGIES = ECOMMERCE_STRATEGIES + LEAD_GEN_STRATEGIES
DEFERRED_STRATEGIES: tuple[str, ...] = ()

ALL_STRATEGIES = ECOMMERCE_STRATEGIES + LEAD_GEN_STRATEGIES

DEFAULT_STRATEGY = "own_ecommerce_low_cost"


def select_strategy(request) -> str:
    """Defaults to own_ecommerce_low_cost (Hostinger+WooCommerce) when the
    request's business_model doesn't match a known strategy — implements
    the "default = lowest-cost validated stack" hard rule."""
    model = (request.business_model or "").strip()
    if model in ALL_STRATEGIES:
        return model
    if model == "own_ecommerce":
        return "own_ecommerce_low_cost"
    if model == "client_ecommerce":
        if request.margin_sensitivity == "premium_brand":
            return "client_ecommerce_shopify_premium"
        return "client_ecommerce_low_cost"
    if model in ("marketos_owned", "owned_stack"):
        return "marketos_owned_stack"
    if model in ("high_ticket_lead_gen", "lead_gen"):
        from .recommendations import gohighlevel_allowed
        if gohighlevel_allowed(request):
            return "high_ticket_lead_gen_gohighlevel_fast"
        return "high_ticket_lead_gen_low_cost"
    if model == "agency_white_label":
        return "agency_white_label_fast"
    return DEFAULT_STRATEGY


def is_deferred_strategy(strategy_id: str) -> bool:
    return strategy_id in DEFERRED_STRATEGIES


def is_lead_gen_strategy(strategy_id: str) -> bool:
    return strategy_id in LEAD_GEN_STRATEGIES
