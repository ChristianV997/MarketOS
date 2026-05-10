"""backend.inference — centralized inference kernel for my_OS.

ALL model calls in the codebase route through this package.

Quick-start:
    from backend.inference import complete, embed, get_router

    resp = complete("Write 5 TikTok hooks for wireless earbuds")
    # → InferenceResponse(content="...", provider="ollama", latency_ms=312, ...)

    vecs = embed(["hook A", "hook B"])
    # → [[0.12, -0.34, ...], [...]]  — one 384-dim vector per text

Provider priority (override via INFERENCE_PROVIDERS env var):
    ollama → openai → airllm → vllm → andromeda → litellm → mock

Replay safety:
    Every response is cached by sequence_id and emitted as an
    INFERENCE_COMPLETED event through the canonical pubsub broker.
    Passing the same sequence_id twice returns the cached response
    (response.replayed=True) without a provider call.

AirLLM note:
    Install with:  pip install airllm
    Set AIRLLM_MODEL, AIRLLM_COMPRESSION (default: 4bit), AIRLLM_CACHE_DIR.
    AirLLM streams 70B+ model layers from disk — works on 4 GB VRAM.
"""
from .router      import complete, embed, get_router, InferenceRouter
from .embeddings  import (
    embed_text,
    embed_batch,
    embed_hooks,
    embed_products,
    embed_campaigns,
    embed_angles,
    similarity,
    top_k_similar,
)
from .models      import InferenceRequest, InferenceResponse, EmbeddingRequest, RoutingDecision
from .scheduling  import get_scheduler, InferenceScheduler
from .fallback    import get_chain
from .quantization import get_config as get_quantization_config, detect_best_config

__all__ = [
    # One-liners
    "complete",
    "embed",
    # Router
    "get_router",
    "InferenceRouter",
    # Embedding helpers
    "embed_text",
    "embed_batch",
    "embed_hooks",
    "embed_products",
    "embed_campaigns",
    "embed_angles",
    "similarity",
    "top_k_similar",
    # Data models
    "InferenceRequest",
    "InferenceResponse",
    "EmbeddingRequest",
    "RoutingDecision",
    # Scheduler
    "get_scheduler",
    "InferenceScheduler",
    # Config
    "get_chain",
    "get_quantization_config",
    "detect_best_config",
]
