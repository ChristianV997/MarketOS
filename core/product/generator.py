"""core.product.generator — generate product candidates from a signal cluster."""
from __future__ import annotations

from typing import Any


def generate_products(cluster: list[dict[str, Any]], max_candidates: int = 3) -> list[str]:
    """Extract candidate product names from a cluster's signal texts.

    Uses the first three tokens of each unique text as a naive proxy for
    a product label.

    Parameters
    ----------
    cluster:
        List of signal dicts containing a ``"text"`` key.
    max_candidates:
        Maximum number of product candidates to return.

    Returns
    -------
    list[str]
        Up to *max_candidates* distinct product label strings.
    """
    seen: set[str] = set()
    products: list[str] = []
    for s in cluster:
        words = s.get("text", "").split()
        label = " ".join(words[:3]) if words else ""
        if label and label not in seen:
            seen.add(label)
            products.append(label)
        if len(products) >= max_candidates:
            break
    return products
