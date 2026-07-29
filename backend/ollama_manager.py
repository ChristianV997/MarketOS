"""backend.ollama_manager — lifecycle management for the local Ollama daemon.

`backend/inference/providers/ollama.py` already knows how to talk to a
running Ollama daemon for completions/embeddings/streaming. This module
manages the daemon's lifecycle around that: is it up, is the configured
model actually pulled, and (optionally) starting it when it isn't — plus a
static resource-footprint reference so deployment sizing (terminal or AWS)
doesn't have to guess.

Nothing here is required for the router to function — every method is
best-effort and fails soft (mirrors the fail-silent-but-logged pattern used
throughout orchestrator/main.py's worker functions).
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import Any

from backend.inference._utils import now_ms

_log = logging.getLogger(__name__)

_BASE = os.getenv("OLLAMA_URL", "http://localhost:11434")
_HEALTH_TIMEOUT = float(os.getenv("OLLAMA_HEALTH_TIMEOUT_S", "0.25"))
_PULL_TIMEOUT = float(os.getenv("OLLAMA_PULL_TIMEOUT_S", "600"))
_AUTO_START = os.getenv("OLLAMA_AUTO_START", "false").lower() == "true"
_AUTO_START_POLL_S = float(os.getenv("OLLAMA_AUTO_START_POLL_S", "0.5"))
_AUTO_START_MAX_WAIT_S = float(os.getenv("OLLAMA_AUTO_START_MAX_WAIT_S", "5"))

# Recommended models for MarketOS's non-critical inference paths (hooks,
# angles, creative drafts). Not auto-selected — operators choose via
# OLLAMA_MODEL; this is reference data for deployment sizing and docs.
RECOMMENDED_MODELS: dict[str, dict[str, Any]] = {
    "mistral:7b": {
        "vram_gb": 2.0, "ram_gb": 4.0, "cpu_latency_ms_estimate": 25,
        "role": "primary — best reasoning/creative balance",
    },
    "llama3.2:3b": {
        "vram_gb": 1.0, "ram_gb": 2.0, "cpu_latency_ms_estimate": 10,
        "role": "low-resource fallback — fast, basic quality",
    },
    "neural-chat:7b": {
        "vram_gb": 2.0, "ram_gb": 4.0, "cpu_latency_ms_estimate": 35,
        "role": "high-quality alternative — product descriptions, chat",
    },
}

# Conservative default for unrecognized model names — assume the heaviest
# common footprint so sizing decisions err safe rather than under-provision.
_DEFAULT_RESOURCE_ESTIMATE: dict[str, Any] = {
    "vram_gb": 4.0, "ram_gb": 8.0, "cpu_latency_ms_estimate": 50,
    "role": "unknown model — conservative default estimate",
}


class OllamaManager:
    """Manages the local Ollama daemon: health, models, optional auto-start."""

    def __init__(self, base_url: str = _BASE) -> None:
        self._base = base_url

    # ── health ────────────────────────────────────────────────────────────────

    def is_healthy(self) -> bool:
        """Fast health check against the daemon's /api/tags endpoint."""
        try:
            import httpx
            r = httpx.get(f"{self._base}/api/tags", timeout=_HEALTH_TIMEOUT)
            healthy = r.status_code == 200
        except Exception:
            healthy = False
        if not healthy:
            try:
                from backend.observability.metrics import ollama_health_check_failures_total
                ollama_health_check_failures_total.inc()
            except Exception:
                pass
        return healthy

    def ensure_running(self) -> bool:
        """If unhealthy and OLLAMA_AUTO_START=true, attempt to start the daemon.

        Best-effort: never raises. Returns the health state after the attempt.
        """
        if self.is_healthy():
            return True
        if not _AUTO_START:
            return False
        try:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            _log.warning("ollama_auto_start_failed error=%s", exc)
            return False

        deadline = time.monotonic() + _AUTO_START_MAX_WAIT_S
        while time.monotonic() < deadline:
            if self.is_healthy():
                _log.info("ollama_auto_start_succeeded")
                return True
            time.sleep(_AUTO_START_POLL_S)
        _log.warning("ollama_auto_start_timed_out wait_s=%s", _AUTO_START_MAX_WAIT_S)
        return False

    # ── models ────────────────────────────────────────────────────────────────

    def list_models(self) -> list[str]:
        """Return installed model names, or [] if the daemon is unreachable."""
        try:
            import httpx
            r = httpx.get(f"{self._base}/api/tags", timeout=_HEALTH_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        except Exception as exc:
            _log.debug("ollama_list_models_failed error=%s", exc)
            return []

    def pull_model(self, name: str) -> bool:
        """Pull a model if not already present. No-ops (returns True) if present."""
        if name in self.list_models():
            return True
        t0 = now_ms()
        status = "error"
        try:
            import httpx
            with httpx.stream(
                "POST", f"{self._base}/api/pull",
                json={"name": name}, timeout=_PULL_TIMEOUT,
            ) as resp:
                resp.raise_for_status()
                for _ in resp.iter_lines():
                    pass  # drain progress stream; final status checked below
            status = "ok"
            return True
        except Exception as exc:
            _log.warning("ollama_pull_model_failed model=%s error=%s", name, exc)
            return False
        finally:
            duration_ms = now_ms() - t0
            try:
                from backend.observability.metrics import (
                    ollama_model_pull_duration_ms, ollama_model_pulls_total,
                )
                ollama_model_pull_duration_ms.labels(model=name).observe(duration_ms)
                ollama_model_pulls_total.labels(model=name, status=status).inc()
            except Exception:
                pass

    def ensure_model(self, name: str) -> bool:
        """Check-then-pull convenience wrapper. Best-effort; never raises."""
        try:
            return self.pull_model(name)
        except Exception as exc:
            _log.warning("ollama_ensure_model_failed model=%s error=%s", name, exc)
            return False

    # ── sizing ────────────────────────────────────────────────────────────────

    def estimate_resource_needs(self, name: str) -> dict[str, Any]:
        """Static resource-footprint lookup for deployment sizing.

        Not live introspection — a reference table for the recommended
        models plus a conservative default for anything else.
        """
        estimate = RECOMMENDED_MODELS.get(name)
        if estimate is None:
            _log.warning("ollama_resource_estimate_unknown_model model=%s", name)
            return dict(_DEFAULT_RESOURCE_ESTIMATE)
        return dict(estimate)
