"""BaseProvider — abstract contract every inference provider must satisfy."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generator

from ..models.inference_request import InferenceRequest
from ..models.inference_response import InferenceResponse
from ..models.embedding_request import EmbeddingRequest


class BaseProvider(ABC):
    """Minimal interface for a model provider.

    Providers are stateless routing targets.  All side-effects (telemetry,
    caching, fallback) belong to the router layer above.
    """

    name: str = "base"

    # ── availability ──────────────────────────────────────────────────────────

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the provider is configured and available (offline check)."""

    def probe(self) -> bool:
        """Explicit network or state probe. Defaults to returning is_available()."""
        return self.is_available()

    # ── inference ─────────────────────────────────────────────────────────────

    @abstractmethod
    def complete(self, request: InferenceRequest) -> InferenceResponse:
        """Run a synchronous completion and return a full response."""

    # ── embeddings ────────────────────────────────────────────────────────────

    @abstractmethod
    def embed(self, request: EmbeddingRequest) -> list[list[float]]:
        """Return one embedding vector per text in request.texts."""

    # ── streaming (optional override) ─────────────────────────────────────────

    def stream(
        self, request: InferenceRequest
    ) -> Generator[str, None, InferenceResponse]:
        """Yield token chunks, then return the final InferenceResponse.

        Default implementation buffers the full response and yields it as a
        single chunk — providers override this for true streaming.
        """
        response = self.complete(request)
        yield response.content
        return response

    # ── repr ──────────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        available = "✓" if self.is_available() else "✗"
        return f"<Provider:{self.name} {available}>"
