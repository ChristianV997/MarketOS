"""Optional Supabase adapter for canonical events.

It is deliberately not the default repository.  A caller must construct it
explicitly with a fake client (tests) or credentials (operator-owned runtime).
The adapter never falls back to a network client and never changes legacy
Supabase state tables.
"""
from __future__ import annotations

import os
from typing import Any, Iterator, Sequence

from backend.contracts.events import Event
from backend.events.repository import AppendResult


class SupabaseEventRepositoryError(RuntimeError):
    """Configuration or transport error for the optional canonical adapter."""


def _response_rows(response: Any) -> list[dict[str, Any]]:
    rows = getattr(response, "data", response)
    return list(rows or []) if isinstance(rows, (list, tuple)) else []


class SupabaseEventRepository:
    """Canonical `EventRepository` adapter backed by `canonical_events`.

    The service-role key must remain server-only.  The default schema enables
    RLS and exposes no public policy; direct browser access is intentionally
    outside this foundation.
    """

    def __init__(
        self,
        *,
        url: str | None = None,
        key: str | None = None,
        client: Any | None = None,
        table: str = "canonical_events",
    ) -> None:
        self.url = url if url is not None else os.getenv("SUPABASE_URL", "")
        self.key = key if key is not None else os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        self._client = client
        self.table = table
        self._known_ids: set[str] = set()

    @property
    def configured(self) -> bool:
        return self._client is not None or bool(self.url and self.key)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.url or not self.key:
            raise SupabaseEventRepositoryError("Supabase canonical event adapter is unconfigured; set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
        try:
            from supabase import create_client  # Lazy import: no SDK/client on ordinary imports.
        except ImportError as exc:  # pragma: no cover - dependency is declared but optional installs exist.
            raise SupabaseEventRepositoryError("Supabase client package is unavailable") from exc
        self._client = create_client(self.url, self.key)
        return self._client

    @staticmethod
    def _row(event: Event) -> dict[str, Any]:
        return event.to_dict()

    @staticmethod
    def _event(row: dict[str, Any]) -> Event:
        return Event.from_dict({key: row.get(key) for key in Event.__dataclass_fields__})

    def append(self, event: Event) -> AppendResult:
        if event.event_id in self._known_ids:
            return AppendResult(event.event_id, appended=False, idempotent=True)
        try:
            table = self._get_client().table(self.table)
            table.upsert(self._row(event), on_conflict="event_id").execute()
        except SupabaseEventRepositoryError:
            raise
        except Exception as exc:
            raise SupabaseEventRepositoryError(f"Supabase canonical append failed: {type(exc).__name__}") from exc
        self._known_ids.add(event.event_id)
        return AppendResult(event.event_id, appended=True, idempotent=False)

    def append_many(self, events: Sequence[Event]) -> list[AppendResult]:
        return [self.append(event) for event in events]

    def get(self, event_id: str) -> Event | None:
        try:
            response = self._get_client().table(self.table).select("*").eq("event_id", event_id).limit(1).execute()
            rows = _response_rows(response)
            return self._event(rows[0]) if rows else None
        except SupabaseEventRepositoryError:
            raise
        except Exception as exc:
            raise SupabaseEventRepositoryError(f"Supabase canonical get failed: {type(exc).__name__}") from exc

    def stream(self, event_type: str | None = None, aggregate_id: str | None = None, limit: int | None = None) -> Iterator[Event]:
        try:
            query = self._get_client().table(self.table).select("*").order("occurred_at", desc=False).order("event_id", desc=False)
            if event_type is not None:
                query = query.eq("event_type", event_type)
            if aggregate_id is not None:
                query = query.eq("aggregate_id", aggregate_id)
            if limit is not None:
                query = query.limit(max(0, int(limit)))
            rows = _response_rows(query.execute())
            yield from (self._event(row) for row in rows)
        except SupabaseEventRepositoryError:
            raise
        except Exception as exc:
            raise SupabaseEventRepositoryError(f"Supabase canonical stream failed: {type(exc).__name__}") from exc

    def replay(self, since: float | None = None, until: float | None = None, **filters: Any) -> list[Event]:
        events = list(self.stream(event_type=filters.get("event_type"), aggregate_id=filters.get("aggregate_id")))
        return [event for event in events if (since is None or event.occurred_at >= since) and (until is None or event.occurred_at <= until)]

    def tail(self, n: int = 100, event_type: str | None = None) -> list[Event]:
        events = list(self.stream(event_type=event_type))
        return events[-max(0, int(n)):]


__all__ = ["SupabaseEventRepository", "SupabaseEventRepositoryError"]
