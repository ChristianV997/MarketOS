"""core.pipeline.phase2 — Phase 2 pipeline: clusters → product → execution candidate.

Step 64: Cluster → Product → Landing → Persona Generator (Simulate → Execute → Learn)
"""
from __future__ import annotations

from typing import Any

from core.product.generator import generate_products
from core.persona.generator import generate_persona
from core.landing.generator import generate_landing
from core.simulation.evaluator import evaluate
from core.selection.select import select_best


def run_phase2(clusters: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Convert a list of cluster analysis dicts into the best execution candidate.

    Each cluster dict must contain:
    - ``"signals"`` — list of raw signal dicts
    - ``"top_angles"`` — list of angle strings

    Parameters
    ----------
    clusters:
        List of cluster analysis dicts as produced by
        :func:`~core.reports.niches.discover`.

    Returns
    -------
    dict or None
        Best candidate dict with product, persona, landing page, and
        simulation metrics; ``None`` when no candidates pass the threshold.
    """
    results: list[dict[str, Any]] = []

    for cluster_info in clusters:
        signals = cluster_info.get("signals", [])
        angles = cluster_info.get("top_angles", [])
        products = generate_products(signals)

        for product in products:
            persona = generate_persona(signals, angles)
            angle = angles[0] if angles else "general"
            landing = generate_landing(product, angle)

            # Use cluster aggregate signal for simulation
            agg_signal = {
                "views": cluster_info.get("total_views", 0),
                "engagement": cluster_info.get("avg_engagement", 0.0),
            }
            sim = evaluate(product, persona, landing, agg_signal)

            results.append(
                {
                    "product": product,
                    "persona": persona,
                    "landing": landing,
                    "angle": angle,
                    **sim,
                }
            )

    return select_best(results)
