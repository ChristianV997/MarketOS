"""VLLMProvider — OpenAI-compatible HTTP interface to a vLLM inference server.

vLLM exposes an OpenAI-compatible REST API.  This provider calls it via
httpx so it works without the openai SDK, and without installing vllm itself
in this process.

Environment variables:
  VLLM_ENDPOINT   Base URL of vLLM server  (default: http://localhost:8001)
  VLLM_MODEL      Model name served        (default: meta-llama/Llama-3.2-1B)
  VLLM_API_KEY    Optional bearer token    (default: none)
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

_ENDPOINT = os.getenv("VLLM_ENDPOINT", "http://localhost:8001")
_MODEL    = os.getenv("VLLM_MODEL",    "meta-llama/Llama-3.2-1B")
_API_KEY  = os.getenv("VLLM_API_KEY",  "")
_TIMEOUT  = float(os.getenv("VLLM_TIMEOUT_S", "60"))
_HEALTH_TIMEOUT = float(os.getenv("VLLM_HEALTH_TIMEOUT_S", "0.25"))


def _headers() -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if _API_KEY:
        h["Authorization"] = f"Bearer {_API_KEY}"
    return h


class VLLMProvider(BaseProvider):
    """Connects to a running vLLM HTTP server (no in-process GPU required)."""

    name = "vllm"

    def is_available(self) -> bool:
        try:
            import httpx
            r = httpx.get(f"{_ENDPOINT}/health", timeout=_HEALTH_TIMEOUT)
            return r.status_code == 200
        except Exception:
            return False

    def complete(self, request: InferenceRequest) -> InferenceResponse:
        import httpx

        model    = request.model if request.model != "default" else _MODEL
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})

        payload: dict = {
            "model":       model,
            "messages":    messages,
            "max_tokens":  request.max_tokens,
            "temperature": request.temperature,
        }
        if request.seed is not None:
            payload["seed"] = request.seed

        t0   = now_ms()
        resp = httpx.post(
            f"{_ENDPOINT}/v1/chat/completions",
            json=payload,
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data    = resp.json()
        content = data["choices"][0]["message"]["content"]
        usage   = data.get("usage", {})

        return InferenceResponse(
            content=content,
            provider="vllm",
            model=model,
            sequence_id=request.sequence_id,
            replay_hash=compute_replay_hash(request),
            latency_ms=now_ms() - t0,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )

    def embed(self, request: EmbeddingRequest) -> list[list[float]]:
        import httpx, math

        model = request.model if request.model != "default" else _MODEL
        resp  = httpx.post(
            f"{_ENDPOINT}/v1/embeddings",
            json={"model": model, "input": request.texts},
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        vecs = [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]
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
        import httpx, json as _json

        model    = request.model if request.model != "default" else _MODEL
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})

        payload: dict = {
            "model":       model,
            "messages":    messages,
            "max_tokens":  request.max_tokens,
            "temperature": request.temperature,
            "stream":      True,
        }
        if request.seed is not None:
            payload["seed"] = request.seed

        t0     = now_ms()
        chunks: list[str] = []

        with httpx.stream(
            "POST", f"{_ENDPOINT}/v1/chat/completions",
            json=payload, headers=_headers(), timeout=_TIMEOUT,
        ) as r:
            for line in r.iter_lines():
                if not line or line == "data: [DONE]":
                    continue
                raw = line.removeprefix("data: ")
                try:
                    delta = _json.loads(raw)["choices"][0]["delta"].get("content", "")
                    if delta:
                        chunks.append(delta)
                        yield delta
                except (_json.JSONDecodeError, KeyError):
                    pass

        content = "".join(chunks)
        return InferenceResponse(
            content=content,
            provider="vllm",
            model=model,
            sequence_id=request.sequence_id,
            replay_hash=compute_replay_hash(request),
            latency_ms=now_ms() - t0,
            prompt_tokens=len(request.prompt.split()),
            completion_tokens=len(content.split()),
        )
