"""backend.commerce — brand registry, product catalog, storefront layer,
and the canonical commerce loop.

The commerce back-half of the dropship spine: a handful of brand/category
storefronts (landing pages by default, Shopify optional per brand), their
product catalogs, and the storefront adapters that create/update product
pages on whichever backend a brand is bound to. Alongside that, the
canonical commerce loop provides the complementary commerce truth layer:
signal normalization, product ranking, creative generation, launch
orchestration, and metrics feedback reconciliation.

Public surface:
    brand_registry            singleton — Brand CRUD + category routing
    product_catalog           singleton — per-brand catalog entries
    get_storefront(brand)     storefront adapter dispatch
    run_commerce_cycle(...)   signal → rank → creative → launch → feedback
"""
from backend.commerce.brands import Brand, brand_registry
from backend.commerce.catalog import CatalogEntry, product_catalog
from backend.commerce.storefront import get_storefront

from backend.commerce.contracts import (
    CampaignOutcome,
    CommerceCycleReport,
    CommerceSignal,
    CreativeBundle,
    LaunchPlan,
    RankedOpportunity,
)
from backend.commerce.creative import CreativeComposer
from backend.commerce.feedback import FeedbackRecorder
from backend.commerce.launch import LaunchExecutor
from backend.commerce.loop import CommerceLoop, run_commerce_cycle, run_provider_cycle
from backend.commerce.scoring import OpportunityScorer
from backend.commerce.oss_bridge import clear_oss_cache, collect_oss_inputs

__all__ = [
    "Brand",
    "brand_registry",
    "CatalogEntry",
    "product_catalog",
    "get_storefront",
    "CampaignOutcome",
    "CommerceCycleReport",
    "CommerceSignal",
    "CreativeBundle",
    "LaunchPlan",
    "RankedOpportunity",
    "CreativeComposer",
    "FeedbackRecorder",
    "LaunchExecutor",
    "CommerceLoop",
    "run_commerce_cycle",
    "run_provider_cycle",
    "OpportunityScorer",
    "collect_oss_inputs",
    "clear_oss_cache",
]
