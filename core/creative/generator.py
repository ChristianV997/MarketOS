from __future__ import annotations

import hashlib
import os
from typing import Any


_DEFAULT_MODEL = os.getenv("CREATIVE_GENERATOR_MODEL", "default")

# ── Step 65 — hook-template batch generator ───────────────────────────────────
# Complementary to generate_creative() below: a lightweight, deterministic,
# non-AI batch generator over a small hook-angle template pool, used by
# core/pipeline/execution.py's end-to-end creative→ad pipeline.
_HOOKS: dict[str, list[str]] = {
    "satisfaction": [
        "watch this",
        "this is so satisfying",
    ],
    "problem": [
        "this fixes...",
        "stop doing this wrong",
    ],
    "convenience": [
        "this saves so much time",
        "the easiest way to do this",
    ],
    "transformation": [
        "before vs after",
        "this changed everything",
    ],
}


def generate_creatives(product: str, angle: str) -> list[dict[str, Any]]:
    """Return hook-based creative variants for *product* and *angle*.

    Parameters
    ----------
    product:
        Product name to feature in each creative.
    angle:
        Content angle key (e.g. ``"satisfaction"``, ``"problem"``).

    Returns
    -------
    list[dict]
        Each dict contains ``hook``, ``body``, and ``cta`` keys.
    """
    hooks = _HOOKS.get(angle, [f"{angle} hook"])
    return [
        {
            "hook": h,
            "body": f"show {product} solving problem",
            "cta": "get it now",
        }
        for h in hooks
    ]


def _fallback_script(product: str, angle: str) -> str:
    return (
        f"[Script] Product: {product} | Angle: {angle} | "
        "Hook: Discover the difference. | CTA: Shop now."
    )


def _sequence_id(product: str, angle: str) -> str:
    digest = hashlib.sha256(f"{product}::{angle}".encode("utf-8")).hexdigest()
    return f"creative-{digest[:16]}"


def generate_creative(product: str, angle: str) -> str:
    """Generate an ad script for *product* using the given *angle*.

    Routes through the centralized inference kernel when available; otherwise
    returns a deterministic placeholder so the system works offline / in tests.
    """
    try:
        from backend.inference import complete

        response = complete(
            (
                f"Write a short TikTok ad script for '{product}'. "
                f"Angle: {angle}. "
                "Include a hook, problem, solution, and CTA. "
                "Keep it under 60 words."
            ),
            model=_DEFAULT_MODEL,
            max_tokens=256,
            temperature=0.2,
            sequence_id=_sequence_id(product, angle),
            system=(
                "You write concise, high-conviction TikTok ad scripts. "
                "Return only the final script."
            ),
        )
        content = (response.content or "").strip()
        if response.provider != "mock" and content:
            return content
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        pass

    return _fallback_script(product, angle)
