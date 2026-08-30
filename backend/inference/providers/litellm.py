"""LiteLLMProvider — unified multi-provider proxy via the litellm library.

LiteLLM maps 100+ providers to a single OpenAI-compatible interface.
Use it when you want a single config string to switch between providers
without maintaining separate provider classes.

Environment variables:
  LITELLM_MODEL   Model string (e.g. "openai/gpt-4o-mini", "ollama/llama3")
  LITELLM_*       All standard LiteLLM credential vars are passed through.

Install (optional — not in base requirements):
  pip install litellm
"""
from __future__ import annotations

import logging
import os
from typing import Generator

from .._utils import compute_replay_hash, now_ms
from ..models.embedding_request import EmbeddingRequest
from ..models.inference_request import InferenceRequest
from ..models.inference_response import InferenceResponse
from .base import BaseProvider

_log = logging.getLogger(__name__)

_MODEL   = os.getenv("LITELLM_MODEL", "openai/gpt-4o-mini")
_TIMEOUT = float(os.getenv("LITELLM_TIMEOUT_S", "30"))


_EXPLICIT_ENABLED = os.getenv("LITELLM_ENABLED", "false").lower() == "true"

class LiteLLMProvider(BaseProvider):
    """Thin wrapper around litellm.completion — enables any provider with one import."""

    name = "litellm"

    def is_available(self) -> bool:
        if not _EXPLICIT_ENABLED:
            return False
        try:
            import litellm  # noqa: F401
            return True
        except ImportError:
            return False

    def probe(self) -> bool:
        # LiteLLM availability check must not perform provider calls
        return self.is_available()

    def complete(self, request: InferenceRequest) -> InferenceResponse:
        import litellm  # noqa: PLC0415

        model    = request.model if request.model != "default" else _MODEL
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})

        kwargs: dict = dict(
            model=model,
            messages=messages,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            timeout=_TIMEOUT,
        )
        if request.seed is not None:
            kwargs["seed"] = request.seed

        t0   = now_ms()
        resp = litellm.completion(**kwargs)
        latency = now_ms() - t0

        content = resp.choices[0].message.content or ""
        usage   = resp.usage or type("U", (), {"prompt_tokens": 0, "completion_tokens": 0})()

        return InferenceResponse(
            content=content,
            provider="litellm",
            model=model,
            sequence_id=request.sequence_id,
            replay_hash=compute_replay_hash(request),
            latency_ms=latency,
            prompt_tokens=getattr(usage, "prompt_tokens", 0),
            completion_tokens=getattr(usage, "completion_tokens", 0),
        )

    def embed(self, request: EmbeddingRequest) -> list[list[float]]:
        import litellm, math  # noqa: PLC0415

        model = request.model if request.model != "default" else "openai/text-embedding-3-small"
        resp  = litellm.embedding(model=model, input=request.texts)
        vecs  = [item["embedding"] for item in resp["data"]]
        if request.normalize:
            out = []
            for v in vecs:
                norm = math.sqrt(sum(x * x for x in v))
                out.append([x / norm for x in v] if norm > 0 else v)
            return out
        return vecs

    def stream(
        self, request: InferenceRequest
    ) -> Generator[str, None, InferenceResponse]:
        import litellm  # noqa: PLC0415

        model    = request.model if request.model != "default" else _MODEL
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})

        kwargs: dict = dict(
            model=model,
            messages=messages,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            stream=True,
        )
        if request.seed is not None:
            kwargs["seed"] = request.seed

        t0     = now_ms()
        chunks: list[str] = []

        for chunk in litellm.completion(**kwargs):
            delta = chunk.choices[0].delta.content or ""
            if delta:
                chunks.append(delta)
                yield delta

        content = "".join(chunks)
        return InferenceResponse(
            content=content,
            provider="litellm",
            model=model,
            sequence_id=request.sequence_id,
            replay_hash=compute_replay_hash(request),
            latency_ms=now_ms() - t0,
            prompt_tokens=len(request.prompt.split()),
            completion_tokens=len(content.split()),
        )
