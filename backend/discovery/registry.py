"""backend.discovery.registry — central health/status registry for discovery sources.

Every discovery adapter self-reports at registration time (name,
credential env vars, whether it requires auth); `core.signals.SignalEngine.get()`
records fetch health (count, error) after each invocation. This gives one
place to answer "what data is real right now, and what needs credentials?"
without reverse-engineering `SignalEngine._sources`, which only stores
`{"name", "fetch"}` and no metadata.

Public surface:
    discovery_registry.register(name, credential_env_vars, requires_auth)
    discovery_registry.record_fetch(name, count, error=None)
    discovery_registry.status_report() -> list[dict]
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

_STATUS_ERROR = "error"
_STATUS_MOCK_ONLY = "mock_only"
_STATUS_MOCK_FALLBACK = "mock_fallback"
_STATUS_LIVE = "live"
_STATUS_NOT_REGISTERED = "not_registered"

# Sources known to have an honest mock-only or mock-fallback tier even when
# fetch succeeds (i.e. a nonzero count doesn't necessarily mean real data).
# alibaba moved from mock_only to mock_fallback once its optional
# Firecrawl-backed real path (gated by FIRECRAWL_API_KEY) was added — it's
# no longer *permanently* mock, just conservatively treated the same as
# every other scraper here whose real-data success isn't guaranteed
# run-to-run.
_MOCK_ONLY_SOURCES = set()
_MOCK_FALLBACK_SOURCES = {"amazon_bestsellers", "tiktok_organic", "alibaba"}


@dataclass
class SourceHealth:
    name: str
    credential_env_vars: list[str] = field(default_factory=list)
    requires_auth: bool = False
    last_fetch_ts: float | None = None
    last_fetch_count: int | None = None
    last_error: str | None = None

    @property
    def status(self) -> str:
        if self.last_fetch_ts is None:
            return _STATUS_NOT_REGISTERED
        if self.last_error:
            return _STATUS_ERROR
        if self.name in _MOCK_ONLY_SOURCES:
            return _STATUS_MOCK_ONLY
        if self.name in _MOCK_FALLBACK_SOURCES and not self.requires_auth:
            return _STATUS_MOCK_FALLBACK
        if (self.last_fetch_count or 0) > 0:
            return _STATUS_LIVE
        return _STATUS_MOCK_FALLBACK

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "credential_env_vars": list(self.credential_env_vars),
            "requires_auth": self.requires_auth,
            "status": self.status,
            "last_fetch_ts": self.last_fetch_ts,
            "last_fetch_count": self.last_fetch_count,
            "last_error": self.last_error,
        }


class DiscoveryRegistry:
    """Tracks every discovery adapter's credential requirements and fetch health."""

    def __init__(self) -> None:
        self._sources: dict[str, SourceHealth] = {}

    def register(
        self,
        name: str,
        credential_env_vars: list[str] | None = None,
        requires_auth: bool = False,
    ) -> None:
        """Register a discovery source (idempotent — re-registering keeps fetch history)."""
        existing = self._sources.get(name)
        if existing is not None:
            existing.credential_env_vars = list(credential_env_vars or [])
            existing.requires_auth = requires_auth
            return
        self._sources[name] = SourceHealth(
            name=name,
            credential_env_vars=list(credential_env_vars or []),
            requires_auth=requires_auth,
        )

    def record_fetch(self, name: str, count: int, error: str | None = None) -> None:
        """Record the result of one SignalEngine.get() invocation for a source."""
        source = self._sources.setdefault(name, SourceHealth(name=name))
        source.last_fetch_ts = time.time()
        source.last_fetch_count = count
        source.last_error = error

    def status_report(self) -> list[dict[str, Any]]:
        """Return all registered sources' health, sorted by name."""
        return [s.to_dict() for _, s in sorted(self._sources.items())]

    def reset(self) -> None:
        """Test helper — clear all registered sources."""
        self._sources.clear()


# Module-level singleton, matching core.signals.signal_engine's pattern.
discovery_registry = DiscoveryRegistry()
