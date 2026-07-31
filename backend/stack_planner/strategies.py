"""backend.stack_planner.strategies — the 7 original spec presets.

4 are reachable with only commerce/payment providers modeled this
increment; 3 need CRM/Conversation providers (Phase 2, deferred) and are
represented here so `select_strategy`/`is_deferred_strategy` account for
all 7 by name — never silently dropped.
"""
from __future__ import annotations

REACHABLE_STRATEGIES = (
    "own_ecommerce_low_cost",
    "client_ecommerce_low_cost",
    "client_ecommerce_shopify_premium",
    "marketos_owned_stack",
)

DEFERRED_STRATEGIES = (
    "high_ticket_lead_gen_low_cost",
    "high_ticket_lead_gen_gohighlevel_fast",
    "agency_white_label_fast",
)

ALL_STRATEGIES = REACHABLE_STRATEGIES + DEFERRED_STRATEGIES

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
        return "high_ticket_lead_gen_low_cost"
    if model == "agency_white_label":
        return "agency_white_label_fast"
    return DEFAULT_STRATEGY


def is_deferred_strategy(strategy_id: str) -> bool:
    return strategy_id in DEFERRED_STRATEGIES
