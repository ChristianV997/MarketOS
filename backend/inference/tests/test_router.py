"""Tests for InferenceRouter — routing, fallback, and provider selection."""
import pytest

from backend.inference.models.inference_request  import InferenceRequest
from backend.inference.models.embedding_request  import EmbeddingRequest
from backend.inference.providers.mock            import MockProvider
from backend.inference.providers.base            import BaseProvider
from backend.inference.models.inference_response import InferenceResponse
from backend.inference.router                    import InferenceRouter


# ── helpers ───────────────────────────────────────────────────────────────────

class AlwaysFailProvider(BaseProvider):
    name = "always_fail"

    def is_available(self) -> bool:
        return True

    def complete(self, request):
        raise RuntimeError("intentional test failure")

    def embed(self, request):
        raise RuntimeError("intentional test failure")


class AlwaysUnavailableProvider(BaseProvider):
    name = "always_unavailable"

    def is_available(self) -> bool:
        return False

    def complete(self, request): ...
    def embed(self, request): ...


# ── router basics ─────────────────────────────────────────────────────────────

def test_router_returns_response_with_mock():
    router = InferenceRouter(providers=[MockProvider()])
    req    = InferenceRequest(prompt="test prompt", sequence_id="t001")
    resp   = router.complete(req)

    assert isinstance(resp, InferenceResponse)
    assert resp.ok
    assert resp.sequence_id == "t001"
    assert resp.provider == "mock"
    assert resp.content


def test_router_uses_mock_when_no_providers():
    router = InferenceRouter(providers=[AlwaysUnavailableProvider()])
    req    = InferenceRequest(prompt="test", sequence_id="t002")
    resp   = router.complete(req)

    # Should fall back to MockProvider internally
    assert resp.ok
    assert resp.provider in ("mock", "always_unavailable")


def test_router_fallback_on_provider_failure():
    from backend.inference.policies import RoutingPolicy, FallbackPolicy
    # Explicit chain: always_fail first, then mock
    policy = RoutingPolicy(fallback=FallbackPolicy(["always_fail", "mock"]))
    router = InferenceRouter(providers=[AlwaysFailProvider(), MockProvider()], policy=policy)
    req    = InferenceRequest(prompt="fallback test", sequence_id="t003")
    resp   = router.complete(req)

    assert resp.ok
    assert resp.provider == "mock"
    assert resp.fallback_used


def test_router_fallback_reason_set():
    from backend.inference.policies import RoutingPolicy, FallbackPolicy
    policy = RoutingPolicy(fallback=FallbackPolicy(["always_fail", "mock"]))
    router = InferenceRouter(providers=[AlwaysFailProvider(), MockProvider()], policy=policy)
    req    = InferenceRequest(prompt="fallback reason", sequence_id="t004")
    resp   = router.complete(req)

    assert resp.fallback_reason is not None


def test_router_cools_down_failed_provider_between_requests():
    from backend.inference.policies import RoutingPolicy, FallbackPolicy

    class CountingFailureProvider(AlwaysFailProvider):
        name = "counting_failure"

        def __init__(self):
            self.calls = 0

        def complete(self, request):
            self.calls += 1
            raise RuntimeError("offline")

    failing = CountingFailureProvider()
    policy = RoutingPolicy(fallback=FallbackPolicy(["counting_failure", "mock"]))
    router = InferenceRouter(
        providers=[failing, MockProvider()],
        policy=policy,
        provider_failure_backoff_s=60.0,
    )

    router.complete(InferenceRequest(prompt="first", sequence_id="cooldown-1"))
    router.complete(InferenceRequest(prompt="second", sequence_id="cooldown-2"))

    assert failing.calls == 1
    status = next(item for item in router.provider_status() if item["name"] == "counting_failure")
    assert status["cooling_down"] is True


# ── embedding ─────────────────────────────────────────────────────────────────

def test_router_embed_returns_vectors():
    router = InferenceRouter(providers=[MockProvider()])
    req    = EmbeddingRequest(texts=["hook A", "hook B"], sequence_id="emb001")
    vecs   = router.embed(req)

    assert len(vecs) == 2
    assert all(isinstance(v, list) and len(v) == 384 for v in vecs)


def test_router_embed_empty_input():
    router = InferenceRouter(providers=[MockProvider()])
    req    = EmbeddingRequest(texts=[], sequence_id="emb002")
    vecs   = router.embed(req)
    assert vecs == []


def test_router_embed_normalised():
    import math
    router = InferenceRouter(providers=[MockProvider()])
    req    = EmbeddingRequest(texts=["normalise me"], normalize=True)
    vecs   = router.embed(req)
    norm   = math.sqrt(sum(x * x for x in vecs[0]))
    assert abs(norm - 1.0) < 1e-6


# ── provider status ───────────────────────────────────────────────────────────

def test_router_provider_status():
    router = InferenceRouter(providers=[MockProvider(), AlwaysUnavailableProvider()])
    status = router.provider_status()

    names = {s["name"] for s in status}
    assert "mock"              in names
    assert "always_unavailable" in names

    mock_status = next(s for s in status if s["name"] == "mock")
    assert mock_status["available"] is True

    ua_status = next(s for s in status if s["name"] == "always_unavailable")
    assert ua_status["available"] is False


# ── cache ─────────────────────────────────────────────────────────────────────

def test_router_cache_tracks_responses():
    router = InferenceRouter(providers=[MockProvider()])
    req    = InferenceRequest(prompt="cache test", sequence_id="cache001")
    router.complete(req)
    assert router.cache_size() == 1


def test_router_clear_cache():
    router = InferenceRouter(providers=[MockProvider()])
    router.complete(InferenceRequest(prompt="x", sequence_id="c1"))
    router.complete(InferenceRequest(prompt="y", sequence_id="c2"))
    assert router.cache_size() == 2
    router.clear_cache()
    assert router.cache_size() == 0
