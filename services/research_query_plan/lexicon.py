"""Bounded offline lexicon for localized research query planning.

Only explicit, reviewed term pairs live here. Unsupported languages and
unknown categories do not invent translations or product attributes.
"""
from __future__ import annotations

# Category / product phrase synonyms: language -> source phrase -> alternatives.
# Keys are lowercase. Expansion is capped by the planner.
CATEGORY_SYNONYMS: dict[str, dict[str, tuple[str, ...]]] = {
    "en": {
        "kitchen appliances": ("kitchen appliance", "small kitchen appliance"),
        "fitness": ("fitness gear", "exercise equipment"),
        "drinkware": ("water bottle", "drink bottle"),
        "blender": ("personal blender",),
        "portable blender": ("personal blender", "mini blender"),
        "yoga mat": ("exercise mat",),
    },
    "es": {
        "kitchen appliances": ("electrodomésticos de cocina", "utensilios de cocina"),
        "fitness": ("fitness", "equipo de ejercicio"),
        "drinkware": ("botella de agua", "termo"),
        "blender": ("licuadora", "licuadora personal"),
        "portable blender": ("licuadora portátil", "licuadora personal"),
        "yoga mat": ("colchoneta de yoga", "mat de yoga"),
        "licuadora": ("licuadora portátil",),
    },
}

# Justified product-query transliteration / localization pairs (latin scripts).
# Never used as evidence that the translated form is the "true" product name.
QUERY_LOCALIZATIONS: dict[str, dict[str, str]] = {
    "es": {
        "portable blender": "licuadora portátil",
        "blender": "licuadora",
        "yoga mat": "colchoneta de yoga",
        "water bottle": "botella de agua",
        "stainless steel water bottle": "botella de agua de acero inoxidable",
    },
    "en": {
        "licuadora portátil": "portable blender",
        "licuadora": "blender",
        "colchoneta de yoga": "yoga mat",
        "botella de agua": "water bottle",
    },
}

REGION_LABELS: dict[str, tuple[str, ...]] = {
    "mx": ("México", "Mexico"),
    "mexico": ("México", "Mexico"),
    "us": ("USA", "United States"),
    "usa": ("USA", "United States"),
    "es": ("España", "Spain"),
    "spain": ("España", "Spain"),
    "jp": ("Japan",),
    "japan": ("Japan",),
}

# Source-family modifiers by language. Kept disjoint across families.
FAMILY_MODIFIERS: dict[str, dict[str, tuple[str, ...]]] = {
    "en": {
        "marketplace": ("buy", "price", "marketplace listing"),
        "supplier": ("supplier", "wholesale", "MOQ", "factory"),
        "consumer_attention": ("review", "trend", "demand", "customer feedback"),
    },
    "es": {
        "marketplace": ("comprar", "precio", "marketplace"),
        "supplier": ("proveedor", "mayoreo", "MOQ", "fábrica"),
        "consumer_attention": ("reseña", "opiniones", "tendencia", "demanda"),
    },
}

BUYER_MODIFIERS: dict[str, dict[str, dict[str, tuple[str, ...]]]] = {
    "en": {
        "consumer": {
            "marketplace": ("for home",),
            "supplier": ("small order",),
            "consumer_attention": ("worth buying",),
        },
        "business": {
            "marketplace": ("bulk pack",),
            "supplier": ("B2B wholesale", "commercial supplier"),
            "consumer_attention": ("office use reviews",),
        },
        "reseller": {
            "marketplace": ("resale ready",),
            "supplier": ("dropship supplier", "reseller wholesale"),
            "consumer_attention": ("reseller demand",),
        },
        "unknown": {
            "marketplace": (),
            "supplier": (),
            "consumer_attention": (),
        },
    },
    "es": {
        "consumer": {
            "marketplace": ("para casa",),
            "supplier": ("pedido pequeño",),
            "consumer_attention": ("vale la pena",),
        },
        "business": {
            "marketplace": ("paquete mayoreo",),
            "supplier": ("proveedor B2B", "mayoreo comercial"),
            "consumer_attention": ("uso oficina",),
        },
        "reseller": {
            "marketplace": ("para reventa",),
            "supplier": ("proveedor dropshipping", "mayoreo revendedor"),
            "consumer_attention": ("demanda revendedores",),
        },
        "unknown": {
            "marketplace": (),
            "supplier": (),
            "consumer_attention": (),
        },
    },
}

AMBIGUOUS_TOKENS = frozenset(
    {
        "it",
        "this",
        "that",
        "thing",
        "product",
        "producto",
        "item",
        "stuff",
        "algo",
        "cosa",
    }
)

__all__ = [
    "AMBIGUOUS_TOKENS",
    "BUYER_MODIFIERS",
    "CATEGORY_SYNONYMS",
    "FAMILY_MODIFIERS",
    "QUERY_LOCALIZATIONS",
    "REGION_LABELS",
]
