"""Explicit, fail-closed construction for Supabase canonical-event staging."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterator, Sequence

from backend.contracts.events import Event
from backend.events.repository import AppendResult
from backend.events.supabase_event_validation import validate_events_for_supabase, validate_event_for_supabase

from .supabase import SupabaseEventRepository, SupabaseEventRepositoryError


@dataclass(frozen=True)
class SupabaseStagingConfig:
    url: str; service_role_key: str; write_gate_enabled: bool


def supabase_staging_config_from_env(environ: dict[str, str] | None = None) -> SupabaseStagingConfig:
    values = os.environ if environ is None else environ
    return SupabaseStagingConfig(values.get("SUPABASE_URL", ""), values.get("SUPABASE_SERVICE_ROLE_KEY", ""), values.get("MARKETOS_SUPABASE_CANONICAL_EVENTS", "0") == "1")


def is_supabase_staging_configured(environ: dict[str, str] | None = None) -> bool:
    config = supabase_staging_config_from_env(environ)
    return bool(config.url and config.service_role_key and config.write_gate_enabled)


def explain_supabase_staging_readiness(environ: dict[str, str] | None = None) -> dict[str, Any]:
    config = supabase_staging_config_from_env(environ)
    missing = [key for key, value in (("SUPABASE_URL", config.url), ("SUPABASE_SERVICE_ROLE_KEY", config.service_role_key)) if not value]
    return {"configured": not missing and config.write_gate_enabled, "missing_env": missing, "write_gate_enabled": config.write_gate_enabled, "service_role_server_only": True, "network_calls": False, "next_action": "set server-only staging configuration and explicit gate" if missing or not config.write_gate_enabled else "explicit write may be requested by an operator"}


def assert_supabase_staging_allowed(action_context: dict[str, Any] | None = None, environ: dict[str, str] | None = None) -> None:
    readiness = explain_supabase_staging_readiness(environ)
    if not readiness["configured"]: raise SupabaseEventRepositoryError("Supabase staging is disabled or unconfigured; require SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, and MARKETOS_SUPABASE_CANONICAL_EVENTS=1")
    context = action_context or {}
    if context.get("dry_run") is not True or context.get("advisory") is not True:
        raise SupabaseEventRepositoryError("Supabase staging accepts dry-run advisory events only")


class ValidatingSupabaseStagingRepository:
    """Small validating wrapper; it does not change the optional base adapter."""
    def __init__(self, repository: SupabaseEventRepository): self.repository = repository
    def append(self, event: Event) -> AppendResult: validate_event_for_supabase(event); return self.repository.append(event)
    def append_many(self, events: Sequence[Event]) -> list[AppendResult]: validate_events_for_supabase(events); return self.repository.append_many(events)
    def get(self, event_id: str) -> Event | None: return self.repository.get(event_id)
    def stream(self, *args: Any, **kwargs: Any) -> Iterator[Event]: yield from self.repository.stream(*args, **kwargs)
    def replay(self, *args: Any, **kwargs: Any) -> list[Event]: return self.repository.replay(*args, **kwargs)
    def tail(self, *args: Any, **kwargs: Any) -> list[Event]: return self.repository.tail(*args, **kwargs)


def build_supabase_staging_repository(*, client: Any | None = None, environ: dict[str, str] | None = None) -> ValidatingSupabaseStagingRepository:
    assert_supabase_staging_allowed({"dry_run": True, "advisory": True}, environ)
    config = supabase_staging_config_from_env(environ)
    return ValidatingSupabaseStagingRepository(SupabaseEventRepository(url=config.url, key=config.service_role_key, client=client))


__all__ = ["SupabaseStagingConfig", "ValidatingSupabaseStagingRepository", "assert_supabase_staging_allowed", "build_supabase_staging_repository", "explain_supabase_staging_readiness", "is_supabase_staging_configured", "supabase_staging_config_from_env"]
