"""Tests for RoutingPolicy — cost-aware local-provider preference."""
from backend.inference.models.inference_request import InferenceRequest
from backend.inference.policies import FallbackPolicy, RoutingPolicy
from backend.inference.policies.cost_policy import CostPolicy
from backend.inference.providers.base import BaseProvider


class _AvailableProvider(BaseProvider):
    def __init__(self, name: str):
        self.name = name

    def is_available(self) -> bool:
        return True

    def complete(self, request): ...
    def embed(self, request): ...


def _req(**kwargs) -> InferenceRequest:
    return InferenceRequest(prompt="test", sequence_id="rp-test", **kwargs)


# ── prefer-local re-ranking ────────────────────────────────────────────────────

def test_prefers_free_local_provider_over_paid_when_reordered():
    # Chain deliberately puts the paid provider first; cost ranking should
    # still select the free local one.
    policy = RoutingPolicy(fallback=FallbackPolicy(["openai", "ollama", "mock"]))
    providers = [_AvailableProvider("openai"), _AvailableProvider("ollama"), _AvailableProvider("mock")]
    decision = policy.select(_req(), providers)

    assert decision.selected_provider == "ollama"
    assert decision.reason == "lowest_cost_available"


def test_mock_never_jumps_ahead_of_paid_provider_when_no_free_provider_available():
    class UnavailableOllama(_AvailableProvider):
        def is_available(self) -> bool:
            return False

    policy = RoutingPolicy(fallback=FallbackPolicy(["ollama", "openai", "mock"]))
    providers = [UnavailableOllama("ollama"), _AvailableProvider("openai"), _AvailableProvider("mock")]
    decision = policy.select(_req(), providers)

    # Mock costs 0, same as ollama, but must not outrank openai just because
    # ollama (the only other free provider) is unavailable.
    assert decision.selected_provider == "openai"


def test_prefer_local_disabled_falls_back_to_declared_order():
    policy = RoutingPolicy(
        fallback=FallbackPolicy(["openai", "ollama", "mock"]),
        prefer_local=False,
    )
    providers = [_AvailableProvider("openai"), _AvailableProvider("ollama"), _AvailableProvider("mock")]
    decision = policy.select(_req(), providers)

    assert decision.selected_provider == "openai"
    assert decision.reason == "first_available"


def test_unavailable_ollama_falls_through_to_cloud_provider():
    class UnavailableOllama(_AvailableProvider):
        def is_available(self) -> bool:
            return False

    policy = RoutingPolicy(fallback=FallbackPolicy(["ollama", "openai", "mock"]))
    providers = [UnavailableOllama("ollama"), _AvailableProvider("openai"), _AvailableProvider("mock")]
    decision = policy.select(_req(), providers)

    assert decision.selected_provider == "openai"


def test_cost_rank_preserves_relative_order_among_equal_cost_providers():
    policy = RoutingPolicy(fallback=FallbackPolicy(["vllm", "ollama", "airllm", "mock"]))
    providers = [
        _AvailableProvider("vllm"),
        _AvailableProvider("ollama"),
        _AvailableProvider("airllm"),
        _AvailableProvider("mock"),
    ]
    decision = policy.select(_req(), providers)

    # All free/local and available: stable sort keeps declared order, so
    # the first-declared free provider (vllm) wins, not an arbitrary one.
    assert decision.selected_provider == "vllm"
    assert decision.fallback_chain == ["vllm", "ollama", "airllm", "mock"]


def test_cost_policy_rank_by_cost_sorts_cheapest_first():
    cost = CostPolicy()
    ranked = cost.rank_by_cost(
        ["openai", "ollama"],
        {"openai": "gpt-4o", "ollama": "mistral:7b"},
        max_tokens=512,
    )
    assert ranked == ["ollama", "openai"]
