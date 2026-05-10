"""FallbackPolicy — ordered provider chain with environment override.

Priority (default, left = highest):
  ollama  →  openai  →  airllm  →  vllm  →  andromeda  →  litellm  →  mock

Rationale:
  * Ollama first — free, local, zero latency if running.
  * OpenAI second — reliable cloud fallback when available.
  * AirLLM third — large local models without Ollama daemon.
  * vLLM fourth — self-hosted GPU server.
  * LiteLLM fifth — any provider via unified API.
  * Mock always last — guaranteed fallback for CI / cold-start.

Override via INFERENCE_PROVIDERS env var (comma-separated names).
"""
from __future__ import annotations

import os

_DEFAULT = ["ollama", "openai", "airllm", "vllm", "andromeda", "litellm", "mock"]


class FallbackPolicy:
    def __init__(self, chain: list[str] | None = None) -> None:
        if chain is not None:
            self._chain = list(chain)
        else:
            env = os.getenv("INFERENCE_PROVIDERS", "").strip()
            self._chain = [p.strip() for p in env.split(",") if p.strip()] or list(_DEFAULT)

    # ── public API ────────────────────────────────────────────────────────────

    def get(self) -> list[str]:
        """Ordered list of provider names to try."""
        return list(self._chain)

    def with_guaranteed_mock(self) -> list[str]:
        """Return chain with mock appended if not already present."""
        chain = list(self._chain)
        if "mock" not in chain:
            chain.append("mock")
        return chain

    def exclude(self, *names: str) -> "FallbackPolicy":
        """Return a new policy with the given providers removed."""
        filtered = [p for p in self._chain if p not in names]
        return FallbackPolicy(chain=filtered)

    def __repr__(self) -> str:
        return f"FallbackPolicy({self._chain})"
