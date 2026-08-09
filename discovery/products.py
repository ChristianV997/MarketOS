"""discovery.products — generate niche-aware product candidates from signals."""
from __future__ import annotations

from typing import Any

from discovery.angles import extract_angles
from discovery.clustering import cluster


def generate_products(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cluster *signals* by niche and generate structured product candidates.

    For each signal, a product dict is created with:

    * ``niche`` — detected niche label
    * ``name``  — signal text used as product label
    * ``angles`` — list of content angles

    Parameters
    ----------
    signals:
        List of signal dicts each containing at least a ``"text"`` key.

    Returns
    -------
    list[dict]
        Flat list of product dicts ordered by niche cluster.
    """
    clusters = cluster(signals)
    products: list[dict[str, Any]] = []
    for niche, items in clusters.items():
        for s in items:
            products.append(
                {
                    "niche": niche,
                    "name": s.get("text", ""),
                    "angles": extract_angles(s),
                }
            )
    return products
