"""CostPolicy — per-token cost estimates for provider selection.

Costs are in USD per token (input + output averaged).
Local providers (ollama, airllm, vllm, andromeda) are free at inference time.
"""
from __future__ import annotations

import os

# USD per output token (approximate as of 2025)
_COST_TABLE: dict[str, float] = {
    "openai/gpt-4o":              5e-6,
    "openai/gpt-4o-mini":         0.15e-6,
    "openai/gpt-4-turbo":         10e-6,
    "openai/gpt-3.5-turbo":       0.5e-6,
    "anthropic/claude-3-opus":    15e-6,
    "anthropic/claude-3-5-sonnet-latest": 3e-6,
    "anthropic/claude-3-5-haiku-latest":  1e-6,
    "anthropic/claude-3-haiku-20240307":  0.25e-6,
    "anthropic/*":          1e-6,    # conservative default for unlisted Claude models
    "ollama/*":             0.0,
    "airllm/*":             0.0,
    "vllm/*":               0.0,
    "andromeda/*":          0.0,
    "litellm/*":            0.0,    # cost depends on underlying provider
    "mock/*":               0.0,
}

# Hard budget cap; router will skip providers over this
_MAX_USD_PER_REQUEST = float(os.getenv("INFERENCE_MAX_COST_USD", "0.05"))


def _lookup(provider: str, model: str) -> float:
    exact = f"{provider}/{model}"
    if exact in _COST_TABLE:
        return _COST_TABLE[exact]
    wildcard = f"{provider}/*"
    return _COST_TABLE.get(wildcard, 0.0)


class CostPolicy:
    def estimate(self, provider: str, model: str, max_tokens: int) -> float:
        """Return estimated USD cost for a single request."""
        return _lookup(provider, model) * max_tokens

    def is_affordable(self, provider: str, model: str, max_tokens: int) -> bool:
        """Return False if this provider would exceed the per-request budget cap."""
        cost = self.estimate(provider, model, max_tokens)
        return cost <= _MAX_USD_PER_REQUEST

    def rank_by_cost(self, candidates: list[str], model_map: dict[str, str], max_tokens: int) -> list[str]:
        """Sort candidates cheapest-first."""
        return sorted(
            candidates,
            key=lambda p: self.estimate(p, model_map.get(p, "default"), max_tokens),
        )
