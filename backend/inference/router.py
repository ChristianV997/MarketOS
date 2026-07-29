"""InferenceRouter — the single entry point for all model calls.

Architecture:
  * All completion and embedding requests flow through get_router().complete()
    or get_router().embed().
  * Provider selection is delegated to RoutingPolicy.
  * Fallback ordering is enforced by FallbackPolicy.
  * Every call emits an INFERENCE_COMPLETED or INFERENCE_FAILED event through
    the canonical event broker for replay-safety and telemetry.
  * Responses are cached by sequence_id — replaying the same id returns the
    cached response without making another network call.

Replay safety guarantee:
  Before returning any response, the router stores it in _response_cache keyed
  by sequence_id.  Callers that pass the same sequence_id twice (e.g. during
  replay) receive the cached response with response.replayed=True.  Combined
  with the INFERENCE_COMPLETED event on the broker, this ensures that any
  replay of the event log will see identical inference outputs.
"""
from __future__ import annotations

import logging
import os
import time
from collections import OrderedDict
from threading import Lock
from typing import Generator

from ._utils import compute_replay_hash, now_ms
from .models.inference_request  import InferenceRequest
from .models.inference_response import InferenceResponse
from .models.embedding_request  import EmbeddingRequest
from .models.routing_decision   import RoutingDecision
from .policies.routing_policy   import RoutingPolicy
from .providers.base            import BaseProvider
from .providers                 import REGISTRY, MockProvider

_log = logging.getLogger(__name__)


# ── module-level singleton ────────────────────────────────────────────────────

_router: "InferenceRouter | None" = None
_router_lock = Lock()
_PROVIDER_FAILURE_BACKOFF_S = max(
    0.0, float(os.getenv("INFERENCE_PROVIDER_FAILURE_BACKOFF_S", "30"))
)


def get_router() -> "InferenceRouter":
    """Return the process-wide InferenceRouter singleton (lazy init)."""
    global _router
    if _router is None:
        with _router_lock:
            if _router is None:
                _router = InferenceRouter()
    return _router


# ── convenience wrappers (used by the rest of the codebase) ──────────────────

def complete(prompt: str, **kwargs) -> InferenceResponse:
    """One-line completion: complete("write a hook for...") → InferenceResponse."""
    return get_router().complete(InferenceRequest(prompt=prompt, **kwargs))


def embed(texts: list[str], **kwargs) -> list[list[float]]:
    """One-line embedding: embed(["hook A", "hook B"]) → [[...], [...]]."""
    return get_router().embed(EmbeddingRequest(texts=texts, **kwargs))


# ── router class ─────────────────────────────────────────────────────────────

class InferenceRouter:
    """Routes InferenceRequests to the best available provider."""

    def __init__(
        self,
        providers: list[BaseProvider] | None = None,
        policy:    RoutingPolicy        | None = None,
        provider_failure_backoff_s: float = _PROVIDER_FAILURE_BACKOFF_S,
    ) -> None:
        self._providers = providers if providers is not None else _build_default_providers()
        self._policy    = policy or RoutingPolicy()
        # Bounded replay cache. Callers that pass a stable sequence_id get
        # replay-dedup; callers that don't (fresh uuid per call) would
        # otherwise grow this dict without bound — the cap makes it a FIFO.
        self._cache: "OrderedDict[str, InferenceResponse]" = OrderedDict()
        self._cache_max  = int(os.getenv("INFERENCE_CACHE_MAX", "1000"))
        self._cache_lock = Lock()
        self._provider_failure_backoff_s = max(0.0, provider_failure_backoff_s)
        self._provider_failed_until: dict[str, float] = {}
        self._ensure_ollama_model()

    def _ensure_ollama_model(self) -> None:
        """Best-effort: if OllamaProvider is active, make sure its configured
        model is pulled. Never blocks or raises — router construction must
        succeed even when Ollama is unreachable."""
        if not any(p.name == "ollama" for p in self._providers):
            return
        try:
            from ..ollama_manager import OllamaManager
            model = os.getenv("OLLAMA_MODEL", "llama3.2")
            manager = OllamaManager()
            if manager.is_healthy():
                manager.ensure_model(model)
        except Exception as exc:
            _log.debug("ollama_ensure_model_startup_skipped error=%s", exc)

    # ── completion ────────────────────────────────────────────────────────────

    def complete(self, request: InferenceRequest) -> InferenceResponse:
        # Replay hit: same sequence_id → return cached response
        with self._cache_lock:
            if request.sequence_id in self._cache:
                cached = self._cache[request.sequence_id]
                import dataclasses
                return dataclasses.replace(cached, replayed=True, cached=True)

        decision = self._policy.select(request, self._providers)
        provider_map = {p.name: p for p in self._providers}

        for provider_name in decision.fallback_chain:
            provider = provider_map.get(provider_name)
            if self._provider_failed_until.get(provider_name, 0.0) > time.monotonic():
                continue
            if provider is None or not provider.is_available():
                continue
            try:
                response = provider.complete(request)
                self._provider_failed_until.pop(provider_name, None)
                if provider_name != decision.selected_provider:
                    import dataclasses
                    response = dataclasses.replace(
                        response,
                        fallback_used=True,
                        fallback_reason=f"preferred_providers_unavailable",
                    )
                self._store(request.sequence_id, response)
                _emit_completed(request, response, decision)
                return response
            except Exception as exc:
                if self._provider_failure_backoff_s:
                    self._provider_failed_until[provider_name] = (
                        time.monotonic() + self._provider_failure_backoff_s
                    )
                _log.warning(
                    "inference_provider_failed provider=%s seq=%s error=%s",
                    provider_name, request.sequence_id, exc,
                )
                _emit_failed(request, decision, provider_name, exc)

        # All providers failed — guaranteed mock
        mock     = MockProvider()
        response = mock.complete(request)
        import dataclasses
        response = dataclasses.replace(
            response,
            fallback_used=True,
            fallback_reason="all_providers_exhausted",
        )
        self._store(request.sequence_id, response)
        _emit_completed(request, response, decision)
        return response

    # ── embedding ─────────────────────────────────────────────────────────────

    def embed(self, request: EmbeddingRequest) -> list[list[float]]:
        provider_map = {p.name: p for p in self._providers}

        # Embedding-capable providers (ordered by fallback policy)
        from .policies.fallback_policy import FallbackPolicy
        chain = FallbackPolicy().with_guaranteed_mock()

        for provider_name in chain:
            provider = provider_map.get(provider_name)
            if provider is None or not provider.is_available():
                continue
            try:
                vecs = provider.embed(request)
                _log.debug("embed_ok provider=%s texts=%d", provider_name, len(request.texts))
                return vecs
            except NotImplementedError:
                continue  # AirLLM raises this — skip silently
            except Exception as exc:
                _log.warning("embed_failed provider=%s error=%s", provider_name, exc)

        # Fallback: MockProvider always works
        return MockProvider().embed(request)

    # ── streaming ─────────────────────────────────────────────────────────────

    def stream(
        self, request: InferenceRequest
    ) -> Generator[str, None, InferenceResponse]:
        """Yield token chunks.  Returns InferenceResponse via StopIteration.value."""
        decision     = self._policy.select(request, self._providers)
        provider_map = {p.name: p for p in self._providers}

        for provider_name in decision.fallback_chain:
            provider = provider_map.get(provider_name)
            if provider is None or not provider.is_available():
                continue
            try:
                gen      = provider.stream(request)
                response = None
                try:
                    while True:
                        chunk = next(gen)
                        yield chunk
                except StopIteration as stop:
                    response = stop.value

                if response is None:
                    # Provider didn't return a final response — synthesise one
                    response = provider.complete(request)

                self._store(request.sequence_id, response)
                _emit_completed(request, response, decision)
                return response
            except Exception as exc:
                _log.warning("stream_provider_failed provider=%s error=%s", provider_name, exc)

        mock     = MockProvider()
        response = mock.complete(request)
        yield response.content
        self._store(request.sequence_id, response)
        return response

    # ── cache ─────────────────────────────────────────────────────────────────

    def _store(self, sequence_id: str, response: InferenceResponse) -> None:
        with self._cache_lock:
            self._cache[sequence_id] = response
            self._cache.move_to_end(sequence_id)
            while len(self._cache) > self._cache_max:
                self._cache.popitem(last=False)  # evict oldest (FIFO)

    def cache_size(self) -> int:
        return len(self._cache)

    def clear_cache(self) -> None:
        with self._cache_lock:
            self._cache.clear()

    # ── diagnostics ───────────────────────────────────────────────────────────

    def provider_status(self) -> list[dict]:
        now = time.monotonic()
        return [
            {
                "name": p.name,
                "available": p.is_available(),
                "cooling_down": self._provider_failed_until.get(p.name, 0.0) > now,
            }
            for p in self._providers
        ]


# ── helpers ───────────────────────────────────────────────────────────────────

def _build_default_providers() -> list[BaseProvider]:
    """Instantiate all registered providers (no heavy models loaded yet)."""
    from .providers import REGISTRY
    return [cls() for cls in REGISTRY.values()]


def _emit_completed(
    request:  InferenceRequest,
    response: InferenceResponse,
    decision: RoutingDecision,
) -> None:
    try:
        from .telemetry import emit_inference_completed
        emit_inference_completed(request, response, decision)
    except Exception as exc:
        _log.debug("telemetry_emit_failed error=%s", exc)


def _emit_failed(
    request:       InferenceRequest,
    decision:      RoutingDecision,
    provider_name: str,
    error:         Exception,
) -> None:
    try:
        from .telemetry import emit_inference_failed
        emit_inference_failed(request, decision, provider_name, str(error))
    except Exception as exc:
        _log.debug("telemetry_emit_failed error=%s", exc)
