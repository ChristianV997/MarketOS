from __future__ import annotations

import pytest

from backend.contracts.events import Event
from backend.events.adapters.supabase import SupabaseEventRepository, SupabaseEventRepositoryError


class FakeResponse:
    def __init__(self, data): self.data = data


class FakeQuery:
    def __init__(self, rows): self.rows = rows; self.filters = {}
    def upsert(self, row, on_conflict=None):
        self.rows[:] = [existing for existing in self.rows if existing["event_id"] != row["event_id"]]
        self.rows.append(dict(row)); return self
    def select(self, _columns): return self
    def eq(self, key, value): self.filters[key] = value; return self
    def limit(self, _value): return self
    def order(self, _key, desc=False): return self
    def execute(self):
        return FakeResponse([row for row in self.rows if all(row.get(key) == value for key, value in self.filters.items())])


class FakeClient:
    def __init__(self): self.rows = []
    def table(self, _name): return FakeQuery(self.rows)


def event() -> Event:
    return Event("mvp-event-1", "mvp", "public_signal", "signal-1", "public_signal_observed", 1, 1.0, source="test", payload={"title": "fixture"}, metadata={"dry_run": True})


def test_adapter_fails_closed_without_configuration_or_network() -> None:
    repository = SupabaseEventRepository(url="", key="")
    assert repository.configured is False
    with pytest.raises(SupabaseEventRepositoryError, match="unconfigured"):
        repository.append(event())


def test_adapter_is_explicit_and_supports_event_repository_shape_with_fake_client() -> None:
    repository = SupabaseEventRepository(client=FakeClient())
    result = repository.append(event())
    assert result.appended
    assert repository.get("mvp-event-1") == event()
    assert list(repository.stream())[0].replay_hash() == event().replay_hash()
    assert repository.append(event()).idempotent


def test_schema_is_workspace_scoped_and_security_first() -> None:
    schema = open("deploy/supabase/schema.sql", encoding="utf-8").read()
    for table in ("workspaces", "canonical_events", "public_signals", "artifacts", "run_envelopes", "source_readiness"):
        assert f"public.{table}" in schema
        assert f"alter table public.{table} enable row level security" in schema
    for index in ("event_type", "aggregate", "workspace_occurred", "correlation"):
        assert index in schema
    assert "service-role key" in schema.lower()
