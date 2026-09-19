"""Integration tests for scripts/run_operator_dogfood_workflow.py.

This bridge composes existing authorities (session_start, check_dev_stack,
coderos_snapshot, run_local_quality_gate, run_commercial_replay_integration,
TrustOS's client_workspace_isolation) rather than re-implementing any of
them, so these tests run the real chain against this real repository
wherever practical, and only synthesize inputs at the two seams that
cannot be driven for real without either damaging this checkout
(state_collision_check needs a genuine ownership conflict) or paying for a
slow full-repository test run (readiness_preflight's optional
--execute quality-gate mode, deliberately not used by the bridge itself).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import run_operator_dogfood_workflow as bridge

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Full chain, real execution, real repository
# ---------------------------------------------------------------------------


def test_the_full_bridge_runs_end_to_end_against_the_real_repository():
    report = bridge.run(REPO)
    assert report["schema"] == bridge.SCHEMA
    assert report["audience"] == "operator_internal"
    assert report["overall_classification"] in bridge.CLASSIFICATIONS
    assert report["dry_run"] is True
    assert report["live_actions_taken"] is False
    assert report["network_calls"] is False
    assert report["mutated"] is False

    phases_by_name = {phase["phase"]: phase for phase in report["phases"]}
    assert list(phases_by_name) == list(bridge.PHASES[:4])  # sanitized_handoff is the return value itself, not a phase entry
    for phase in report["phases"]:
        assert phase["classification"] in bridge.CLASSIFICATIONS

    # commercial_dry_run really ran all 5 canonical scenarios end to end.
    dry_run_detail = phases_by_name["commercial_dry_run"]["detail"]
    assert dry_run_detail.get("row_count") == 5
    scenario_ids = {row["scenario"] for row in dry_run_detail["rows"]}
    assert len(scenario_ids) == 5

    # trustos_export really exported (or genuinely blocked) every row --
    # never silently skipped one.
    export_detail = phases_by_name["trustos_export"]["detail"]
    if phases_by_name["trustos_export"]["classification"] == "passed":
        assert export_detail["exported_count"] == 5
        for item in export_detail["exports"]:
            assert len(item["fingerprint"]) == 64  # sha256 hex digest, real, not fabricated
            assert item["redaction_status"] == "validated_no_sensitive_fields"


def test_skip_commercial_marks_the_downstream_phases_not_run_without_running_them():
    report = bridge.run(REPO, skip_commercial=True)
    phases_by_name = {phase["phase"]: phase for phase in report["phases"]}
    assert phases_by_name["commercial_dry_run"]["classification"] == "not_run"
    assert phases_by_name["trustos_export"]["classification"] == "not_run"
    assert report["overall_classification"] in {"not_run", "passed", "ci_unavailable"}


def test_skip_quality_gate_is_recorded_as_not_run_not_silently_passed():
    report = bridge.run(REPO, skip_quality_gate=True, skip_commercial=True)
    phases_by_name = {phase["phase"]: phase for phase in report["phases"]}
    assert phases_by_name["readiness_preflight"]["detail"]["quality_gate"]["classification"] == "not_run"


def test_next_action_and_rollback_are_always_present_and_non_empty():
    report = bridge.run(REPO, skip_commercial=True)
    assert report["next_action"]
    assert report["rollback"]
    assert "no live action" in report["rollback"].lower()


# ---------------------------------------------------------------------------
# state_collision_check
# ---------------------------------------------------------------------------


def test_state_collision_check_is_unavailable_against_a_directory_with_no_session_start(tmp_path: Path):
    # A bare directory has no scripts/ai/session_start.py to invoke --
    # this must fail closed to "unavailable", never silently "passed".
    phase = bridge.state_collision_check(tmp_path)
    assert phase["classification"] == "unavailable"


def test_state_collision_check_passes_against_the_real_clean_repository():
    phase = bridge.state_collision_check(REPO)
    assert phase["classification"] in {"passed", "blocked"}  # blocked only if this worktree is genuinely dirty in an owned path
    assert "branch" in phase["detail"] or "conflicts" in phase["detail"]


def test_run_short_circuits_before_the_commercial_phases_when_state_collision_check_blocks(monkeypatch):
    monkeypatch.setattr(bridge, "state_collision_check", lambda repo: bridge._phase("state_collision_check", "blocked", {"reason": "synthetic_test_conflict"}))
    report = bridge.run(REPO)
    phases_by_name = {phase["phase"]: phase for phase in report["phases"]}
    assert phases_by_name["state_collision_check"]["classification"] == "blocked"
    assert "readiness_preflight" not in phases_by_name
    assert "commercial_dry_run" not in phases_by_name
    assert "trustos_export" not in phases_by_name
    assert report["overall_classification"] == "blocked"


# ---------------------------------------------------------------------------
# _classify_quality_gate -- pinned to run_local_quality_gate.py's real
# (non---execute) --json shape, verified directly against real output
# before writing this test (a flat document with "classification",
# "ci", and "planning_summary", not the nested "gate"/"pr_readiness" shape
# an earlier draft of the bridge wrongly assumed).
# ---------------------------------------------------------------------------


def test_classify_quality_gate_maps_the_real_ci_unavailable_shape():
    document = {
        "classification": "ci_unavailable",
        "ci": {"classification": "ci_unavailable", "status": "unavailable", "reason": "external_ci_not_queried"},
        "planning_summary": {
            "mutation_flags": {"provider_mutation_like_detected": False},
            "secret_or_artifact_flags": {"artifacts_detected": False, "credential_file_detected": False, "secret_value_like_detected": False},
        },
    }
    classification, detail = bridge._classify_quality_gate(document)
    assert classification == "ci_unavailable"
    assert detail["ci_classification"] == "ci_unavailable"


def test_classify_quality_gate_blocks_on_a_real_mutation_flag():
    document = {
        "classification": "passed",
        "ci": {"classification": "success"},
        "planning_summary": {
            "mutation_flags": {"provider_mutation_like_detected": True},
            "secret_or_artifact_flags": {"artifacts_detected": False, "credential_file_detected": False, "secret_value_like_detected": False},
        },
    }
    classification, detail = bridge._classify_quality_gate(document)
    assert classification == "blocked"
    assert detail["mutation_flags"]["provider_mutation_like_detected"] is True


def test_classify_quality_gate_blocks_on_a_real_secret_flag():
    document = {
        "classification": "passed",
        "ci": {"classification": "success"},
        "planning_summary": {
            "mutation_flags": {"provider_mutation_like_detected": False},
            "secret_or_artifact_flags": {"artifacts_detected": False, "credential_file_detected": False, "secret_value_like_detected": True},
        },
    }
    classification, _detail = bridge._classify_quality_gate(document)
    assert classification == "blocked"


def test_classify_quality_gate_passes_on_a_genuinely_clean_report():
    document = {
        "classification": "passed",
        "ci": {"classification": "success"},
        "planning_summary": {
            "mutation_flags": {"provider_mutation_like_detected": False},
            "secret_or_artifact_flags": {"artifacts_detected": False, "credential_file_detected": False, "secret_value_like_detected": False},
        },
    }
    classification, _detail = bridge._classify_quality_gate(document)
    assert classification == "passed"


def test_classify_quality_gate_is_unavailable_when_the_subprocess_produced_no_document():
    classification, _detail = bridge._classify_quality_gate(None)
    assert classification == "unavailable"


def test_readiness_preflight_invokes_the_quality_gate_with_from_git(monkeypatch):
    """Regression: without --from-git, run_local_quality_gate.py's own
    `paths` stays empty and provider_mutation_like_detected /
    secret_value_like_detected / artifacts_detected / credential_file_detected
    are permanently False regardless of the real working tree -- verified
    directly by calling run_local_quality_gate.run([], diff_text=...) vs
    run_local_quality_gate.run(["backend/foo.py"], diff_text=...) on an
    identical mutation-shaped diff (the second call alone detects it)."""
    calls: list[list[str]] = []
    real_run = bridge._run

    def spy(argv, **kwargs):
        calls.append(argv)
        return real_run(argv, **kwargs)

    monkeypatch.setattr(bridge, "_run", spy)
    bridge.readiness_preflight(REPO, skip_quality_gate=False)
    gate_calls = [argv for argv in calls if "run_local_quality_gate.py" in argv[1]]
    assert gate_calls, "run_local_quality_gate.py was never invoked"
    assert "--from-git" in gate_calls[0]


def test_from_git_is_what_actually_makes_mutation_detection_fire():
    """The real defect --from-git fixes, reproduced directly against the
    underlying run_local_quality_gate.run() (not the bridge) so this test
    fails again if a future edit ever drops --from-git silently."""
    from scripts.ai import run_local_quality_gate as gate

    mutation_diff = "diff --git a/backend/foo.py b/backend/foo.py\n+def create_order():\n+    pass\n"
    without_paths = gate.run([], diff_text=mutation_diff, branch="local")
    with_paths = gate.run(["backend/foo.py"], diff_text=mutation_diff, branch="local")
    assert without_paths["mutation_flags"]["provider_mutation_like_detected"] is False
    assert with_paths["mutation_flags"]["provider_mutation_like_detected"] is True


def test_readiness_preflight_is_unavailable_not_passed_when_the_quality_gate_subprocess_fails(monkeypatch):
    """Regression: a subprocess that genuinely failed to run/parse must
    surface as this phase's own "unavailable", never silently "passed" --
    a phase that never checked anything is not the same as one that
    checked and found no problem."""
    def fake_run(argv, **kwargs):
        if "check_dev_stack.py" in argv[1]:
            return {"ok": True, "reason": None, "json": {"tools": {"git": "git version 2.43.0"}}}
        if "coderos_snapshot.py" in argv[1]:
            return {"ok": True, "reason": None, "json": {"status": "success", "target_repo": str(REPO), "evidence_class": "simulated_readonly_snapshot"}}
        if "run_local_quality_gate.py" in argv[1]:
            return {"ok": False, "reason": "executable_not_found", "json": None}
        raise AssertionError(f"unexpected argv: {argv}")

    monkeypatch.setattr(bridge, "_run", fake_run)
    phase = bridge.readiness_preflight(REPO, skip_quality_gate=False)
    assert phase["classification"] == "unavailable"
    assert phase["detail"]["quality_gate"]["classification"] == "unavailable"


def test_readiness_preflight_does_not_block_on_a_missing_bare_python_tool(monkeypatch):
    """Regression: check_dev_stack.py only ever probes shutil.which("python"),
    which is None on any host with only a "python3" binary on PATH -- the
    common case on a fresh Linux/macOS checkout, the exact audience this
    bridge targets. Only a genuinely missing "git" should block."""
    def fake_run(argv, **kwargs):
        if "check_dev_stack.py" in argv[1]:
            return {"ok": True, "reason": None, "json": {"tools": {"git": "git version 2.43.0", "python": None}}}
        if "coderos_snapshot.py" in argv[1]:
            return {"ok": True, "reason": None, "json": {"status": "success"}}
        raise AssertionError(f"unexpected argv: {argv}")

    monkeypatch.setattr(bridge, "_run", fake_run)
    phase = bridge.readiness_preflight(REPO, skip_quality_gate=True)
    assert phase["classification"] != "blocked"


def test_readiness_preflight_blocks_when_git_itself_is_missing(monkeypatch):
    def fake_run(argv, **kwargs):
        assert "check_dev_stack.py" in argv[1]  # coderos_snapshot must never even be spawned
        return {"ok": True, "reason": None, "json": {"tools": {"git": None, "python": "Python 3.11.0"}}}

    monkeypatch.setattr(bridge, "_run", fake_run)
    phase = bridge.readiness_preflight(REPO, skip_quality_gate=True)
    assert phase["classification"] == "blocked"
    assert phase["detail"]["reason"] == "required_tool_missing"


def test_run_accepts_a_non_standard_exit_code_as_long_as_stdout_is_real_json(monkeypatch):
    """Regression: run_local_quality_gate.py has a documented 4th exit
    code (EXIT_CONFIGURATION=3) for a genuine configuration error; a fixed
    (0,1,2) exit-code allowlist would discard that JSON body before ever
    reading its real classification=="malformed"/"configuration_error"."""

    class FakeCompleted:
        returncode = 3
        stdout = json.dumps({"classification": "malformed", "status": "configuration_error"})
        stderr = ""

    monkeypatch.setattr(bridge.subprocess, "run", lambda *a, **k: FakeCompleted())
    result = bridge._run(["python3", "-m", "does_not_matter"], cwd=REPO)
    assert result["ok"] is True
    assert result["json"]["classification"] == "malformed"


def test_classify_quality_gate_against_the_actual_real_command_output():
    """Not a fixture -- runs the real command once and feeds its real
    output through the classifier, so a future schema change in
    run_local_quality_gate.py is caught here rather than only in
    production use of the bridge."""
    result = bridge._run([bridge.sys.executable, "scripts/ai/run_local_quality_gate.py", "--json"], cwd=REPO, timeout_s=60.0)
    assert result["ok"], result["reason"]
    classification, _detail = bridge._classify_quality_gate(result["json"])
    assert classification in bridge.CLASSIFICATIONS


# ---------------------------------------------------------------------------
# trustos_export
# ---------------------------------------------------------------------------


def test_trustos_export_is_not_run_with_no_upstream_rows():
    phase = bridge.trustos_export([])
    assert phase["classification"] == "not_run"


def test_trustos_export_passes_for_a_real_promoted_and_a_real_blocked_row():
    rows = [
        {"scenario": "dogfood_test_promoted", "achievable_stage": "scale_candidate", "promoted_to_launch": True, "blockers": []},
        {"scenario": "dogfood_test_blocked", "achievable_stage": "economics_screened", "promoted_to_launch": False, "blockers": ["evidence_state_insufficient_for_stage:fixture"]},
    ]
    phase = bridge.trustos_export(rows)
    assert phase["classification"] == "passed"
    assert phase["detail"]["exported_count"] == 2


def test_trustos_export_blocks_when_a_row_carries_a_secret_shaped_blocker():
    # The real TrustOS leakage check must reject this before export --
    # never silently export a secret-shaped value because it arrived
    # inside a "blockers" list rather than a top-level field.
    rows = [
        {
            "scenario": "dogfood_test_leaky",
            "achievable_stage": "economics_screened",
            "promoted_to_launch": False,
            "blockers": ["sk-live-abcdefghijklmnopqrstuvwx"],
        }
    ]
    phase = bridge.trustos_export(rows)
    assert phase["classification"] == "blocked"
    assert phase["detail"]["blocked"][0]["workspace_id"] == "dogfood-dogfood_test_leaky"


# ---------------------------------------------------------------------------
# sanitized_handoff overall-classification (most-severe-wins) logic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "classifications,expected_overall",
    [
        (["passed", "passed", "passed", "passed"], "passed"),
        (["passed", "not_run", "not_run", "not_run"], "not_run"),
        (["passed", "ci_unavailable", "passed", "passed"], "ci_unavailable"),
        (["passed", "passed", "unavailable", "passed"], "unavailable"),
        (["passed", "passed", "passed", "blocked"], "blocked"),
        (["passed", "passed", "malformed", "passed"], "malformed"),
        (["blocked", "malformed", "passed", "passed"], "malformed"),
    ],
)
def test_sanitized_handoff_overall_classification_is_most_severe_wins(classifications, expected_overall):
    phases = [bridge._phase(name, classification, {}) for name, classification in zip(bridge.PHASES, classifications)]
    report = bridge.sanitized_handoff(REPO, phases)
    assert report["overall_classification"] == expected_overall


def test_sanitized_handoff_never_runs_the_client_export_leakage_check_over_the_whole_report():
    """Regression for a real design mistake found while building this
    bridge: running check_workspace_leakage(client_safe=True) over the
    whole operator-facing report flags this report's own legitimate local
    "repository" path as a filesystem-path leak -- that check is correctly
    calibrated for client-facing exports, not this internal handoff.
    """
    phases = [bridge._phase(name, "passed", {}) for name in bridge.PHASES[:4]]
    report = bridge.sanitized_handoff(REPO, phases)
    assert report["overall_classification"] == "passed"
    assert str(REPO) == report["repository"]
    assert "leakage_paths" not in report


# ---------------------------------------------------------------------------
# CLI exit code
# ---------------------------------------------------------------------------


def test_main_returns_zero_for_a_passed_or_not_run_or_ci_unavailable_overall(capsys):
    exit_code = bridge.main(["--skip-quality-gate", "--skip-commercial", "--repo", str(REPO)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert bridge.SCHEMA in captured.out
