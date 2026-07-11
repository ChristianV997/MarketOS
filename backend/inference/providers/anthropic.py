"""AnthropicProvider — cloud completions via the anthropic SDK (Claude models)."""
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

_DEFAULT_CHAT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307")


class AnthropicProvider(BaseProvider):
    """Calls the Anthropic API.  Requires ANTHROPIC_API_KEY environment variable."""

    name = "anthropic"

    def __init__(self) -> None:
        self._client = None  # lazy-loaded

    # ── availability ─────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        if not os.getenv("ANTHROPIC_API_KEY"):
            return False
        try:
            import anthropic  # noqa: F401, PLC0415  lazy import — optional dependency
            return True
        except ImportError:
            return False

    # ── lazy client ───────────────────────────────────────────────────────────

    def _get_client(self):
        if self._client is None:
            import anthropic  # noqa: PLC0415  lazy import — optional dependency
            self._client = anthropic.Anthropic()
        return self._client

    # ── inference ─────────────────────────────────────────────────────────────

    def complete(self, request: InferenceRequest) -> InferenceResponse:
        client = self._get_client()
        model  = request.model if request.model != "default" else _DEFAULT_CHAT_MODEL

        kwargs: dict = dict(
            model=model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            messages=[{"role": "user", "content": request.prompt}],
        )
        if request.system:
            kwargs["system"] = request.system

        t0   = now_ms()
        resp = client.messages.create(**kwargs)
        latency = now_ms() - t0

        content = "".join(
            block.text for block in resp.content if getattr(block, "type", "") == "text"
        )
        usage = getattr(resp, "usage", None)

        return InferenceResponse(
            content=content,
            provider="anthropic",
            model=model,
            sequence_id=request.sequence_id,
            replay_hash=compute_replay_hash(request),
            latency_ms=latency,
            prompt_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            completion_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
        )

    # ── embeddings ────────────────────────────────────────────────────────────

    def embed(self, request: EmbeddingRequest) -> list[list[float]]:
        raise NotImplementedError("Anthropic API does not provide embeddings")

    # ── streaming ─────────────────────────────────────────────────────────────

    def stream(
        self, request: InferenceRequest
    ) -> Generator[str, None, InferenceResponse]:
        client = self._get_client()
        model  = request.model if request.model != "default" else _DEFAULT_CHAT_MODEL

        kwargs: dict = dict(
            model=model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            messages=[{"role": "user", "content": request.prompt}],
        )
        if request.system:
            kwargs["system"] = request.system

        t0     = now_ms()
        chunks: list[str] = []
        with client.messages.stream(**kwargs) as stream:
            for delta in stream.text_stream:
                if delta:
                    chunks.append(delta)
                    yield delta

        content = "".join(chunks)
        return InferenceResponse(
            content=content,
            provider="anthropic",
            model=model,
            sequence_id=request.sequence_id,
            replay_hash=compute_replay_hash(request),
            latency_ms=now_ms() - t0,
            prompt_tokens=len(request.prompt.split()),
            completion_tokens=len(content.split()),
        )
