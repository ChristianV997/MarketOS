"""RoutingPolicy — selects provider + model for a given InferenceRequest.

Selection logic:
  1. Read ordered chain from FallbackPolicy (env override respected).
  2. Filter to providers registered in the router's provider map.
  3. If PREFER_LOCAL_INFERENCE is on (default), re-sort the non-mock
     portion of the chain cheapest-first via CostPolicy.rank_by_cost() —
     this keeps free local providers (Ollama, AirLLM, vLLM, ...) ahead of
     paid cloud providers even if INFERENCE_PROVIDERS reorders the chain,
     without letting Mock jump the queue ahead of real paid providers.
  4. Skip providers that are unavailable or over the cost cap.
  5. First surviving provider wins.
  6. Mock is appended as an unconditional last resort.
"""
from __future__ import annotations

import logging
import os

from ..models.inference_request import InferenceRequest
from ..models.routing_decision import RoutingDecision
from ..providers.base import BaseProvider
from .cost_policy import CostPolicy
from .fallback_policy import FallbackPolicy

_log = logging.getLogger(__name__)

_PREFER_LOCAL_DEFAULT = os.getenv("PREFER_LOCAL_INFERENCE", "true").lower() == "true"

# Each provider module reads its own default model from this env var at
# import time (e.g. backend/inference/providers/openai.py reads OPENAI_MODEL).
# Mirrored here so _resolve_model can estimate a real cost for the "default"
# model case without every provider having to expose it as an instance attr.
_DEFAULT_MODEL_ENV: dict[str, tuple[str, str]] = {
    "openai":    ("OPENAI_MODEL",    "gpt-4o-mini"),
    "anthropic": ("ANTHROPIC_MODEL", "claude-3-haiku-20240307"),
    "ollama":    ("OLLAMA_MODEL",    "mistral:7b"),
    "airllm":    ("AIRLLM_MODEL",    "meta-llama/Llama-3.2-1B"),
    "vllm":      ("VLLM_MODEL",      "meta-llama/Llama-3.2-1B"),
    "andromeda": ("ANDROMEDA_MODEL", "meta-andromeda"),
    "litellm":   ("LITELLM_MODEL",   "openai/gpt-4o-mini"),
}


class RoutingPolicy:
    def __init__(
        self,
        fallback:     FallbackPolicy | None = None,
        cost:         CostPolicy    | None = None,
        prefer_local: bool | None = None,
    ) -> None:
        self._fallback     = fallback or FallbackPolicy()
        self._cost         = cost     or CostPolicy()
        self._prefer_local = _PREFER_LOCAL_DEFAULT if prefer_local is None else prefer_local

    def select(
        self,
        request:   InferenceRequest,
        providers: list[BaseProvider],
    ) -> RoutingDecision:
        """Return a RoutingDecision indicating which provider to try first and
        the full ordered fallback chain."""
        provider_map = {p.name: p for p in providers}
        chain        = self._fallback.with_guaranteed_mock()

        # Restrict chain to registered providers
        chain = [name for name in chain if name in provider_map]
        if not chain:
            chain = ["mock"]

        reason_first = "first_available"
        if self._prefer_local:
            chain, reason_first = self._cost_rank(chain, request, provider_map)

        selected  = "mock"
        model     = "mock-1.0"
        reason    = "no_providers_available"

        for name in chain:
            p = provider_map.get(name)
            if p is None:
                continue
            if not p.is_available():
                _log.debug("provider_unavailable provider=%s", name)
                continue
            candidate_model = self._resolve_model(request, p)
            if not self._cost.is_affordable(name, candidate_model, request.max_tokens):
                _log.debug("provider_over_budget provider=%s model=%s", name, candidate_model)
                continue

            selected = name
            model    = candidate_model
            reason   = reason_first
            break

        return RoutingDecision(
            sequence_id=request.sequence_id,
            selected_provider=selected,
            selected_model=model,
            reason=reason,
            fallback_chain=chain,
            cost_estimate_usd=self._cost.estimate(selected, model, request.max_tokens),
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    def _cost_rank(
        self,
        chain:        list[str],
        request:      InferenceRequest,
        provider_map: dict[str, BaseProvider],
    ) -> tuple[list[str], str]:
        """Re-sort the non-mock portion of chain cheapest-first.

        Mock is excluded from ranking and re-appended last: it has zero
        cost like several local providers, so ranking it in would let it
        jump ahead of paid cloud providers whenever no free provider is
        available — defeating "mock is the guaranteed last resort".
        """
        has_mock = "mock" in chain
        rankable = [name for name in chain if name != "mock"]
        model_map = {
            name: self._resolve_model(request, provider_map[name])
            for name in rankable
        }
        ranked = self._cost.rank_by_cost(rankable, model_map, request.max_tokens)
        if has_mock:
            ranked = ranked + ["mock"]
        return ranked, "lowest_cost_available"

    @staticmethod
    def _resolve_model(request: InferenceRequest, provider: BaseProvider) -> str:
        if request.model != "default":
            return request.model
        explicit = getattr(provider, f"_{provider.name}_model", None) or \
                   getattr(provider, "_model", None)
        if isinstance(explicit, str) and explicit:
            return explicit
        env_name, default = _DEFAULT_MODEL_ENV.get(provider.name, (None, None))
        if env_name is not None:
            return os.getenv(env_name, default)
        return "default"
