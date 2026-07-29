"""hooks — generate ad hook lines from filtered signals (3 variants per signal)."""
from __future__ import annotations
from backend.signals.base import BaseSignal

_BASE_TEMPLATES = [
    "Stop what you're doing — {text}",
    "The secret nobody tells you: {text}",
    "Here's why this matters: {text}",
    "Everyone is switching because: {text}",
    "This changes everything: {text}",
]

_VARIANT_PREFIXES = {
    1: "You won't believe this: {base}",
    2: "{base} — here's how.",
    3: "Everyone is talking about: {base}",
}


def generate_hooks(signals: list[BaseSignal]) -> list[dict]:
    hooks = []
    for i, sig in enumerate(signals):
        base_tmpl = _BASE_TEMPLATES[i % len(_BASE_TEMPLATES)]
        hook_text = sig["raw_text"][:70]
        base_hook = base_tmpl.format(text=hook_text)
        for variant, prefix_tmpl in _VARIANT_PREFIXES.items():
            hooks.append({
                "hook":         prefix_tmpl.format(base=base_hook),
                "hook_variant": variant,
                "raw_text":     sig["raw_text"],
                "source":       sig["source"],
                "category":     sig["category"],
                "engagement":   sig["engagement"],
                "external_id":  sig["external_id"],
                "url":          sig["url"],
            })
    return hooks
