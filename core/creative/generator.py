from __future__ import annotations

import hashlib
import os


_DEFAULT_MODEL = os.getenv("CREATIVE_GENERATOR_MODEL", "default")


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
