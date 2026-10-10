from __future__ import annotations

from xml.etree import ElementTree as ET

from scripts.ai.ci_failure_diagnostics import (
    MAX_CASES,
    MAX_INPUT_BYTES,
    MAX_SUMMARY_BYTES,
    build_diagnostics,
)


def test_diagnostics_are_parseable_bounded_and_redacted(tmp_path):
    raw = tmp_path / "raw.xml"
    junit = tmp_path / "out" / "junit.xml"
    summary = tmp_path / "out" / "summary.txt"
    fake_secret = "sk" + "_fixture_value"
    fake_assignment = "password" + "=fixture_value"
    raw.write_text(
        f"""<testsuites><testsuite tests=\"2\" failures=\"1\"><testcase """
        f"""classname=\"tests.secret\" name=\"test_{fake_secret}\" time=\"0.1\">"""
        f"""<failure message=\"{fake_assignment}\">Traceback raw payload</failure>"""
        """</testcase><testcase classname=\"tests.ok\" name=\"test_ok\" /></testsuite></testsuites>""",
        encoding="utf-8",
    )

    assert build_diagnostics(raw, junit, summary) == "ready"
    parsed = ET.parse(junit)
    output = junit.read_text(encoding="utf-8")
    summary_text = summary.read_text(encoding="utf-8")
    assert parsed.getroot().attrib["failures"] == "1"
    assert fake_secret not in output
    assert "Traceback raw payload" not in output
    assert fake_assignment not in output
    assert "test_ok" not in output
    assert "message=\"redacted\"" in output
    assert "failure_or_error_identities:" in summary_text
    assert fake_secret not in summary_text
    assert len(summary.read_bytes()) <= MAX_SUMMARY_BYTES


def test_malformed_and_oversized_junit_fail_closed_without_raw_content(tmp_path):
    junit = tmp_path / "junit.xml"
    summary = tmp_path / "summary.txt"
    malformed = tmp_path / "malformed.xml"
    malformed_marker = "malformed_fixture_marker"
    malformed.write_text(f"<testsuite><failure>{malformed_marker}</testsuite>", encoding="utf-8")
    assert build_diagnostics(malformed, junit, summary) == "malformed_junit"
    assert ET.parse(junit).getroot().attrib["tests"] == "0"
    assert malformed_marker not in summary.read_text(encoding="utf-8")

    oversized = tmp_path / "oversized.xml"
    oversized.write_bytes(b"x" * (MAX_INPUT_BYTES + 1))
    assert build_diagnostics(oversized, junit, summary) == "junit_too_large"
    assert "junit_too_large" in summary.read_text(encoding="utf-8")


def test_diagnostics_junit_projection_is_case_bounded(tmp_path):
    raw = tmp_path / "raw.xml"
    cases = "".join(
        f'<testcase classname="tests.x" name="test_{index}"><failure /></testcase>'
        for index in range(MAX_CASES + 5)
    )
    raw.write_text(f"<testsuite tests=\"{MAX_CASES + 5}\">{cases}</testsuite>", encoding="utf-8")

    junit = tmp_path / "junit.xml"
    summary = tmp_path / "summary.txt"
    assert build_diagnostics(raw, junit, summary) == "ready"

    root = ET.parse(junit).getroot()
    assert len(root.findall("testcase")) == MAX_CASES
    assert root.attrib["tests"] == str(MAX_CASES + 5)
    assert root.attrib["failures"] == str(MAX_CASES + 5)


def test_diagnostics_are_deterministic(tmp_path):
    raw = tmp_path / "raw.xml"
    raw.write_text(
        "<testsuite tests=\"1\" failures=\"1\"><testcase classname=\"tests.x\" "
        "name=\"test_failure\"><failure /></testcase></testsuite>",
        encoding="utf-8",
    )
    first_junit = tmp_path / "first.xml"
    first_summary = tmp_path / "first.txt"
    second_junit = tmp_path / "second.xml"
    second_summary = tmp_path / "second.txt"
    build_diagnostics(raw, first_junit, first_summary)
    build_diagnostics(raw, second_junit, second_summary)
    assert first_junit.read_bytes() == second_junit.read_bytes()
    assert first_summary.read_bytes() == second_summary.read_bytes()
