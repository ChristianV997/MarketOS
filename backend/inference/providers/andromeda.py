"""AndromedaProvider — OpenAI-compatible HTTP access for Meta Andromeda backends."""
from __future__ import annotations

import os
from typing import Generator

from .._utils import compute_replay_hash, now_ms
from ..models.embedding_request import EmbeddingRequest
from ..models.inference_request import InferenceRequest
from ..models.inference_response import InferenceResponse
from .base import BaseProvider

_ENDPOINT = os.getenv("ANDROMEDA_ENDPOINT", "")
_MODEL = os.getenv("ANDROMEDA_MODEL", "meta-andromeda")
_API_KEY = os.getenv("ANDROMEDA_API_KEY", "")
_TIMEOUT = float(os.getenv("ANDROMEDA_TIMEOUT_S", "60"))


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if _API_KEY:
        headers["Authorization"] = f"Bearer {_API_KEY}"
    return headers


class AndromedaProvider(BaseProvider):
    """Connects to a running Andromeda-compatible HTTP endpoint."""

    name = "andromeda"

    def is_available(self) -> bool:
        if not _ENDPOINT:
            return False
        try:
            import httpx

            response = httpx.get(f"{_ENDPOINT}/health", timeout=2.0, headers=_headers())
            return response.status_code == 200
        except Exception:
            return False

    def complete(self, request: InferenceRequest) -> InferenceResponse:
        import httpx

        model = request.model if request.model != "default" else _MODEL
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})

        payload: dict[str, object] = {
            "model": model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.seed is not None:
            payload["seed"] = request.seed

        t0 = now_ms()
        response = httpx.post(
            f"{_ENDPOINT}/v1/chat/completions",
            json=payload,
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})

        return InferenceResponse(
            content=content,
            provider="andromeda",
            model=model,
            sequence_id=request.sequence_id,
            replay_hash=compute_replay_hash(request),
            latency_ms=now_ms() - t0,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )

    def embed(self, request: EmbeddingRequest) -> list[list[float]]:
        import httpx
        import math

        model = request.model if request.model != "default" else _MODEL
        response = httpx.post(
            f"{_ENDPOINT}/v1/embeddings",
            json={"model": model, "input": request.texts},
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        vectors = [item["embedding"] for item in sorted(data["data"], key=lambda item: item["index"])]
        if not request.normalize:
            return vectors

        normalized: list[list[float]] = []
        for vector in vectors:
            norm = math.sqrt(sum(value * value for value in vector))
            normalized.append([value / norm for value in vector] if norm > 0 else vector)
        return normalized

    def stream(
        self, request: InferenceRequest
    ) -> Generator[str, None, InferenceResponse]:
        import httpx
        import json as _json

        model = request.model if request.model != "default" else _MODEL
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})

        payload: dict[str, object] = {
            "model": model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": True,
        }
        if request.seed is not None:
            payload["seed"] = request.seed

        t0 = now_ms()
        chunks: list[str] = []
        with httpx.stream(
            "POST",
            f"{_ENDPOINT}/v1/chat/completions",
            json=payload,
            headers=_headers(),
            timeout=_TIMEOUT,
        ) as response:
            for line in response.iter_lines():
                if not line or line == "data: [DONE]":
                    continue
                raw = line.removeprefix("data: ")
                try:
                    delta = _json.loads(raw)["choices"][0]["delta"].get("content", "")
                except (_json.JSONDecodeError, KeyError, IndexError, TypeError):
                    delta = ""
                if delta:
                    chunks.append(delta)
                    yield delta

        content = "".join(chunks)
        # Streaming responses often omit usage metadata until the stream closes,
        # so these token counts are an explicit fallback approximation.
        return InferenceResponse(
            content=content,
            provider="andromeda",
            model=model,
            sequence_id=request.sequence_id,
            replay_hash=compute_replay_hash(request),
            latency_ms=now_ms() - t0,
            prompt_tokens=len(request.prompt.split()),
            completion_tokens=len(content.split()),
        )
