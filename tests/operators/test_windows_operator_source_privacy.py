"""Source-level privacy for the Windows operator safety and scenario modules.

Exceptions raised by these modules must not echo an absolute path, a secret-shaped basename, or
file-body content. Every canary below is synthetic; the exit-code and stable-reason contracts stay pinned.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.operators import windows_operator_safety as safety
from scripts.operators import windows_operator_scenarios as scenarios
from scripts.operators.windows_operator_safety import OperatorSafetyError

DIR_CANARY = "pathcanary7f3a"
LEAF_CANARY = "sk-test-LEAFCANARY0123456789"
BODY_CANARY = "bodycanary9c41e2"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    base = tmp_path / f"root-{DIR_CANARY}"
    base.mkdir()
    return base


def _assert_private(exc: BaseException, root: Path) -> None:
    text = str(exc)
    assert str(root) not in text
    assert DIR_CANARY not in text
    assert LEAF_CANARY not in text
    assert BODY_CANARY not in text


def test_missing_input_names_the_label_not_the_absolute_path(root: Path) -> None:
    with pytest.raises(OperatorSafetyError, match="source does not exist") as caught:
        safety.require_safe_input(root, f"{LEAF_CANARY}.json", label="source")
    assert caught.value.exit_code == 2
    _assert_private(caught.value, root)


def test_disallowed_suffix_names_the_allowed_types_not_the_path(root: Path) -> None:
    (root / f"{LEAF_CANARY}.txt").write_text("x", encoding="utf-8")
    with pytest.raises(OperatorSafetyError, match=r"source must be \.json, \.csv, or \.md") as caught:
        safety.require_safe_input(root, f"{LEAF_CANARY}.txt", label="source")
    assert caught.value.exit_code == 2
    _assert_private(caught.value, root)


def test_non_object_json_is_refused_without_echoing_the_path_or_body(root: Path) -> None:
    path = root / f"{LEAF_CANARY}.json"
    path.write_text(json.dumps([BODY_CANARY]), encoding="utf-8")
    with pytest.raises(OperatorSafetyError, match="JSON object required") as caught:
        safety.load_json_object(path)
    assert caught.value.exit_code == 2
    _assert_private(caught.value, root)


def test_secret_shaped_json_keeps_exit_four_without_echoing_the_path(root: Path) -> None:
    path = root / f"{LEAF_CANARY}-secret.json"
    path.write_text(json.dumps({"note": "sk-live-BODYCANARY0123456789abcdef"}), encoding="utf-8")
    with pytest.raises(OperatorSafetyError, match="secret-shaped content rejected") as caught:
        safety.load_json_object(path)
    assert caught.value.exit_code == 4
    _assert_private(caught.value, root)


def test_unreadable_json_input_keeps_its_os_error_type_without_the_path(root: Path) -> None:
    path = root / f"{LEAF_CANARY}-missing.json"
    with pytest.raises(FileNotFoundError) as caught:
        safety.load_json_object(path)
    _assert_private(caught.value, root)


@pytest.mark.parametrize("error_type", [OSError, RuntimeError], ids=["oserror", "runtimeerror-symlink-loop"])
def test_resolve_failure_is_reported_as_a_fixed_reason(root: Path, monkeypatch: pytest.MonkeyPatch, error_type: type) -> None:
    def fail_resolve(self, *args, **kwargs):
        raise error_type(f"symbolic link loop at {self}")

    monkeypatch.setattr(Path, "resolve", fail_resolve)
    with pytest.raises(OSError) as caught:
        safety.require_safe_input(root, f"{LEAF_CANARY}.json", label="source")
    assert str(caught.value) == "path could not be resolved"
    _assert_private(caught.value, root)


def test_non_object_scenario_is_refused_without_echoing_the_path_or_body(root: Path) -> None:
    path = root / f"{LEAF_CANARY}.json"
    path.write_text(json.dumps([BODY_CANARY]), encoding="utf-8")
    with pytest.raises(OperatorSafetyError, match="scenario must be an object") as caught:
        scenarios.load_scenario(path)
    assert caught.value.exit_code == 2
    _assert_private(caught.value, root)


def test_secret_shaped_scenario_keeps_exit_four_without_echoing_the_path(root: Path) -> None:
    path = root / f"{LEAF_CANARY}-scenario.json"
    path.write_text(
        json.dumps({"schema_version": scenarios.SCENARIO_SCHEMA, "note": "sk-live-BODYCANARY0123456789abcdef"}),
        encoding="utf-8",
    )
    with pytest.raises(OperatorSafetyError, match="secret-shaped scenario rejected") as caught:
        scenarios.load_scenario(path)
    assert caught.value.exit_code == 4
    _assert_private(caught.value, root)


def test_body_controlled_schema_value_is_not_echoed(root: Path) -> None:
    path = root / "schema-scenario.json"
    path.write_text(json.dumps({"schema_version": BODY_CANARY}), encoding="utf-8")
    with pytest.raises(OperatorSafetyError, match="unsupported scenario schema") as caught:
        scenarios.load_scenario(path)
    assert caught.value.exit_code == 2
    _assert_private(caught.value, root)


def test_missing_stages_names_only_the_fixed_required_list(root: Path) -> None:
    path = root / "nostage-scenario.json"
    path.write_text(
        json.dumps({"schema_version": scenarios.SCENARIO_SCHEMA, "scenario_id": "hydroponics", "stages": {}}),
        encoding="utf-8",
    )
    with pytest.raises(OperatorSafetyError, match="scenario missing stages") as caught:
        scenarios.load_scenario(path)
    assert "ingestion" in str(caught.value)
    _assert_private(caught.value, root)


def test_body_controlled_stage_name_and_class_are_not_echoed(root: Path) -> None:
    stages = {name: "fixture" for name in scenarios.REQUIRED_STAGES}
    stages[BODY_CANARY] = BODY_CANARY
    path = root / "stage-scenario.json"
    path.write_text(
        json.dumps({"schema_version": scenarios.SCENARIO_SCHEMA, "scenario_id": "hydroponics", "stages": stages}),
        encoding="utf-8",
    )
    with pytest.raises(OperatorSafetyError, match="invalid stage class") as caught:
        scenarios.load_scenario(path)
    assert caught.value.exit_code == 2
    _assert_private(caught.value, root)


def test_missing_scenario_pack_directory_does_not_echo_the_path(root: Path) -> None:
    with pytest.raises(OperatorSafetyError, match="scenario pack directory missing") as caught:
        scenarios.run_scenario_pack(root / f"{DIR_CANARY}-nodir")
    assert caught.value.exit_code == 2
    _assert_private(caught.value, root)


def test_scenario_id_mismatch_names_only_the_fixed_scenario(root: Path) -> None:
    pack = root / f"pack-{DIR_CANARY}"
    pack.mkdir()
    for scenario_id in scenarios.REQUIRED_SCENARIOS:
        body = {
            "schema_version": scenarios.SCENARIO_SCHEMA,
            "scenario_id": f"wrong-{BODY_CANARY}",
            "stages": {name: "fixture" for name in scenarios.REQUIRED_STAGES},
        }
        (pack / f"{scenario_id}.json").write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(OperatorSafetyError, match="scenario_id mismatch for") as caught:
        scenarios.run_scenario_pack(pack)
    assert caught.value.exit_code == 2
    _assert_private(caught.value, root)


def test_missing_required_scenario_keeps_its_stable_reason(root: Path) -> None:
    pack = root / "empty-pack"
    pack.mkdir()
    with pytest.raises(OperatorSafetyError, match="missing required scenario: ") as caught:
        scenarios.run_scenario_pack(pack)
    assert caught.value.exit_code == 2
    _assert_private(caught.value, root)
