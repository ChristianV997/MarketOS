from __future__ import annotations

import json
import os
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


def _generate_pytest_junit(tmp_path: Path, name: str, source: str) -> Path:
    """Run a tiny hermetic pytest project and return its real JUnit XML report."""
    project = tmp_path / f"proj-{name}"
    project.mkdir()
    (project / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (project / "test_sample.py").write_text(source, encoding="utf-8")
    report = tmp_path / f"{name}.xml"
    subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={report}", "-c", "pytest.ini"],
        cwd=project,
        capture_output=True,
        check=False,
        timeout=120,
    )
    return report


_PYTEST_BASE = '''
import pytest

@pytest.fixture
def boom():
    raise RuntimeError("sk-CANARYFAKE0000 fixture")

def test_pass(): pass
def test_resolved(): assert False, "sk-CANARYFAKE0000 message"
def test_errors(boom): pass
@pytest.mark.skip(reason="r")
def test_skipped(): pass
@pytest.mark.xfail
def test_xfail(): assert False
@pytest.mark.xfail(strict=True)
def test_xpass_strict(): pass
@pytest.mark.parametrize("value", ["a b", "<&>", "x" * 700, "x" * 700 + "y"])
def test_param(value): pass
'''
_PYTEST_CANDIDATE = _PYTEST_BASE.replace(
    "def test_pass(): pass", "def test_pass(): assert False"
).replace('def test_resolved(): assert False, "sk-CANARYFAKE0000 message"', "def test_resolved(): pass")


def test_real_pytest_junit_round_trip_is_complete_and_classified(tmp_path: Path) -> None:
    base = _generate_pytest_junit(tmp_path, "base", _PYTEST_BASE)
    candidate = _generate_pytest_junit(tmp_path, "candidate", _PYTEST_CANDIDATE)
    result = comparator.compare(base, candidate)

    assert result["status"] == "complete", result["errors"]
    # pytest declares counts on the nested <testsuite>, which must be validated too.
    assert result["reports"]["base"]["counts"]["tests"] == 10
    comparison = result["comparison"]
    assert [key for key in comparison["candidate_only_failures"] if "test_pass" in key]
    assert [key for key in comparison["base_only_failures"] if "test_resolved" in key]
    assert any("test_errors" in key for key in comparison["shared_failures"])
    assert any("test_xpass_strict" in key for key in comparison["shared_failures"])
    # xfail is reported by pytest as <skipped>; it is an unchanged skip, not a failure.
    assert any("test_xfail" in key for key in comparison["shared_skips"])
    assert any("test_skipped" in key for key in comparison["shared_skips"])
    assert {change["node_key"].count("test_pass") for change in comparison["outcome_changes"]} >= {1}
    # long parametrize ids stay distinct, bounded, and do not invalidate the report
    long_keys = [key for key in comparison["unchanged"] if "test_param" in key and "~" in key]
    assert len(long_keys) == 2 and len(set(long_keys)) == 2
    assert all(len(key) < 1200 for key in long_keys)

    serialized = comparator._canonical_json(result) + comparator.render_text(result)
    assert "CANARYFAKE" not in serialized
    assert comparator.compare(base, candidate) == result


def test_long_testcase_field_is_truncated_with_stable_digest_not_rejected(tmp_path: Path) -> None:
    long_name = "n" * (comparator.MAX_FIELD_LENGTH + 50)
    first = _write_report(tmp_path, "a.xml", _suite(_case(long_name), tests=1, failures=0, errors=0, skipped=0))
    second = _write_report(tmp_path, "b.xml", _suite(_case(long_name), tests=1, failures=0, errors=0, skipped=0))
    loaded = comparator._load_report(first, "base")
    assert loaded["status"] == "complete"
    assert loaded["issue_codes"] == []
    assert len(loaded["cases"][0]["identity"]["name"]) <= comparator.MAX_FIELD_LENGTH
    assert comparator.compare(first, second)["comparison"]["unchanged"] == [loaded["cases"][0]["node_key"]]


def test_nested_suite_declared_count_mismatch_is_incomplete(tmp_path: Path) -> None:
    good = _write_report(
        tmp_path, "good.xml", f"<testsuites>{_suite(_case('a'), tests=1, failures=0, errors=0, skipped=0)}</testsuites>"
    )
    bad = _write_report(
        tmp_path, "bad.xml", f"<testsuites>{_suite(_case('a'), tests=3, failures=0, errors=0, skipped=0)}</testsuites>"
    )
    result = comparator.compare(good, bad)
    assert result["status"] == "incomplete"
    assert {"role": "candidate", "code": "declared_count_mismatch"} in result["errors"]


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-8"])
def test_doctype_is_rejected_regardless_of_encoding(tmp_path: Path, encoding: str) -> None:
    declaration = '<?xml version="1.0" encoding="%s"?>' % ("utf-16" if encoding.startswith("utf-16") else "utf-8")
    body = declaration + '<!DOCTYPE a [<!ENTITY e "x">]>' + _suite(_case("a"))
    hostile = tmp_path / "hostile.xml"
    hostile.write_bytes(body.encode(encoding))
    clean = _write_report(tmp_path, "clean.xml", _suite(_case("a")))
    result = comparator.compare(hostile, clean)
    assert result["status"] == "incomplete"
    assert {"role": "base", "code": "unsafe_xml_declaration"} in result["errors"]


def test_doctype_like_text_in_cdata_is_not_rejected(tmp_path: Path) -> None:
    literal = "<![CDATA[Literal markers: <!DOCTYPE and <!ENTITY are text here.]]>"
    report = _write_report(tmp_path, "cdata.xml", _suite(_case("literal", body=literal)))
    clean = _write_report(tmp_path, "clean.xml", _suite(_case("literal")))

    result = comparator.compare(report, clean)

    assert result["status"] == "complete"
    assert result["comparison"]["unchanged"] == ['{"classname":"tests.example","name":"literal"}']


@pytest.mark.parametrize(
    "declaration",
    [
        '<!DOCTYPE testsuite SYSTEM "file:///not-present">',
        '<!DOCTYPE testsuite [<!ENTITY external SYSTEM "file:///not-present">]>',
    ],
)
def test_external_doctype_and_entity_declarations_remain_rejected(
    tmp_path: Path, declaration: str
) -> None:
    hostile = _write_report(tmp_path, "external.xml", declaration + _suite(_case("a")))
    clean = _write_report(tmp_path, "clean.xml", _suite(_case("a")))

    result = comparator.compare(hostile, clean)

    assert result["status"] == "incomplete"
    assert {"role": "base", "code": "unsafe_xml_declaration"} in result["errors"]


def test_errors_never_echo_report_content(tmp_path: Path) -> None:
    canary = "sk-CANARYFAKE0000"
    hostile = _write_report(tmp_path, "bad.xml", f"<testsuite><testcase name='{canary}'><failure message='{canary}'")
    clean = _write_report(tmp_path, "clean.xml", _suite(_case("a")))
    result = comparator.compare(hostile, clean)
    rendered = comparator._canonical_json(result) + comparator.render_text(result)
    assert result["status"] == "incomplete"
    assert canary not in rendered


def test_directory_and_fifo_reports_are_not_files_and_never_block(tmp_path: Path) -> None:
    clean = _write_report(tmp_path, "clean.xml", _suite(_case("a")))
    result = comparator.compare(tmp_path, clean)
    assert {"role": "base", "code": "report_not_a_file"} in result["errors"]
    if hasattr(os, "mkfifo"):
        fifo = tmp_path / "fifo.xml"
        os.mkfifo(fifo)
        result = comparator.compare(fifo, clean)
        assert {"role": "base", "code": "report_not_a_file"} in result["errors"]


def test_same_identity_duplicates_with_matching_outcomes_are_order_independent(tmp_path: Path) -> None:
    forward = _write_report(tmp_path, "f.xml", _suite(_case("dup"), _case("dup", body="<failure />")))
    reverse = _write_report(tmp_path, "r.xml", _suite(_case("dup", body="<failure />"), _case("dup")))
    result = comparator.compare(forward, reverse)
    assert result["status"] == "complete"
    assert result["comparison"]["outcome_changes"] == []


def test_duplicate_identity_multiplicity_change_is_incomplete(tmp_path: Path) -> None:
    base = _write_report(
        tmp_path,
        "base.xml",
        _suite(_case("dup", body="<failure />")),
    )
    candidate = _write_report(
        tmp_path,
        "candidate.xml",
        _suite(_case("dup", body="<failure />"), _case("dup")),
    )

    result = comparator.compare(base, candidate)

    assert result["status"] == "incomplete"
    assert result["comparison"] is None
    assert {"role": "comparison", "code": "ambiguous_duplicate_testcase_identity"} in result["errors"]


def test_duplicate_identity_outcome_distribution_change_is_incomplete(tmp_path: Path) -> None:
    base = _write_report(
        tmp_path,
        "base.xml",
        _suite(_case("dup", body="<failure />"), _case("dup")),
    )
    candidate = _write_report(
        tmp_path,
        "candidate.xml",
        _suite(_case("dup", body="<error />"), _case("dup")),
    )

    result = comparator.compare(base, candidate)

    assert result["status"] == "incomplete"
    assert result["comparison"] is None
    assert {"role": "comparison", "code": "ambiguous_duplicate_testcase_identity"} in result["errors"]


def test_report_above_testcase_limit_retains_observed_count(tmp_path: Path) -> None:
    count = comparator.MAX_TESTCASES + 1
    body = f'<testsuite tests="{count}">' + '<testcase name="x"/>' * count + "</testsuite>"
    assert len(body.encode("utf-8")) < comparator.MAX_REPORT_BYTES
    oversized_count = _write_report(tmp_path, "many.xml", body)
    clean = _write_report(tmp_path, "clean.xml", _suite(_case("one")))

    result = comparator.compare(oversized_count, clean)
    base = result["reports"]["base"]

    assert result["status"] == "incomplete"
    assert base["test_count"] == count
    assert base["counts"]["tests"] == count
    assert "too_many_testcases" in base["issue_codes"]
    assert "no_testcases" not in base["issue_codes"]
