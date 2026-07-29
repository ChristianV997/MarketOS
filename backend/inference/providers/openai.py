"""OpenAIProvider — cloud completions + embeddings via the openai SDK."""
from __future__ import annotations

import logging
import os
import time
from typing import Generator

from .._utils import compute_replay_hash, now_ms
from ..models.embedding_request import EmbeddingRequest
from ..models.inference_request import InferenceRequest
from ..models.inference_response import InferenceResponse
from .base import BaseProvider

_log = logging.getLogger(__name__)

_DEFAULT_CHAT_MODEL  = os.getenv("OPENAI_MODEL",       "gpt-4o-mini")
_DEFAULT_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
_EMBED_DIM           = 1536  # text-embedding-3-small default dimension
_TIMEOUT_S           = float(os.getenv("OPENAI_TIMEOUT_S", "10"))


class OpenAIProvider(BaseProvider):
    """Calls the OpenAI API.  Requires OPENAI_API_KEY environment variable."""

    name = "openai"

    def __init__(self) -> None:
        self._client = None  # lazy-loaded

    # ── availability ─────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY"))

    # ── lazy client ───────────────────────────────────────────────────────────

    def _get_client(self):
        if self._client is None:
            import openai  # noqa: PLC0415  lazy import — optional dependency
            self._client = openai.OpenAI(
                api_key=os.getenv("OPENAI_API_KEY"),
                timeout=_TIMEOUT_S,
                max_retries=0,
            )
        return self._client

    # ── inference ─────────────────────────────────────────────────────────────

    def complete(self, request: InferenceRequest) -> InferenceResponse:
        client    = self._get_client()
        model     = request.model if request.model != "default" else _DEFAULT_CHAT_MODEL
        messages  = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})

        kwargs: dict = dict(
            model=model,
            messages=messages,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
        )
        if request.seed is not None:
            kwargs["seed"] = request.seed

        t0 = now_ms()
        resp = client.chat.completions.create(**kwargs)
        latency = now_ms() - t0

        content = resp.choices[0].message.content or ""
        usage   = resp.usage or type("U", (), {"prompt_tokens": 0, "completion_tokens": 0})()

        return InferenceResponse(
            content=content,
            provider="openai",
            model=model,
            sequence_id=request.sequence_id,
            replay_hash=compute_replay_hash(request),
            latency_ms=latency,
            prompt_tokens=getattr(usage, "prompt_tokens", 0),
            completion_tokens=getattr(usage, "completion_tokens", 0),
        )

    # ── embeddings ────────────────────────────────────────────────────────────

    def embed(self, request: EmbeddingRequest) -> list[list[float]]:
        client = self._get_client()
        model  = request.model if request.model != "default" else _DEFAULT_EMBED_MODEL
        resp   = client.embeddings.create(input=request.texts, model=model)
        vecs   = [item.embedding for item in sorted(resp.data, key=lambda x: x.index)]
        if request.normalize:
            import math
            out = []
            for v in vecs:
                norm = math.sqrt(sum(x * x for x in v))
                out.append([x / norm for x in v] if norm > 0 else v)
            return out
        return vecs

    # ── streaming ─────────────────────────────────────────────────────────────

    def stream(
        self, request: InferenceRequest
    ) -> Generator[str, None, InferenceResponse]:
        client   = self._get_client()
        model    = request.model if request.model != "default" else _DEFAULT_CHAT_MODEL
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
        for chunk in client.chat.completions.create(**kwargs):
            delta = chunk.choices[0].delta.content or ""
            if delta:
                chunks.append(delta)
                yield delta

        content = "".join(chunks)
        return InferenceResponse(
            content=content,
            provider="openai",
            model=model,
            sequence_id=request.sequence_id,
            replay_hash=compute_replay_hash(request),
            latency_ms=now_ms() - t0,
            prompt_tokens=len(request.prompt.split()),
            completion_tokens=len(content.split()),
        )
