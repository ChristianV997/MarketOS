"""backend.ollama_manager — lifecycle management for the local Ollama daemon.

Ollama lifecycle operations require an explicit opt-in configuration.
This module separates deterministic readiness metadata from an explicit local-loopback probe.
The normal readiness path is completely offline. An explicit probe path is available
for operator use but never runs by default.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import Any

_log = logging.getLogger(__name__)

_BASE = os.getenv("OLLAMA_URL", "http://localhost:11434")
_HEALTH_TIMEOUT = float(os.getenv("OLLAMA_HEALTH_TIMEOUT_S", "0.25"))
_PULL_TIMEOUT = float(os.getenv("OLLAMA_PULL_TIMEOUT_S", "600"))

# Explicit safety boundaries
_OLLAMA_ENABLED = os.getenv("OLLAMA_ENABLED", "false").lower() == "true"
_AUTO_START = os.getenv("OLLAMA_AUTO_START", "false").lower() == "true"

RECOMMENDED_MODELS: dict[str, dict[str, Any]] = {
    "mistral:7b": {
        "vram_gb": 2.0, "ram_gb": 4.0, "cpu_latency_ms_estimate": 25,
        "role": "primary — best reasoning/creative balance",
    },
    "llama3.2:3b": {
        "vram_gb": 1.0, "ram_gb": 2.0, "cpu_latency_ms_estimate": 10,
        "role": "low-resource fallback — fast, basic quality",
    },
}
_DEFAULT_RESOURCE_ESTIMATE: dict[str, Any] = {
    "vram_gb": 4.0, "ram_gb": 8.0, "cpu_latency_ms_estimate": 50,
    "role": "unknown model",
}

class OllamaManager:
    """Manages the local Ollama daemon."""

    def __init__(self, base_url: str = _BASE) -> None:
        self._base = base_url
        self._enabled = _OLLAMA_ENABLED

    def is_enabled(self) -> bool:
        """Deterministic offline metadata check."""
        return self._enabled

    def probe_health(self) -> str:
        """Explicit local-loopback probe. Returns 'ready', 'unavailable', or 'blocked'."""
        if not self._enabled:
            return "blocked"
        try:
            import httpx
            r = httpx.get(f"{self._base}/api/tags", timeout=_HEALTH_TIMEOUT)
            if r.status_code == 200:
                return "ready"
            return "unavailable"
        except Exception:
            return "unavailable"

    def ensure_running(self) -> bool:
        """Bound lifecycle operation: auto-start disabled by default."""
        if not self._enabled:
            return False
        if self.probe_health() == "ready":
            return True
        if not _AUTO_START:
            return False

        try:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            _log.warning("ollama_auto_start_failed")
            return False

        # Bounded poll
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if self.probe_health() == "ready":
                return True
            time.sleep(0.5)
        return False

    def list_models(self) -> list[str]:
        if not self._enabled:
            return []
        try:
            import httpx
            r = httpx.get(f"{self._base}/api/tags", timeout=_HEALTH_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        except Exception:
            return []

    def pull_model(self, name: str) -> bool:
        """Pull a model explicitly. No auto-retry loop, bounded timeout, no credential/prompt logging."""
        if not self._enabled:
            return False

        if name in self.list_models():
            return True

        try:
            import httpx
            with httpx.stream(
                "POST", f"{self._base}/api/pull",
                json={"name": name}, timeout=_PULL_TIMEOUT,
            ) as resp:
                resp.raise_for_status()
                for _ in resp.iter_lines():
                    pass
            return True
        except Exception:
            # Explicitly not logging raw prompt/model-output/credentials
            _log.warning("ollama_pull_model_failed")
            return False

    def ensure_model(self, name: str) -> bool:
        """Check-then-pull explicitly invoked."""
        try:
            return self.pull_model(name)
        except Exception:
            return False

    def estimate_resource_needs(self, name: str) -> dict[str, Any]:
        return dict(RECOMMENDED_MODELS.get(name) or _DEFAULT_RESOURCE_ESTIMATE)
