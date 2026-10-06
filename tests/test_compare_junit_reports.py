from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ai import compare_junit_reports as comparator


def _write_report(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _suite(
    *cases: str,
    tests: int | None = None,
    failures: int | None = None,
    errors: int | None = None,
    skipped: int | None = None,
) -> str:
    attributes = "" if tests is None else f' tests="{tests}"'
    attributes += "" if failures is None else f' failures="{failures}"'
    attributes += "" if errors is None else f' errors="{errors}"'
    attributes += "" if skipped is None else f' skipped="{skipped}"'
    return f"<testsuite{attributes}>{''.join(cases)}</testsuite>"


def _case(name: str, *, classname: str = "tests.example", file: str | None = None, body: str = "") -> str:
    file_attr = "" if file is None else f' file="{file}"'
    return f'<testcase classname="{classname}" name="{name}"{file_attr}>{body}</testcase>'


def test_compares_failures_errors_skips_and_missing_cases(tmp_path: Path) -> None:
    base = _write_report(
        tmp_path,
        "base.xml",
        _suite(
            _case("shared", body="<failure message=\"base\" />"),
            _case("candidate-failure"),
            _case("base-only", body="<error message=\"base\" />"),
            _case("same-skip", body="<skipped />"),
            _case("candidate-skip"),
            tests=5,
            failures=1,
            errors=1,
            skipped=1,
        ),
    )
    candidate = _write_report(
        tmp_path,
        "candidate.xml",
        _suite(
            _case("shared", body="<error message=\"candidate\" />"),
            _case("candidate-failure", body="<failure message=\"candidate\" />"),
            _case("same-skip", body="<skipped />"),
            _case("candidate-skip", body="<skipped />"),
            _case("new-pass"),
            tests=5,
            failures=1,
            errors=1,
            skipped=2,
        ),
    )

    result = comparator.compare(base, candidate)

    assert result["status"] == "complete"
    comparison = result["comparison"]
    assert comparison["shared_failures"] == ['{"classname":"tests.example","name":"shared"}']
    assert comparison["candidate_only_failures"] == ['{"classname":"tests.example","name":"candidate-failure"}']
    assert comparison["base_only_failures"] == ['{"classname":"tests.example","name":"base-only"}']
    assert comparison["shared_skips"] == ['{"classname":"tests.example","name":"same-skip"}']
    assert comparison["candidate_skips"] == [
        '{"classname":"tests.example","name":"candidate-skip"}',
        '{"classname":"tests.example","name":"same-skip"}',
    ]
    assert comparison["base_missing"] == ['{"classname":"tests.example","name":"new-pass"}']
    assert comparison["outcome_changes"] == [
        {
            "node_key": '{"classname":"tests.example","name":"base-only"}',
            "base": "error",
            "candidate": "missing",
        },
        {
            "node_key": '{"classname":"tests.example","name":"candidate-failure"}',
            "base": "passed",
            "candidate": "failure",
        },
        {
            "node_key": '{"classname":"tests.example","name":"candidate-skip"}',
            "base": "passed",
            "candidate": "skipped",
        },
        {
            "node_key": '{"classname":"tests.example","name":"new-pass"}',
            "base": "missing",
            "candidate": "passed",
        },
        {
            "node_key": '{"classname":"tests.example","name":"shared"}',
            "base": "failure",
            "candidate": "error",
        },
    ]
    assert comparison["candidate_missing"] == ['{"classname":"tests.example","name":"base-only"}']


def test_testsuites_wrapper_and_duplicate_looking_names_keep_distinct_keys(tmp_path: Path) -> None:
    base = _write_report(
        tmp_path,
        "base.xml",
        "<testsuites><testsuite>"
        + _case("same", classname="package.one", file="one.py")
        + _case("same", classname="package.two", file="two.py")
        + _case("same", classname="package.one", file="one.py")
        + "</testsuite></testsuites>",
    )
    candidate = _write_report(
        tmp_path,
        "candidate.xml",
        "<testsuites><testsuite>"
        + _case("same", classname="package.one", file="one.py")
        + _case("same", classname="package.two", file="two.py")
        + _case("same", classname="package.one", file="one.py")
        + "</testsuite></testsuites>",
    )

    result = comparator.compare(base, candidate)

    assert result["status"] == "complete"
    keys = result["comparison"]["unchanged"]
    assert len(keys) == 3
    assert len(set(keys)) == 3
    assert any("package.two" in key for key in keys)
    assert any("duplicate-2" in key for key in keys)


def test_pytest_shaped_nested_suites_preserve_file_and_line_identity(tmp_path: Path) -> None:
    pytest_xml = (
        '<testsuites name="pytest tests"><testsuite name="pytest" tests="2" failures="1" errors="0" skipped="0">'
        '<testcase classname="test_api" name="test_one[param]" file="tests/test_api.py" line="12" />'
        '<testcase classname="test_api" name="test_two" file="tests/test_api.py" line="18"><failure /></testcase>'
        "</testsuite></testsuites>"
    )
    base = _write_report(tmp_path, "base.xml", pytest_xml)
    candidate = _write_report(tmp_path, "candidate.xml", pytest_xml)

    result = comparator.compare(base, candidate)

    assert result["status"] == "complete"
    keys = result["comparison"]["shared_failures"]
    assert keys == ['{"classname":"test_api","file":"tests/test_api.py","line":"18","name":"test_two"}']
    assert result["comparison"]["node_count"] == 2


@pytest.mark.parametrize(
    ("base_body", "candidate_body", "expected_code"),
    [
        ("<testsuite>", "<testsuite><testcase name=\"ok\" /></testsuite>", "malformed_xml"),
        ("<testsuite><testcase name=\"ok\" /></testsuite>", "<not-junit />", "invalid_junit_root"),
    ],
)
def test_malformed_reports_are_incomplete_and_not_passes(
    tmp_path: Path, base_body: str, candidate_body: str, expected_code: str
) -> None:
    base = _write_report(tmp_path, "base.xml", base_body)
    candidate = _write_report(tmp_path, "candidate.xml", candidate_body)

    result = comparator.compare(base, candidate)

    assert result["status"] == "incomplete"
    assert result["comparison"] is None
    assert any(item["code"] == expected_code for item in result["errors"])


def test_missing_report_is_incomplete_and_cli_returns_nonzero(tmp_path: Path) -> None:
    candidate = _write_report(tmp_path, "candidate.xml", _suite(_case("ok")))
    missing = tmp_path / "missing.xml"

    result = comparator.compare(missing, candidate)
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/ai/compare_junit_reports.py",
            "--base",
            str(missing),
            "--candidate",
            str(candidate),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result["status"] == "incomplete"
    assert any(item["code"] == "missing_report" for item in result["errors"])
    assert completed.returncode == comparator.EXIT_INCOMPLETE
    assert json.loads(completed.stdout)["status"] == "incomplete"
    assert "traceback" not in completed.stderr.lower()


def test_declared_count_mismatch_is_incomplete(tmp_path: Path) -> None:
    base = _write_report(tmp_path, "base.xml", _suite(_case("ok"), tests=2))
    candidate = _write_report(tmp_path, "candidate.xml", _suite(_case("ok")))

    result = comparator.compare(base, candidate)

    assert result["status"] == "incomplete"
    assert any(item["code"] == "declared_count_mismatch" for item in result["errors"])


def test_oversized_reports_are_bounded(tmp_path: Path) -> None:
    base = tmp_path / "base.xml"
    candidate = _write_report(tmp_path, "candidate.xml", _suite(_case("ok")))
    base.write_bytes(b"<testsuite>" + (b" " * comparator.MAX_REPORT_BYTES) + b"</testsuite>")

    result = comparator.compare(base, candidate)

    assert result["status"] == "incomplete"
    assert any(item["code"] == "report_too_large" for item in result["errors"])


def test_json_and_text_are_deterministic(tmp_path: Path) -> None:
    base = _write_report(tmp_path, "base.xml", _suite(_case("b"), _case("a")))
    candidate = _write_report(tmp_path, "candidate.xml", _suite(_case("a"), _case("b")))
    first = comparator.compare(base, candidate)
    second = comparator.compare(base, candidate)

    assert comparator._canonical_json(first) == comparator._canonical_json(second)
    assert comparator.render_text(first) == comparator.render_text(second)
    assert "status: complete" in comparator.render_text(first)


def test_text_includes_outcome_changes(tmp_path: Path) -> None:
    base = _write_report(tmp_path, "base.xml", _suite(_case("changed")))
    candidate = _write_report(
        tmp_path,
        "candidate.xml",
        _suite(_case("changed", body="<failure />")),
    )

    result = comparator.compare(base, candidate)
    rendered = comparator.render_text(result)

    assert "outcome_changes: 1" in rendered
    assert '- {"classname":"tests.example","name":"changed"}: passed -> failure' in rendered
