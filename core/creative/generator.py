def _placeholder(product: str, angle: str) -> str:
    return (
        f"[Script] Product: {product} | Angle: {angle} | "
        "Hook: Discover the difference. | CTA: Shop now."
    )


def generate_creative(product: str, angle: str) -> str:
    """Generate an ad script for *product* using the given *angle*.

    Routed through the central inference kernel (backend.inference.router),
    which provides provider fallback (Ollama → Anthropic → OpenAI → …),
    replay-safe caching, and cost telemetry.  When no real provider is
    configured the router lands on MockProvider; in that case we return the
    deterministic domain placeholder so the system works offline / in tests
    exactly as before.
    """
    prompt = (
        f"Write a short TikTok ad script for '{product}'. "
        f"Angle: {angle}. "
        "Include a hook, problem, solution, and CTA. "
        "Keep it under 60 words."
    )
    try:
        from backend.inference.router import complete
        response = complete(prompt, max_tokens=256)
        if response.provider != "mock" and response.content.strip():
            return response.content.strip()
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        pass
    return _placeholder(product, angle)
