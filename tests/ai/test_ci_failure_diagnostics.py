from __future__ import annotations

from io import BytesIO
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


def test_diagnostics_redact_common_secret_and_absolute_path_shapes(tmp_path):
    raw = tmp_path / "raw.xml"
    junit = tmp_path / "junit.xml"
    summary = tmp_path / "summary.txt"
    fake_github_token = "".join(("g", "h", "o", "_", "fixture", "_token"))
    fake_slack_token = "".join(("x", "o", "x", "b", "-", "fixture", "-token"))
    fake_aws_key = "".join(("A", "K", "I", "A", "1234", "5678", "90AB", "CDEF"))
    fake_bearer = "".join(("Bear", "er", " ", "fixture_bearer_token"))
    windows_path = r"C:\runner\_work\MarketOS\secret.py"
    unc_path = r"\\server\share\secret.py"
    posix_path = "/var/lib/runner/workspace/secret.py"
    raw.write_text(
        f'<testsuite tests="1" failures="1"><testcase '
        f'classname="{windows_path}" name="{fake_github_token} {fake_slack_token} '
        f'{fake_aws_key} {fake_bearer} {unc_path} {posix_path}"><failure /></testcase></testsuite>',
        encoding="utf-8",
    )

    assert build_diagnostics(raw, junit, summary) == "ready"
    output = junit.read_text(encoding="utf-8")
    summary_text = summary.read_text(encoding="utf-8")
    for value in (
        fake_github_token,
        fake_slack_token,
        fake_aws_key,
        fake_bearer,
        windows_path,
        unc_path,
        posix_path,
    ):
        assert value not in output
        assert value not in summary_text
    assert "[redacted-secret]" in output
    assert "[redacted-path]" in output


def test_diagnostics_redact_bearer_token_inside_assignment_metadata(tmp_path):
    raw = tmp_path / "raw.xml"
    junit = tmp_path / "junit.xml"
    summary = tmp_path / "summary.txt"
    token_tail = "ci_fixture_authorization_canary"
    raw.write_text(
        '<testsuite tests="1" failures="1"><testcase '
        'classname="authorization=&quot;Bearer ' + token_tail + '&quot;" '
        'name="test_auth"><failure /></testcase></testsuite>',
        encoding="utf-8",
    )

    assert build_diagnostics(raw, junit, summary) == "ready"
    output = junit.read_text(encoding="utf-8") + summary.read_text(encoding="utf-8")
    assert token_tail not in output
    assert "Bearer" not in output
    assert "[redacted-secret]" in output


def test_diagnostics_redact_relative_path_like_metadata(tmp_path):
    raw = tmp_path / "raw.xml"
    junit = tmp_path / "junit.xml"
    summary = tmp_path / "summary.txt"
    path_marker = "ci_fixture_relative_path_canary"
    raw.write_text(
        '<testsuite tests="1" failures="1"><testcase '
        'classname="../../' + path_marker + '" '
        'name="fixtures/' + path_marker + '.py"><failure /></testcase></testsuite>',
        encoding="utf-8",
    )

    assert build_diagnostics(raw, junit, summary) == "ready"
    output = junit.read_text(encoding="utf-8") + summary.read_text(encoding="utf-8")
    assert path_marker not in output
    assert "../" not in output
    assert "fixtures/" not in output
    assert "[redacted-path]" in output


def test_diagnostics_reject_a_valid_non_junit_root(tmp_path):
    raw = tmp_path / "not-junit.xml"
    raw.write_text("<report><testcase name=\"fixture\" /></report>", encoding="utf-8")
    junit = tmp_path / "junit.xml"
    summary = tmp_path / "summary.txt"

    assert build_diagnostics(raw, junit, summary) == "malformed_junit"
    assert "malformed_junit" in summary.read_text(encoding="utf-8")


def test_diagnostics_enforce_byte_cap_after_input_changes(tmp_path):
    class GrowingInput:
        def is_file(self):
            return True

        def open(self, mode):
            assert mode == "rb"
            return BytesIO(b"x" * (MAX_INPUT_BYTES + 1))

    junit = tmp_path / "junit.xml"
    summary = tmp_path / "summary.txt"

    assert build_diagnostics(GrowingInput(), junit, summary) == "junit_too_large"


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


def test_summary_byte_cap_preserves_utf8_boundaries(tmp_path):
    raw = tmp_path / "raw.xml"
    cases = "".join(
        '<testcase classname="tests.unicode" name="' + ("€" * 240) + '"><failure /></testcase>'
        for _ in range(MAX_CASES)
    )
    raw.write_text(
        f'<testsuite tests="{MAX_CASES}" failures="{MAX_CASES}">{cases}</testsuite>',
        encoding="utf-8",
    )

    junit = tmp_path / "junit.xml"
    summary = tmp_path / "summary.txt"
    assert build_diagnostics(raw, junit, summary) == "ready"
    summary_bytes = summary.read_bytes()
    assert len(summary_bytes) <= MAX_SUMMARY_BYTES
    assert summary_bytes.endswith(b"\n")
    summary_bytes.decode("utf-8")


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


def test_summary_identities_exclude_skipped_cases(tmp_path):
    raw = tmp_path / "raw.xml"
    raw.write_text(
        "<testsuite tests=\"2\" failures=\"1\" skipped=\"1\">"
        "<testcase classname=\"tests.failed\" name=\"test_failure\"><failure /></testcase>"
        "<testcase classname=\"tests.skipped\" name=\"test_skip\"><skipped /></testcase>"
        "</testsuite>",
        encoding="utf-8",
    )
    junit = tmp_path / "junit.xml"
    summary = tmp_path / "summary.txt"

    assert build_diagnostics(raw, junit, summary) == "ready"
    summary_text = summary.read_text(encoding="utf-8")
    assert "tests.failed::test_failure" in summary_text
    assert "tests.skipped::test_skip" not in summary_text
