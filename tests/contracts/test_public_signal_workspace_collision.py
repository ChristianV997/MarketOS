"""Regression tests: one public article ingested for two workspaces.

Signal identity is workspace-agnostic (``signal_identifier`` hashes source, query,
URL and title), so ``public_signal_event`` yields the same ``event_id`` for both
synthetic workspaces. These tests fail on current main. Each assertion is an
invariant that every candidate identity option in
docs/ai/PUBLIC_SIGNAL_EVENT_IDENTITY.md must satisfy, so none of them pre-selects
an option. Persisted identity is not changed by this file.
"""
from __future__ import annotations

from pathlib import Path

from backend.events.adapters.supabase import SupabaseEventRepository, SupabaseEventRepositoryError
from backend.events.replay_certification import load_canonical_jsonl
from backend.events.repository import JsonlEventRepository
from backend.signals.public_sources import append_public_signal_events, ingest_public_rss, public_signal_event

ROOT = Path("tests/fixtures/public_signals")
WORKSPACE_ALPHA = "synthetic-workspace-alpha"
WORKSPACE_BETA = "synthetic-workspace-beta"


class _FakeQuery:
    """Models the current canonical_events primary key: upsert replaces the row with the same event_id."""

    def __init__(self, rows):
        self.rows = rows

    def upsert(self, row, on_conflict=None):
        self.rows[:] = [existing for existing in self.rows if existing["event_id"] != row["event_id"]]
        self.rows.append(dict(row))
        return self

    def execute(self):
        return None


class _FakeClient:
    def __init__(self):
        self.rows = []

    def table(self, _name):
        return _FakeQuery(self.rows)


def _signals():
    return ingest_public_rss("ecommerce trends", fixture_xml=(ROOT / "rss_sample.xml").read_text(encoding="utf-8")).signals


def _outcome(write):
    """Return the write result, or the refusal if the adapter refuses loudly."""
    try:
        return write()
    except SupabaseEventRepositoryError as exc:
        return exc


def test_supabase_second_workspace_does_not_reassign_first_workspace_row():
    """Separate adapter instances, as build_supabase_staging_repository() creates per call."""
    client = _FakeClient()
    signal = _signals()[0]
    SupabaseEventRepository(client=client).append(public_signal_event(signal, WORKSPACE_ALPHA, cache_status="fixture"))
    _outcome(lambda: SupabaseEventRepository(client=client).append(public_signal_event(signal, WORKSPACE_BETA, cache_status="fixture")))
    assert WORKSPACE_ALPHA in {row["workspace_id"] for row in client.rows}


def test_supabase_same_adapter_never_reports_other_workspace_write_as_idempotent():
    """One adapter instance: the in-memory _known_ids shortcut must not treat another workspace's write as a replay."""
    repository = SupabaseEventRepository(client=_FakeClient())
    signal = _signals()[0]
    repository.append(public_signal_event(signal, WORKSPACE_ALPHA, cache_status="fixture"))
    outcome = _outcome(lambda: repository.append(public_signal_event(signal, WORKSPACE_BETA, cache_status="fixture")))
    assert isinstance(outcome, SupabaseEventRepositoryError) or not outcome.idempotent


def test_jsonl_second_workspace_write_is_not_reported_as_idempotent_duplicate(tmp_path):
    path = tmp_path / "shared-signals.jsonl"
    signal = _signals()[0]
    JsonlEventRepository(path).append(public_signal_event(signal, WORKSPACE_ALPHA, cache_status="fixture"))
    outcome = JsonlEventRepository(path).append(public_signal_event(signal, WORKSPACE_BETA, cache_status="fixture"))
    assert not outcome.idempotent


def test_reported_event_ids_equal_rows_persisted_for_each_workspace(tmp_path):
    """append_public_signal_events must report only IDs that were persisted for that workspace."""
    path = tmp_path / "shared-signals.jsonl"
    signals = _signals()
    reported = {}
    for workspace in (WORKSPACE_ALPHA, WORKSPACE_BETA):
        reported[workspace] = set(append_public_signal_events(signals, JsonlEventRepository(path), workspace_id=workspace, cache_status="fixture"))
    stored = load_canonical_jsonl(path)
    for workspace, event_ids in reported.items():
        assert event_ids == {event.event_id for event in stored if event.workspace_id == workspace}
