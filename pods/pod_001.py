"""pods.pod_001 — first executable pod: research → products → creatives."""
from __future__ import annotations

from typing import Any


def run_pod(signals: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Run the POD_001 pipeline.

    Executes the minimal loop:

    1. Research signals (uses *signals* if supplied, else falls back to
       :func:`core.sensors.normalize.normalize_tiktok` stubs).
    2. Generates product candidates via
       :func:`discovery.products.generate_products`.
    3. Generates content specs via
       :func:`core.content.generator.generate_content`.

    Parameters
    ----------
    signals:
        Optional list of pre-normalised signal dicts.  When ``None``, an empty
        signal list is used so the pod can run without external API keys.

    Returns
    -------
    dict
        ``{"products": [...], "creatives": [...]}``
    """
    from core.content.generator import generate_content
    from discovery.products import generate_products as disco_generate

    raw_signals: list[dict[str, Any]] = signals if signals is not None else []

    products = disco_generate(raw_signals)

    creatives: list[dict[str, Any]] = []
    for p in products[:2]:
        angles = p.get("angles", ["general"])
        angle = angles[0] if angles else "general"
        creatives.append(generate_content(p.get("name", str(p)), angle))

    return {"products": products, "creatives": creatives}


if __name__ == "__main__":  # pragma: no cover
    result = run_pod()
    print("TOP PRODUCTS:", result["products"][:3])
    print("CREATIVES:", result["creatives"][:3])
