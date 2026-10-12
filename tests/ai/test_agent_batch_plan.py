"""Tests for the pre-dispatch agent batch plan validator."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.ai import agent_batch_plan as plan
from scripts.ai import validate_agent_batch_plan as cli

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "docs" / "ai" / "agent_batch_plan.sample.json"
POLICY = plan.load_policy()
ROSTER = {
    1: ["hermes-bots-team", "hermes-agents-a", "hermes-agents-b", "grok-bots-team", "antigravity-a"],
    2: ["antigravity-b", "antigravity-c", "antigravity-d", "cursor-a", "cursor-b"],
    3: ["cursor-c", "cursor-d", "claude-a", "claude-b", "claude-c", "claude-d"],
    4: ["codex-a", "codex-b", "codex-c", "codex-d", "grok-chat-a", "grok-chat-b"],
}


def _sample() -> dict:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def _assignments(data: dict) -> list[dict]:
    return [item for batch in data["batches"] for item in batch["assignments"]]


def _codes(report: dict) -> set[str]:
    return {item["code"] for item in report["errors"]}


def _check(data: dict, policy: dict | None = None) -> dict:
    return plan.validate_plan_object(data, POLICY if policy is None else policy)


def test_sample_manifest_is_valid_for_the_current_roster():
    report = _check(_sample())
    assert report["valid"] is True
    assert report["error_count"] == 0
    assert report["assignments_checked"] == 22


def test_policy_encodes_the_agreed_four_batch_roster_as_data():
    assert [batch["size"] for batch in POLICY["batches"]] == [5, 5, 6, 6]
    for batch in POLICY["batches"]:
        assert batch["agents"] == ROSTER[batch["batch"]]
    assert len(POLICY["agents"]) == 22
    assert POLICY["require_earlier_batch_dependencies"] is True


def test_output_is_deterministic_regardless_of_input_key_order():
    data = _sample()
    reordered = json.loads(json.dumps(data, sort_keys=True))
    first = json.dumps(_check(data), sort_keys=True)
    assert first == json.dumps(_check(data), sort_keys=True)
    assert first == json.dumps(_check(reordered), sort_keys=True)


def test_invalid_plan_errors_are_sorted_and_stable_across_key_order():
    data = _sample()
    _assignments(data)[5]["agent_id"] = "hermes-bots-team"
    _assignments(data)[3]["primary_paths"] = ["../escape.md"]
    reversed_data = json.loads(json.dumps(data), object_pairs_hook=lambda pairs: dict(reversed(pairs)))
    report = _check(data)
    assert json.dumps(report, sort_keys=True) == json.dumps(_check(reversed_data), sort_keys=True)
    codes = [item["code"] for item in report["errors"]]
    assert codes == sorted(codes)


def test_duplicate_agent_assignment_and_missing_agent_are_rejected():
    data = _sample()
    # Index 5 is batch 2's first slot; renaming it to a batch 1 agent is a duplicate in the wrong batch.
    _assignments(data)[5]["agent_id"] = "hermes-bots-team"
    codes = _codes(_check(data))
    assert {"duplicate_agent_assignment", "missing_agent", "agent_wrong_batch"} <= codes


def test_duplicate_task_and_prompt_ids_are_rejected():
    data = _sample()
    _assignments(data)[1]["task_id"] = _assignments(data)[0]["task_id"]
    _assignments(data)[2]["prompt_id"] = _assignments(data)[0]["prompt_id"]
    codes = _codes(_check(data))
    assert {"duplicate_task_id", "duplicate_prompt_id"} <= codes


def test_primary_primary_overlap_between_agents_is_rejected():
    data = _sample()
    _assignments(data)[1]["primary_paths"] = list(_assignments(data)[0]["primary_paths"])
    report = _check(data)
    assert "primary_primary_overlap" in _codes(report)
    overlap = next(item for item in report["errors"] if item["code"] == "primary_primary_overlap")
    assert overlap["agents"] == ["hermes-agents-a", "hermes-bots-team"]


@pytest.mark.parametrize(
    ("left_key", "right_key"), [("primary_paths", "fallback_paths"), ("fallback_paths", "primary_paths")]
)
def test_primary_fallback_overlap_is_rejected_in_both_directions(left_key, right_key):
    data = _sample()
    first, second = _assignments(data)[0], _assignments(data)[1]
    second[right_key] = list(first[left_key])
    assert "primary_fallback_overlap" in _codes(_check(data))


def test_fallback_fallback_overlap_between_agents_is_rejected():
    data = _sample()
    _assignments(data)[1]["fallback_paths"] = list(_assignments(data)[0]["fallback_paths"])
    assert "fallback_fallback_overlap" in _codes(_check(data))


def test_an_agents_own_primary_and_fallback_may_share_a_path():
    data = _sample()
    first = _assignments(data)[0]
    first["fallback_paths"] = list(first["primary_paths"])
    assert _check(data)["valid"] is True


def test_file_and_directory_prefix_overlap_is_rejected_but_siblings_are_not():
    data = _sample()
    _assignments(data)[0]["primary_paths"] = ["planning/agent-batch-sample/shared"]
    _assignments(data)[1]["primary_paths"] = ["planning/agent-batch-sample/shared/nested.md"]
    assert "primary_primary_overlap" in _codes(_check(data))

    sibling = _sample()
    _assignments(sibling)[0]["primary_paths"] = ["planning/agent-batch-sample/shared"]
    _assignments(sibling)[1]["primary_paths"] = ["planning/agent-batch-sample/shared2"]
    assert _check(sibling)["valid"] is True


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("../escape.md", "path_traversal"),
        ("planning/../escape.md", "path_traversal"),
        ("/etc/passwd", "path_absolute"),
        ("C:/Windows/system.ini", "path_absolute"),
        ("C:escape.md", "path_absolute"),
        ("//server/share/x.md", "path_absolute"),
        ("planning\\agent-batch-sample\\x.md", "path_not_normalized"),
        ("\\\\server\\share\\x.md", "path_not_normalized"),
        ("./planning/x.md", "path_not_normalized"),
        ("planning//x.md", "path_not_normalized"),
        ("planning/x/", "path_not_normalized"),
        (" planning/x.md", "path_not_normalized"),
        ("planning/x.md:stream", "invalid_path"),
        ("planning/x\x00.md", "invalid_path"),
        (".git/config", "forbidden_path"),
        ("artifacts/out.json", "forbidden_path"),
        (".env.local", "forbidden_path"),
        ("planning/secrets/x.md", "forbidden_path"),
    ],
)
def test_unsafe_or_non_canonical_scope_paths_are_rejected_without_echo(raw, code):
    data = _sample()
    _assignments(data)[0]["primary_paths"] = [raw]
    report = _check(data)
    assert report["valid"] is False
    assert code in _codes(report)
    assert raw not in json.dumps(report)


def test_dependency_cycle_is_rejected_when_batch_order_is_not_enforced():
    relaxed = dict(POLICY, require_earlier_batch_dependencies=False)
    data = _sample()
    first, second = _assignments(data)[0], _assignments(data)[1]
    first["depends_on"] = [second["task_id"]]
    second["depends_on"] = [first["task_id"]]
    report = _check(data, relaxed)
    cycle = next(item for item in report["errors"] if item["code"] == "dependency_cycle")
    assert cycle["ids"] == sorted([first["task_id"], second["task_id"]])


def test_same_or_later_batch_dependencies_are_rejected_under_the_default_policy():
    data = _sample()
    _assignments(data)[0]["depends_on"] = [_assignments(data)[-1]["task_id"]]
    assert "dependency_not_earlier_batch" in _codes(_check(data))


def test_unknown_self_and_duplicate_dependencies_are_rejected():
    data = _sample()
    first = _assignments(data)[0]
    first["depends_on"] = ["b9-missing", first["task_id"], "b9-missing"]
    codes = _codes(_check(data))
    assert {"unknown_dependency", "dependency_self", "duplicate_dependency"} <= codes


def test_batch_count_order_size_and_boolean_batch_numbers_are_enforced():
    short = _sample()
    short["batches"].pop()
    assert "batch_count_mismatch" in _codes(_check(short))

    reordered = _sample()
    reordered["batches"][0]["batch"] = 2
    assert "batch_order_mismatch" in _codes(_check(reordered))

    boolean = _sample()
    boolean["batches"][0]["batch"] = True
    assert "batch_order_mismatch" in _codes(_check(boolean))

    moved = _sample()
    moved["batches"][2]["assignments"].append(moved["batches"][1]["assignments"].pop())
    assert "batch_size_mismatch" in _codes(_check(moved))

    # Swapping two agents between batches keeps every size correct, so only the wrong-batch rule fires.
    swapped = _sample()
    first = swapped["batches"][1]["assignments"][0]
    second = swapped["batches"][2]["assignments"][0]
    first["agent_id"], second["agent_id"] = second["agent_id"], first["agent_id"]
    report = _check(swapped)
    assert _codes(report) == {"agent_wrong_batch"}
    assert sorted(item["agents"][0] for item in report["errors"]) == ["antigravity-b", "cursor-c"]


def test_unknown_and_missing_agents_are_rejected_without_echoing_the_unknown_id():
    data = _sample()
    _assignments(data)[0]["agent_id"] = "rogue-agent"
    report = _check(data)
    assert {"unknown_agent", "missing_agent"} <= _codes(report)
    assert "rogue-agent" not in json.dumps(report)


def test_secret_shaped_values_are_reported_without_echoing_them():
    secret = "ghp_" + "A" * 36
    data = _sample()
    _assignments(data)[0]["task_id"] = secret
    data["batches"][0]["api_key"] = "not-a-real-value"
    report = _check(data)
    assert {"sensitive_value", "sensitive_field"} <= _codes(report)
    text = json.dumps(report)
    assert secret not in text
    assert "api_key" not in text
    assert "not-a-real-value" not in text


def test_prompt_text_cannot_be_embedded_in_a_plan():
    data = _sample()
    _assignments(data)[0]["prompt"] = "Private instructions ZZQ-7731 do not share"
    report = _check(data)
    assert "unknown_field" in _codes(report)
    assert "ZZQ-7731" not in json.dumps(report)


def test_top_level_shape_is_enforced():
    data = _sample()
    data["schema"] = "MarketOS.Other.v1"
    del data["session_id"]
    data["extra"] = 1
    assert {"schema_mismatch", "missing_field", "unknown_field"} <= _codes(_check(data))


@pytest.mark.parametrize(
    ("raw", "allowed"),
    [
        (b"", {"manifest_malformed"}),
        (b"{", {"manifest_malformed"}),
        (b"[]", {"manifest_not_object"}),
        (b'{"schema": "a", "schema": "b"}', {"manifest_duplicate_key"}),
        (b'{"schema": NaN}', {"manifest_malformed"}),
        (b"\xff\xfe\x00", {"manifest_malformed"}),
        (b"[" * 5_000 + b"]" * 5_000, {"manifest_malformed", "manifest_not_object"}),
    ],
)
def test_malformed_manifests_fail_closed(raw, allowed):
    report = plan.validate_plan_bytes(raw, POLICY)
    assert report["valid"] is False
    assert _codes(report) and _codes(report) <= allowed


def test_oversized_manifest_is_rejected_before_parsing():
    report = plan.validate_plan_bytes(b" " * (plan.MAX_MANIFEST_BYTES + 1), POLICY)
    assert _codes(report) == {"manifest_too_large"}


def test_deeply_nested_manifest_is_rejected():
    nested: dict = {"x": None}
    for _ in range(12):
        nested = {"x": nested}
    assert _codes(plan.validate_plan_object(nested, POLICY)) == {"manifest_too_deep"}


def test_excessive_list_length_is_rejected():
    data = _sample()
    _assignments(data)[0]["primary_paths"] = [
        f"planning/agent-batch-sample/bulk/{index}.md" for index in range(plan.MAX_LIST_ITEMS + 1)
    ]
    assert "too_many_items" in _codes(_check(data))


def test_oversized_batch_is_flagged_and_checked_only_up_to_the_policy_size():
    data = _sample()
    # A flood of identical-looking slots must stay bounded: the overlap check never sees more than the roster.
    flood = _assignments(data)[0]
    data["batches"][0]["assignments"] = [copy.deepcopy(flood) for _ in range(500)]
    report = _check(data)
    assert "batch_size_mismatch" in _codes(report)
    assert report["assignments_checked"] <= sum(batch["size"] for batch in POLICY["batches"])


def test_policy_rejects_size_mismatch_duplicate_agents_and_missing_files(tmp_path):
    raw = json.loads(plan.POLICY_PATH.read_text(encoding="utf-8"))

    bad_size = copy.deepcopy(raw)
    bad_size["batches"][0]["size"] = 4
    path = tmp_path / "bad_size.json"
    path.write_text(json.dumps(bad_size), encoding="utf-8")
    with pytest.raises(plan.PlanError) as caught:
        plan.load_policy(path)
    assert caught.value.code == "policy_size_mismatch"

    duplicate = copy.deepcopy(raw)
    duplicate["batches"][1]["agents"][0] = "hermes-bots-team"
    path.write_text(json.dumps(duplicate), encoding="utf-8")
    with pytest.raises(plan.PlanError) as caught:
        plan.load_policy(path)
    assert caught.value.code == "policy_invalid"

    with pytest.raises(plan.PlanError) as caught:
        plan.load_policy(tmp_path / "absent.json")
    assert caught.value.code == "policy_unreadable"


def test_cli_exits_zero_for_the_sample_and_reports_deterministically(capsys):
    assert cli.main([str(SAMPLE)]) == 0
    first = capsys.readouterr().out
    assert cli.main([str(SAMPLE)]) == 0
    assert capsys.readouterr().out == first
    assert json.loads(first)["valid"] is True


def test_cli_exits_two_on_an_invalid_plan_without_echoing_the_path(tmp_path, capsys):
    data = _sample()
    _assignments(data)[0]["primary_paths"] = ["../escape.md"]
    target = tmp_path / "plan-under-review.json"
    target.write_text(json.dumps(data), encoding="utf-8")
    assert cli.main([str(target)]) == 2
    out = capsys.readouterr().out
    assert "path_traversal" in out
    assert "plan-under-review" not in out
    assert str(tmp_path) not in out


def test_cli_reports_unreadable_inputs_without_echoing_the_path(tmp_path, capsys):
    absent = tmp_path / "absent-plan.json"
    assert cli.main([str(absent)]) == 2
    out = capsys.readouterr().out
    assert "manifest_unreadable" in out
    assert "absent-plan" not in out

    # A directory is not a regular file and must not be opened.
    assert cli.main([str(tmp_path)]) == 2
    assert "manifest_unreadable" in capsys.readouterr().out


def test_cli_rejects_a_malformed_policy_before_reading_the_plan(tmp_path, capsys):
    bad = tmp_path / "policy.json"
    bad.write_text("{", encoding="utf-8")
    assert cli.main([str(SAMPLE), "--policy", str(bad)]) == 2
    assert "policy_malformed" in capsys.readouterr().out


@pytest.mark.parametrize("module", [plan, cli])
def test_validator_source_has_no_network_process_or_credential_access(module):
    source = Path(module.__file__).read_text(encoding="utf-8")
    for banned in ("subprocess", "socket", "urllib", "http.client", "requests", "getenv", "os.environ", "importlib"):
        assert banned not in source, banned
