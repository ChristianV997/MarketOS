"""Identity contract for BaseArtifact: uniqueness for new records, preservation for stored ones.

* A new record gets a random UUID4 minted once and persisted.
* A supplied or stored ``artifact_id`` is preserved and never recomputed.
* Registering an existing id again replaces the earlier version (stored-ID replay).
* A payload with no ``artifact_id`` is a new record; retrying a logical operation is
  idempotent only when the caller supplies a stable ``artifact_id``.

No test depends on wall-clock timing; equal timestamps are fixed explicitly.
"""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import backend.contracts.base as base_module
from backend.contracts.base import BaseArtifact
from backend.contracts.registry import ArtifactRegistry
from backend.experiments.envelope import CommercialRunEnvelope
from backend.experiments.registry import ExperimentRegistry

ROOT = Path(__file__).resolve().parents[2]
STAMP = 1_700_000_000.0


@pytest.fixture(autouse=True)
def _no_durable_log(monkeypatch):
    """Keep registry.register() from appending to the shared replay store."""
    monkeypatch.setattr("backend.events.log.append", lambda *args, **kwargs: None)


def _artifact(**overrides) -> BaseArtifact:
    return BaseArtifact(artifact_type="base", workspace="prod", created_at=STAMP, **overrides)


# --- uniqueness of newly created records ------------------------------------


def test_equal_timestamps_do_not_share_an_id():
    ids = {_artifact().artifact_id for _ in range(500)}
    assert len(ids) == 500


def test_concurrent_creation_with_equal_timestamps_is_unique():
    with ThreadPoolExecutor(max_workers=16) as pool:
        ids = list(pool.map(lambda _: _artifact().artifact_id, range(800)))
    assert len(set(ids)) == 800


def test_new_ids_are_random_uuid4_not_derived_from_content():
    artifact = _artifact()
    parsed = uuid.UUID(artifact.artifact_id)
    assert parsed.version == 4
    assert str(parsed) == artifact.artifact_id
    namespace = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
    assert artifact.artifact_id != str(uuid.uuid5(namespace, f"base:prod:{STAMP}"))


_MINT_IN_FRESH_PROCESS = """
import os, sys
os.getpid = lambda: 1  # a container's first process: the PID repeats on every restart
sys.path.insert(0, {root!r})
from backend.contracts.base import BaseArtifact
print(BaseArtifact(artifact_type="base", workspace="prod", created_at={stamp!r}).artifact_id)
"""


def test_restart_with_a_reused_pid_and_equal_timestamp_does_not_collide():
    """Two real interpreters, same fixed PID and timestamp, counters back at zero."""
    code = _MINT_IN_FRESH_PROCESS.format(root=str(ROOT), stamp=STAMP)
    first, second = (
        subprocess.run([sys.executable, "-I", "-B", "-c", code], capture_output=True, text=True, check=True, timeout=60).stdout.strip()
        for _ in range(2)
    )
    assert uuid.UUID(first).version == uuid.UUID(second).version == 4
    assert first != second


def test_module_keeps_no_process_local_identity_state():
    assert not hasattr(base_module, "_ID_SEQUENCE")
    assert not hasattr(base_module, "_creation_nonce")


# --- preservation of supplied and stored ids --------------------------------


def test_explicit_id_is_preserved_and_never_minted(monkeypatch):
    def forbidden() -> uuid.UUID:
        raise AssertionError("an explicit artifact_id must not trigger minting")

    monkeypatch.setattr(base_module.uuid, "uuid4", forbidden)
    artifact = _artifact(artifact_id="caller-supplied-id")
    assert artifact.artifact_id == "caller-supplied-id"
    assert BaseArtifact.from_dict(artifact.to_dict()).artifact_id == "caller-supplied-id"


def test_id_is_minted_exactly_once_per_new_record(monkeypatch):
    minted: list[uuid.UUID] = []

    def fixed_sequence() -> uuid.UUID:
        value = uuid.UUID(int=len(minted) + 1, version=4)
        minted.append(value)
        return value

    monkeypatch.setattr(base_module.uuid, "uuid4", fixed_sequence)
    artifact = _artifact()
    assert len(minted) == 1 and artifact.artifact_id == str(minted[0])
    assert artifact.artifact_id == artifact.artifact_id and artifact.to_dict()["artifact_id"] == str(minted[0])
    assert len(minted) == 1

    restored = BaseArtifact.from_dict(artifact.to_dict())
    assert restored.artifact_id == artifact.artifact_id
    assert len(minted) == 1, "restoring a stored record must not mint"


# --- serialization / hydration ------------------------------------------------


def test_json_round_trip_preserves_identity_and_replay_hash():
    artifact = _artifact(parent_ids=["p1"], metadata={"k": "v"})
    restored = BaseArtifact.from_dict(json.loads(json.dumps(artifact.to_dict())))
    assert restored.artifact_id == artifact.artifact_id
    assert restored.replay_hash == artifact.replay_hash
    assert restored.to_dict() == artifact.to_dict()


def test_envelope_round_trip_keeps_artifact_and_experiment_identity():
    envelope = CommercialRunEnvelope(service_name="x", workspace_id="ws-1", created_at=STAMP)
    assert envelope.experiment_id == envelope.artifact_id
    restored = CommercialRunEnvelope.from_dict(json.loads(json.dumps(envelope.to_dict())))
    assert (restored.artifact_id, restored.experiment_id, restored.replay_hash) == (
        envelope.artifact_id,
        envelope.experiment_id,
        envelope.replay_hash,
    )
    registry_copy = ArtifactRegistry().deserialize(envelope.to_dict())
    assert isinstance(registry_copy, CommercialRunEnvelope) and registry_copy.artifact_id == envelope.artifact_id


def test_envelope_keeps_a_distinct_explicit_experiment_id():
    envelope = CommercialRunEnvelope(service_name="x", workspace_id="ws-1", created_at=STAMP, experiment_id="exp-keep")
    assert envelope.experiment_id == "exp-keep" and envelope.artifact_id != "exp-keep"
    assert CommercialRunEnvelope.from_dict(envelope.to_dict()).experiment_id == "exp-keep"


# --- registry behaviour --------------------------------------------------------


def test_registry_retains_both_same_timestamp_artifacts_with_their_indexes():
    registry = ArtifactRegistry()
    first, second = _artifact(parent_ids=["p"]), _artifact(parent_ids=["p"])
    registry.register(first)
    registry.register(second)
    assert registry.count() == 2 and registry.count("base") == 2
    assert {item.artifact_id for item in registry.children_of("p")} == {first.artifact_id, second.artifact_id}
    assert registry.get(first.artifact_id) is first and registry.get(second.artifact_id) is second


def test_registering_a_stored_id_again_replaces_it_without_multiplying_indexes():
    """Stored-ID replay semantics are unchanged: same id means the later version wins."""
    registry = ArtifactRegistry()
    original = _artifact(parent_ids=["p"], metadata={"version": 1})
    registry.register(original)
    updated = BaseArtifact.from_dict({**original.to_dict(), "metadata": {"version": 2}, "replay_hash": ""})
    assert updated.artifact_id == original.artifact_id
    registry.register(updated)
    assert registry.count() == 1 and registry.count("base") == 1
    assert [item.artifact_id for item in registry.children_of("p")] == [original.artifact_id]
    assert registry.get(original.artifact_id).metadata == {"version": 2}


def test_hydrate_restores_distinct_ids_and_later_event_with_same_id_wins():
    registry = ArtifactRegistry()
    first, second = _artifact(metadata={"n": 1}), _artifact(metadata={"n": 2})
    revised = {**first.to_dict(), "metadata": {"n": 99}}
    events = [
        {"type": "artifact.base.registered", "payload": first.to_dict()},
        {"type": "artifact.base.registered", "payload": second.to_dict()},
        {"type": "artifact.base.registered", "payload": revised},
        {"type": "artifact.base.registered", "payload": {k: v for k, v in first.to_dict().items() if k != "artifact_id"}},
    ]
    assert registry.hydrate(events) == 3, "a payload with no artifact_id is skipped, not given an identity"
    assert registry.count() == 2
    assert registry.get(first.artifact_id).metadata == {"n": 99}
    assert registry.get(second.artifact_id).metadata == {"n": 2}


def test_same_timestamp_envelopes_keep_per_workspace_spend_separate():
    experiments = ExperimentRegistry(artifact_registry=ArtifactRegistry(), hydrate=False)
    for workspace, spend in (("ws-a", 30.0), ("ws-a", 20.0), ("ws-b", 1000.0)):
        experiments.register(CommercialRunEnvelope(service_name="x", workspace_id=workspace, actual_spend=spend, created_at=STAMP))
    assert experiments.spend_this_month("ws-a", now=STAMP) == 50.0
    assert experiments.spend_this_month("ws-b", now=STAMP) == 1000.0


# --- retries and idempotency ---------------------------------------------------


def test_retry_without_a_caller_key_records_a_new_attempt_each_time():
    """No idempotency is claimed: every construction is a distinct run record."""
    experiments = ExperimentRegistry(artifact_registry=ArtifactRegistry(), hydrate=False)
    attempts = [CommercialRunEnvelope(service_name="x", workspace_id="ws-1", created_at=STAMP) for _ in range(3)]
    for attempt in attempts:
        experiments.register(attempt)
    assert len({attempt.experiment_id for attempt in attempts}) == 3
    assert len(experiments.for_workspace("ws-1")) == 3


def test_retry_with_a_caller_supplied_id_replaces_the_same_record():
    experiments = ExperimentRegistry(artifact_registry=ArtifactRegistry(), hydrate=False)
    first = CommercialRunEnvelope(service_name="x", workspace_id="ws-1", artifact_id="op-123", experiment_id="op-123", actual_spend=5.0)
    retry = CommercialRunEnvelope(service_name="x", workspace_id="ws-1", artifact_id="op-123", experiment_id="op-123", actual_spend=5.0)
    experiments.register(first)
    experiments.register(retry)
    assert len(experiments.for_workspace("ws-1")) == 1
    assert experiments.get("op-123") is retry


def test_payload_without_an_id_is_a_new_record_each_time_it_is_built():
    payload = {k: v for k, v in _artifact().to_dict().items() if k not in {"artifact_id", "replay_hash"}}
    first, second = BaseArtifact.from_dict(dict(payload)), BaseArtifact.from_dict(dict(payload))
    assert first.artifact_id and second.artifact_id and first.artifact_id != second.artifact_id
