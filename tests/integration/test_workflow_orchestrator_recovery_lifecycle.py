"""Integration regression: workflow interrupt / resume / replay lifecycle.

Runs the real orchestrator against the real ``WorkflowRegistry`` (workflows,
checkpoints and timeline) and the real ``execute_workflow_stage`` stage
implementations. The registry is a fresh instance rooted in ``tmp_path``; no
repository state, network or live action is touched. The only test seam is a
counting spy around the executor boundary that delegates to the real function,
can raise a scheduled failure, and adds one deterministic produced ref so
de-duplication is observable.
"""
from __future__ import annotations

import copy
from collections import Counter
from types import SimpleNamespace

import pytest

from backend.workflows import orchestrator, runbook
from backend.workflows import workflow_registry as workflow_registry_module
from backend.workflows.workflow_registry import WorkflowRegistry

STAGE_TRANSITIONS = {"stage_started", "stage_completed", "stage_skipped", "stage_failed", "stage_blocked"}
FIXTURE_REF = {"object_type": "evidence_import", "object_id": "fixture_ref_1", "registry": "marketos", "relation": "produced"}

# Completes with real stages: skipped (no imports), completed, completed.
COMPLETING = "recovery_lifecycle_cycle"
# The middle stage is unknown to the real executor, which blocks it.
BLOCKING = "recovery_lifecycle_blocked_cycle"


class _StageSpy:
    def __init__(self, real):
        self.real = real
        self.calls: Counter[str] = Counter()
        self.fail_queue: dict[str, list[str]] = {}

    def __call__(self, run, stage, context):
        self.calls[stage.stage_name] += 1
        queue = self.fail_queue.get(stage.stage_name)
        if queue:
            raise Exception(queue.pop(0))
        result = self.real(run, stage, context)
        if stage.stage_name == "acquisition_planning" and result.get("status") == "completed":
            result = {**result, "produced_object_ids": list(result["produced_object_ids"]) + [copy.deepcopy(FIXTURE_REF)]}
        return result


@pytest.fixture
def lifecycle(tmp_path, monkeypatch):
    monkeypatch.setitem(runbook._STAGES, COMPLETING, ["import_evidence", "acquisition_planning", "final_summary"])
    monkeypatch.setitem(runbook._STAGES, BLOCKING, ["acquisition_planning", "unsupported_probe_stage", "final_summary"])
    registry = WorkflowRegistry(tmp_path / "workflow_registry.json")
    monkeypatch.setattr(workflow_registry_module, "_singleton", registry)
    spy = _StageSpy(orchestrator.execute_workflow_stage)
    monkeypatch.setattr(orchestrator, "execute_workflow_stage", spy)
    return SimpleNamespace(registry=registry, spy=spy)


def _events(env, wid, stage=None, types=None):
    return [
        e.event_type
        for e in env.registry.list_timeline(wid)
        if (stage is None or e.stage_name == stage) and (types is None or e.event_type in types)
    ]


def _stage(result, name):
    return next(s for s in result["stages"] if s["stage_name"] == name)


def _statuses(result):
    return [(s["stage_name"], s["status"]) for s in result["stages"]]


def _assert_coherent(env, wid):
    """Every stage's transitions are well-formed started->terminal pairs and the
    run's embedded checkpoints match the registry's."""
    run = env.registry.get_workflow(wid)
    for stage in run.stages:
        seq = _events(env, wid, stage.stage_name, STAGE_TRANSITIONS)
        assert len(seq) % 2 == 0, (stage.stage_name, seq)
        for started, terminal in zip(seq[0::2], seq[1::2]):
            assert started == "stage_started" and terminal != "stage_started", (stage.stage_name, seq)
    assert {c.checkpoint_id for c in run.checkpoints} == {c.checkpoint_id for c in env.registry.list_checkpoints(wid, limit=1000)}
    ids = [(r["object_type"], r["object_id"], r["relation"]) for r in run.produced_object_ids]
    assert len(ids) == len(set(ids))


def _interrupt_after_acquisition(env, workflow_type=COMPLETING):
    result = orchestrator.run_workflow(
        workspace_id="lifecycle", workflow_type=workflow_type, payload={}, stop_after_stage="acquisition_planning"
    )
    return result["workflow_id"], result


def test_interrupted_workflow_resumes_only_pending_work(lifecycle):
    env = lifecycle
    wid, interrupted = _interrupt_after_acquisition(env)

    assert interrupted["status"] == "partial"
    assert _statuses(interrupted) == [
        ("import_evidence", "skipped"),
        ("acquisition_planning", "completed"),
        ("final_summary", "pending"),
    ]
    assert env.spy.calls == Counter(import_evidence=1, acquisition_planning=1)

    resumed = orchestrator.resume_workflow(wid)

    assert resumed["workflow_id"] == wid
    assert resumed["status"] == "completed"
    assert _statuses(resumed) == [
        ("import_evidence", "skipped"),
        ("acquisition_planning", "completed"),
        ("final_summary", "completed"),
    ]
    assert env.spy.calls == Counter(import_evidence=1, acquisition_planning=1, final_summary=1)
    assert all(s["retry_count"] == 0 for s in resumed["stages"])
    assert resumed["errors"] == []
    assert [r["object_id"] for r in resumed["produced_object_ids"]] == ["fixture_ref_1"]

    assert _events(env, wid, "import_evidence", STAGE_TRANSITIONS) == ["stage_started", "stage_skipped"]
    assert _events(env, wid, "acquisition_planning", STAGE_TRANSITIONS) == ["stage_started", "stage_completed"]
    assert _events(env, wid, "final_summary", STAGE_TRANSITIONS) == ["stage_started", "stage_completed"]
    assert _events(env, wid, "", {"workflow_partial"}) == ["workflow_partial"]
    assert _events(env, wid, "", {"workflow_completed"}) == ["workflow_completed"]
    for stage_name in ("import_evidence", "acquisition_planning", "final_summary"):
        assert len(env.registry.list_checkpoints(wid, stage_name)) == 2  # before_stage + after_stage, none added by resume
    _assert_coherent(env, wid)


def test_resume_by_registry_checkpoint_id_skips_completed_stage(lifecycle):
    env = lifecycle
    wid, _ = _interrupt_after_acquisition(env)
    checkpoint = env.registry.latest_checkpoint(wid, "acquisition_planning")
    assert (checkpoint.checkpoint_type, checkpoint.recoverable, checkpoint.replayable) == ("after_stage", True, True)

    assert orchestrator.resume_workflow(wid, checkpoint_id="checkpoint_missing")["status"] == "not_found"
    resumed = orchestrator.resume_workflow(wid, checkpoint_id=checkpoint.checkpoint_id)

    assert resumed["status"] == "completed"
    assert env.spy.calls["acquisition_planning"] == 1
    assert env.spy.calls["final_summary"] == 1
    _assert_coherent(env, wid)


def test_finished_workflow_resume_and_replay_repeat_no_work_and_append_only_audit(lifecycle):
    env = lifecycle
    wid, _ = _interrupt_after_acquisition(env)
    finished = orchestrator.resume_workflow(wid)
    assert finished["status"] == "completed"
    calls_after_finish = Counter(env.spy.calls)
    transitions_after_finish = _events(env, wid, None, STAGE_TRANSITIONS)

    again = orchestrator.resume_workflow(wid)
    assert again["status"] == "completed"
    for _ in range(2):
        replayed = orchestrator.replay_workflow_stage(wid, "acquisition_planning", "audit")
        assert replayed["status"] == "completed"
        assert _stage(replayed, "acquisition_planning")["status"] == "completed"

    assert env.spy.calls == calls_after_finish
    assert _events(env, wid, None, STAGE_TRANSITIONS) == transitions_after_finish
    assert _events(env, wid, "", {"workflow_completed"}) == ["workflow_completed"]
    assert _events(env, wid, "", {"workflow_partial"}) == ["workflow_partial"]
    assert _events(env, wid, None, {"recovery_started"}) == ["recovery_started", "recovery_started"]
    assert _events(env, wid, None, {"recovery_completed"}) == ["recovery_completed", "recovery_completed"]
    assert _events(env, wid, "acquisition_planning", {"replay_started"}) == ["replay_started"] * 2
    assert _events(env, wid, "acquisition_planning", {"replay_completed"}) == ["replay_completed"] * 2
    assert [r["object_id"] for r in replayed["produced_object_ids"]] == ["fixture_ref_1"]
    assert [r["object_id"] for r in _stage(replayed, "acquisition_planning")["produced_object_ids"]] == ["fixture_ref_1"]

    timeline_before = len(env.registry.list_timeline(wid))
    blocked = orchestrator.replay_workflow_stage(wid, "final_summary")
    assert blocked["status"] == "blocked"
    assert blocked["blocked_reasons"] == ["stage_replay_requires_full_safe_rerun"]
    assert len(env.registry.list_timeline(wid)) == timeline_before
    _assert_coherent(env, wid)


def test_recoverable_failure_is_retried_with_its_own_audit_and_only_that_stage(lifecycle):
    env = lifecycle
    env.spy.fail_queue["acquisition_planning"] = ["temporary unavailable service error"]
    failed = orchestrator.run_workflow(workspace_id="lifecycle", workflow_type=COMPLETING, payload={})
    wid = failed["workflow_id"]

    assert failed["status"] == "partial"
    assert _stage(failed, "acquisition_planning")["status"] == "failed"
    checkpoint = env.registry.latest_checkpoint(wid, "acquisition_planning")
    assert (checkpoint.checkpoint_type, checkpoint.recoverable, checkpoint.replayable) == ("failure", True, True)

    recovered = orchestrator.resume_workflow(wid, checkpoint_id=checkpoint.checkpoint_id)

    assert recovered["status"] == "completed"
    assert recovered["errors"] == []
    assert env.spy.calls == Counter(import_evidence=1, acquisition_planning=2, final_summary=1)
    assert _events(env, wid, "acquisition_planning", STAGE_TRANSITIONS) == [
        "stage_started", "stage_failed", "stage_started", "stage_completed",
    ]
    assert _events(env, wid, "", {"workflow_partial", "workflow_completed"}) == ["workflow_partial", "workflow_completed"]
    _assert_coherent(env, wid)


def test_repeated_failures_record_each_attempt_and_report_only_current_error(lifecycle):
    env = lifecycle
    env.spy.fail_queue["acquisition_planning"] = ["temporary unavailable service error 1", "temporary unavailable service error 2"]
    first = orchestrator.run_workflow(workspace_id="lifecycle", workflow_type=COMPLETING, payload={})
    wid = first["workflow_id"]
    assert first["errors"] == ["temporary unavailable service error 1"]

    checkpoint = env.registry.latest_checkpoint(wid, "acquisition_planning")
    second = orchestrator.resume_workflow(wid, checkpoint_id=checkpoint.checkpoint_id)

    assert second["status"] == "partial"
    assert second["errors"] == ["temporary unavailable service error 2"]
    failure_messages = [
        e.message for e in env.registry.list_timeline(wid) if e.stage_name == "acquisition_planning" and e.event_type == "stage_failed"
    ]
    assert failure_messages == ["temporary unavailable service error 1", "temporary unavailable service error 2"]
    assert _events(env, wid, "acquisition_planning", {"stage_started"}) == ["stage_started"] * 2

    checkpoint = env.registry.latest_checkpoint(wid, "acquisition_planning")
    third = orchestrator.resume_workflow(wid, checkpoint_id=checkpoint.checkpoint_id)
    assert third["status"] == "completed"
    assert third["errors"] == []
    assert env.spy.calls["acquisition_planning"] == 3
    assert env.spy.calls["final_summary"] == 1
    _assert_coherent(env, wid)


def test_recovered_stage_does_not_inherit_stale_failure_classification(lifecycle):
    env = lifecycle
    env.spy.fail_queue["acquisition_planning"] = ["kaboom"]  # unclassified -> non-recoverable failure checkpoint
    failed = orchestrator.run_workflow(workspace_id="lifecycle", workflow_type=COMPLETING, payload={})
    wid = failed["workflow_id"]
    failure_cp = env.registry.latest_checkpoint(wid, "acquisition_planning")
    assert (failure_cp.checkpoint_type, failure_cp.recoverable) == ("failure", False)
    assert orchestrator.resume_workflow(wid, checkpoint_id=failure_cp.checkpoint_id)["status"] == "blocked"

    recovered = orchestrator.resume_workflow(wid, from_stage="acquisition_planning")

    assert recovered["status"] == "completed"
    stage = _stage(recovered, "acquisition_planning")
    assert stage["status"] == "completed"
    assert "failure_classification" not in stage["metadata"]
    after = env.registry.latest_checkpoint(wid, "acquisition_planning")
    assert (after.checkpoint_type, after.stage_status, after.recoverable, after.replayable) == ("after_stage", "completed", True, True)

    calls = Counter(env.spy.calls)
    from_completed = orchestrator.resume_workflow(wid, checkpoint_id=after.checkpoint_id)
    assert from_completed["status"] == "completed"
    assert env.spy.calls == calls
    _assert_coherent(env, wid)


def test_safety_failure_stays_unrecoverable_and_unreplayable_without_executing(lifecycle):
    env = lifecycle
    env.spy.fail_queue["acquisition_planning"] = ["unsafe path escape detected"]
    failed = orchestrator.run_workflow(workspace_id="lifecycle", workflow_type=COMPLETING, payload={})
    wid = failed["workflow_id"]
    checkpoint = env.registry.latest_checkpoint(wid, "acquisition_planning")
    assert (checkpoint.recoverable, checkpoint.replayable) == (False, False)
    calls = Counter(env.spy.calls)
    timeline_before = len(env.registry.list_timeline(wid))

    resume = orchestrator.resume_workflow(wid, checkpoint_id=checkpoint.checkpoint_id)
    replay = orchestrator.replay_workflow_stage(wid, "acquisition_planning")

    assert resume["status"] == "blocked" and resume["blocked_reasons"] == ["checkpoint_not_recoverable"]
    assert replay["status"] == "blocked" and replay["blocked_reasons"] == ["stage_checkpoint_not_replayable"]
    assert env.spy.calls == calls
    assert len(env.registry.list_timeline(wid)) == timeline_before
    _assert_coherent(env, wid)


def test_blocked_stage_retry_is_not_suppressed_and_completed_stages_are_not_rerun(lifecycle):
    env = lifecycle
    first = orchestrator.run_workflow(workspace_id="lifecycle", workflow_type=BLOCKING, payload={})
    wid = first["workflow_id"]

    assert first["status"] == "partial"
    assert _statuses(first) == [
        ("acquisition_planning", "completed"),
        ("unsupported_probe_stage", "blocked"),
        ("final_summary", "completed"),
    ]
    assert first["errors"] == ["unsupported_stage"]
    probe_cp = env.registry.latest_checkpoint(wid, "unsupported_probe_stage")
    assert (probe_cp.checkpoint_type, probe_cp.recoverable, probe_cp.replayable) == ("failure", False, False)
    assert orchestrator.resume_workflow(wid, checkpoint_id=probe_cp.checkpoint_id)["status"] == "blocked"
    assert orchestrator.replay_workflow_stage(wid, "unsupported_probe_stage")["status"] == "blocked"
    assert env.spy.calls["unsupported_probe_stage"] == 1

    retried = orchestrator.resume_workflow(wid, from_stage="unsupported_probe_stage")

    assert retried["status"] == "partial"
    assert retried["errors"] == ["unsupported_stage"]
    assert env.spy.calls == Counter(acquisition_planning=1, unsupported_probe_stage=2, final_summary=1)
    assert _events(env, wid, "unsupported_probe_stage", STAGE_TRANSITIONS) == [
        "stage_started", "stage_blocked", "stage_started", "stage_blocked",
    ]
    assert _events(env, wid, "acquisition_planning", STAGE_TRANSITIONS) == ["stage_started", "stage_completed"]
    assert _events(env, wid, "", {"workflow_partial"}) == ["workflow_partial"]
    assert [r["object_id"] for r in retried["produced_object_ids"]] == ["fixture_ref_1"]
    _assert_coherent(env, wid)


def test_pending_stages_after_interruption_still_execute_when_earlier_stage_is_blocked(lifecycle):
    env = lifecycle
    wid, interrupted = _interrupt_after_acquisition(env, BLOCKING)
    assert _statuses(interrupted) == [
        ("acquisition_planning", "completed"),
        ("unsupported_probe_stage", "pending"),
        ("final_summary", "pending"),
    ]

    resumed = orchestrator.resume_workflow(wid)

    assert _statuses(resumed) == [
        ("acquisition_planning", "completed"),
        ("unsupported_probe_stage", "blocked"),
        ("final_summary", "completed"),
    ]
    assert env.spy.calls == Counter(acquisition_planning=1, unsupported_probe_stage=1, final_summary=1)
    _assert_coherent(env, wid)


def test_replay_does_not_rewrite_earlier_audit_records(lifecycle):
    env = lifecycle
    wid, _ = _interrupt_after_acquisition(env)
    orchestrator.resume_workflow(wid)

    def historical_relations():
        completed = [
            ref["relation"]
            for e in env.registry.list_timeline(wid)
            if e.stage_name == "acquisition_planning" and e.event_type == "stage_completed"
            for ref in e.object_refs
        ]
        after_stage = [
            ref["relation"]
            for c in env.registry.list_checkpoints(wid, "acquisition_planning")
            if c.checkpoint_type == "after_stage"
            for ref in c.produced_object_ids
        ]
        return completed, after_stage

    assert historical_relations() == (["produced"], ["produced"])
    orchestrator.replay_workflow_stage(wid, "acquisition_planning")
    assert historical_relations() == (["produced"], ["produced"])
    _assert_coherent(env, wid)
