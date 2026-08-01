"""backend.creation.creative_generator — dropship listing + ad copy.

Routed through the central inference kernel (backend.inference.router) like
core/creative/generator.py: real providers when configured, deterministic
domain templates otherwise, so creation works offline and in tests.

The LLM path asks for strict JSON; any parse failure falls back to the
deterministic template rather than surfacing malformed copy downstream.
"""
from __future__ import annotations

import json
import logging
from typing import Any

_log = logging.getLogger(__name__)

_DEFAULT_ANGLES = ["problem-solution", "social-proof", "urgency", "curiosity", "authority"]

_PLATFORM_TONE = {
    "tiktok": "casual, trendy, native to TikTok — hook in the first line",
    "meta":   "relatable and trust-building, benefit-led",
    "google": "search-intent focused, specific, authority-based",
}


def _complete_json(prompt: str, max_tokens: int = 512) -> dict | None:
    """Run the prompt through the inference kernel; return parsed JSON or None.

    None means "use the deterministic fallback" — either no real provider is
    configured (MockProvider), the call failed, or the output wasn't JSON.
    """
    try:
        from backend.inference.router import complete
        response = complete(prompt, max_tokens=max_tokens)
        if response.provider == "mock" or not response.content.strip():
            return None
        text = response.content.strip()
        # Providers often wrap JSON in code fences; strip them before parsing
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        _log.debug("creative_llm_failed error=%s", exc)
        return None


# ── product listing ───────────────────────────────────────────────────────────

def generate_listing(product: str, price: float, supplier_days: int = 9) -> dict[str, Any]:
    """Generate a store product listing: title, description, bullet points."""
    prompt = (
        f"Write a Shopify product listing for '{product}' priced at ${price:.2f}. "
        "Return STRICT JSON with keys: title (string, <=70 chars), "
        "description (string, 2-3 paragraphs of HTML), "
        "bullets (array of exactly 5 short benefit strings). "
        "No markdown, no code fences — raw JSON only."
    )
    result = _complete_json(prompt)
    if isinstance(result, dict) and result.get("title") and result.get("bullets"):
        result.setdefault("description", "")
        description = str(result["description"])
        # Preserve the listing contract even when a configured provider omits
        # the requested price from otherwise valid copy.
        price_text = f"{price:.2f}"
        if price_text not in description:
            description = f"{description}<p>Price: ${price_text}</p>"
        return {
            "title": str(result["title"])[:70],
            "description": description,
            "bullets": [str(b) for b in result["bullets"]][:5],
            "generated_by": "llm",
        }
    return _fallback_listing(product, price, supplier_days)


def _fallback_listing(product: str, price: float, supplier_days: int) -> dict[str, Any]:
    title = f"{product} — Premium Quality, Fast Shipping"[:70]
    return {
        "title": title,
        "description": (
            f"<p>Meet the {product}: the upgrade your daily routine has been "
            f"waiting for. Thousands of happy customers can't be wrong.</p>"
            f"<p>Ships within {supplier_days} days, backed by our 30-day "
            f"money-back guarantee. Only ${price:.2f} for a limited time.</p>"
        ),
        "bullets": [
            f"Premium-grade {product.lower()} built to last",
            "30-day money-back guarantee — zero risk",
            f"Fast tracked shipping ({supplier_days} days average)",
            "Loved by thousands of verified buyers",
            "Limited-time launch pricing",
        ],
        "generated_by": "template",
    }


# ── ad copy ───────────────────────────────────────────────────────────────────

def generate_ad_copy(product: str, platform: str = "tiktok") -> dict[str, Any]:
    """Generate platform-native ad copy: hooks, angles, headlines, CTAs."""
    tone = _PLATFORM_TONE.get(platform, "persuasive and benefit-focused")
    prompt = (
        f"Write ad copy for '{product}' on {platform}. Tone: {tone}. "
        "Return STRICT JSON with keys: hooks (array of 5 short scroll-stopping "
        "openers), angles (array of 5 from: problem-solution, social-proof, "
        "urgency, curiosity, authority), headlines (array of 3, <=40 chars), "
        "ctas (array of 3 short calls to action). Raw JSON only."
    )
    result = _complete_json(prompt)
    if isinstance(result, dict) and result.get("hooks"):
        return {
            "product": product,
            "platform": platform,
            "hooks": [str(h) for h in result.get("hooks", [])][:5],
            "angles": [str(a) for a in result.get("angles", _DEFAULT_ANGLES)][:5],
            "headlines": [str(h)[:40] for h in result.get("headlines", [])][:3],
            "ctas": [str(c) for c in result.get("ctas", [])][:3],
            "generated_by": "llm",
        }
    return _fallback_ad_copy(product, platform)


def _fallback_ad_copy(product: str, platform: str) -> dict[str, Any]:
    # Seed hooks from the curated pattern library when available
    try:
        from core.creative.hooks import HOOKS
        base_hooks = list(HOOKS)[:3]
    except Exception:
        base_hooks = []
    hooks = base_hooks + [
        f"I didn't believe the hype about {product.lower()} until I tried it…",
        f"POV: you finally found a {product.lower()} that actually works",
    ]
    return {
        "product": product,
        "platform": platform,
        "hooks": hooks[:5],
        "angles": list(_DEFAULT_ANGLES),
        "headlines": [
            f"{product}: Sold Out 3x"[:40],
            f"The Last {product} You'll Buy"[:40],
            f"{product} — 50% Off Today"[:40],
        ],
        "ctas": ["Shop Now", "Get Yours Today", "Claim the Deal"],
        "generated_by": "template",
    }
