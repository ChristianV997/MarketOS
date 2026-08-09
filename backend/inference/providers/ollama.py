"""OllamaProvider — local inference via the Ollama HTTP API.

Requires a running Ollama daemon.  No GPU required for small models.
Set OLLAMA_URL (default http://localhost:11434) and OLLAMA_MODEL.
"""
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

_BASE    = os.getenv("OLLAMA_URL",        "http://localhost:11434")
_MODEL   = os.getenv("OLLAMA_MODEL",      "mistral:7b")
_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT_S", "30"))
_HEALTH_TIMEOUT = float(os.getenv("OLLAMA_HEALTH_TIMEOUT_S", "0.25"))


class OllamaProvider(BaseProvider):
    """Ollama local model server — uses httpx (already in requirements)."""

    name = "ollama"

    # ── availability ─────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        try:
            import httpx
            r = httpx.get(f"{_BASE}/api/tags", timeout=_HEALTH_TIMEOUT)
            return r.status_code == 200
        except Exception:
            return False

    # ── inference ─────────────────────────────────────────────────────────────

    def complete(self, request: InferenceRequest) -> InferenceResponse:
        import httpx

        model    = request.model if request.model != "default" else _MODEL
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})

        payload: dict = {
            "model":   model,
            "messages": messages,
            "stream":  False,
            "options": {"temperature": request.temperature, "num_predict": request.max_tokens},
        }
        if request.seed is not None:
            payload["options"]["seed"] = request.seed

        t0   = now_ms()
        resp = httpx.post(f"{_BASE}/api/chat", json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        data    = resp.json()
        content = data.get("message", {}).get("content", "")
        latency = now_ms() - t0

        return InferenceResponse(
            content=content,
            provider="ollama",
            model=model,
            sequence_id=request.sequence_id,
            replay_hash=compute_replay_hash(request),
            latency_ms=latency,
            prompt_tokens=data.get("prompt_eval_count", len(request.prompt.split())),
            completion_tokens=data.get("eval_count", len(content.split())),
        )

    # ── embeddings ────────────────────────────────────────────────────────────

    def embed(self, request: EmbeddingRequest) -> list[list[float]]:
        import httpx, math

        model   = request.model if request.model != "default" else _MODEL
        results = []
        for text in request.texts:
            resp = httpx.post(
                f"{_BASE}/api/embeddings",
                json={"model": model, "prompt": text},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            vec = resp.json().get("embedding", [])
            if request.normalize and vec:
                norm = math.sqrt(sum(x * x for x in vec))
                vec  = [x / norm for x in vec] if norm > 0 else vec
            results.append(vec)
        return results

    # ── streaming ─────────────────────────────────────────────────────────────

    def stream(
        self, request: InferenceRequest
    ) -> Generator[str, None, InferenceResponse]:
        import httpx

        model    = request.model if request.model != "default" else _MODEL
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})

        payload: dict = {
            "model":    model,
            "messages": messages,
            "stream":   True,
            "options":  {"temperature": request.temperature, "num_predict": request.max_tokens},
        }
        if request.seed is not None:
            payload["options"]["seed"] = request.seed

        t0     = now_ms()
        chunks: list[str] = []

        import json as _json
        with httpx.stream("POST", f"{_BASE}/api/chat", json=payload, timeout=_TIMEOUT) as r:
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    data  = _json.loads(line)
                    delta = data.get("message", {}).get("content", "")
                    if delta:
                        chunks.append(delta)
                        yield delta
                except _json.JSONDecodeError:
                    pass

        content = "".join(chunks)
        return InferenceResponse(
            content=content,
            provider="ollama",
            model=model,
            sequence_id=request.sequence_id,
            replay_hash=compute_replay_hash(request),
            latency_ms=now_ms() - t0,
            prompt_tokens=len(request.prompt.split()),
            completion_tokens=len(content.split()),
        )
