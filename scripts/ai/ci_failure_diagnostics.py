"""Create bounded, redacted diagnostics for a blocking pytest run.

The CI workflow keeps the raw pytest stream in the runner temp directory and
publishes only this sanitized JUnit projection plus a short summary. This is a
diagnostic adapter, not a test or readiness authority.
"""

from __future__ import annotations

import argparse
import math
import re
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

MAX_INPUT_BYTES = 5 * 1024 * 1024
MAX_CASES = 100
MAX_IDENTIFIER_CHARS = 240
MAX_SUMMARY_BYTES = 32 * 1024

_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|authorization|bearer|cookie|password|secret|token)\b"
    r"\s*[:=]\s*['\"]?[^\s,;\"'}]+"
)
_SECRET_PREFIX = re.compile(
    r"(?i)(?<![a-z0-9])(?:github_pat|gh[opusr]|sk|xox[baprs]|npm)[_-][a-z0-9_-]{6,}"
    r"|(?<![a-z0-9])akia[0-9a-z]{16,}(?![a-z0-9])"
)
_SECRET_BEARER = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{6,}")
_ABSOLUTE_PATH = re.compile(
    r"(?ix)(?:\b[a-z]:[\\/][^\s\"']*|(?<!\S)\\\\[^\s\"']*|"
    r"(?<![a-z0-9_:/])/[^\s\"']*)"
)
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]+")


def _safe_text(value: object) -> str:
    text = _CONTROL_CHARS.sub(" ", str(value or "")).strip()
    text = _SECRET_ASSIGNMENT.sub("[redacted-secret]", text)
    text = _SECRET_PREFIX.sub("[redacted-secret]", text)
    text = _SECRET_BEARER.sub("[redacted-secret]", text)
    text = _ABSOLUTE_PATH.sub("[redacted-path]", text)
    return text[:MAX_IDENTIFIER_CHARS]


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _nonnegative_int(value: object) -> int | None:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _count(root: ET.Element, attribute: str, observed: int) -> int:
    declared = _nonnegative_int(root.attrib.get(attribute))
    if declared is None:
        suite_counts = [
            _nonnegative_int(suite.attrib.get(attribute))
            for suite in root.iter()
            if _tag(suite) == "testsuite"
        ]
        values = [value for value in suite_counts if value is not None]
        declared = sum(values) if values else observed
    return max(declared, observed)


def _case_status(case: ET.Element) -> str:
    children = {_tag(child) for child in case}
    if "error" in children:
        return "error"
    if "failure" in children:
        return "failure"
    if "skipped" in children:
        return "skipped"
    return "passed"


def _safe_time(value: object) -> str:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return "0"
    return str(parsed) if math.isfinite(parsed) and parsed >= 0 else "0"


def _case_identity(case: ET.Element) -> str:
    classname = _safe_text(case.attrib.get("classname", "unknown")) or "unknown"
    name = _safe_text(case.attrib.get("name", "unknown")) or "unknown"
    return f"{classname}::{name}"


def _write_fallback(junit_path: Path, summary_path: Path, reason: str) -> None:
    root = ET.Element(
        "testsuite",
        {
            "name": "marketos-pytest",
            "tests": "0",
            "failures": "0",
            "errors": "0",
            "skipped": "0",
        },
    )
    ET.SubElement(root, "properties").append(
        ET.Element("property", {"name": "diagnostics_status", "value": "unavailable"})
    )
    _write_xml(junit_path, root)
    _write_summary(summary_path, [
        "## Required pytest diagnostics",
        "status=unavailable",
        f"reason={reason}",
        "No raw pytest output is published.",
    ])


def _write_xml(path: Path, root: ET.Element) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    try:
        ET.indent(tree, space="  ")
    except AttributeError:  # pragma: no cover - Python 3.12 always has indent.
        pass
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _write_summary(path: Path, lines: Iterable[str]) -> None:
    text = "\n".join(lines).strip() + "\n"
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_SUMMARY_BYTES:
        encoded = encoded[: MAX_SUMMARY_BYTES - 1] + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)


def build_diagnostics(input_path: Path, junit_path: Path, summary_path: Path) -> str:
    """Project a raw JUnit file into bounded, secret-free diagnostics."""

    try:
        if not input_path.is_file():
            _write_fallback(junit_path, summary_path, "missing_junit")
            return "missing_junit"
        with input_path.open("rb") as handle:
            raw = handle.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            _write_fallback(junit_path, summary_path, "junit_too_large")
            return "junit_too_large"
        if b"<!DOCTYPE" in raw.upper():
            _write_fallback(junit_path, summary_path, "unsafe_xml_declaration")
            return "unsafe_xml_declaration"
        root = ET.fromstring(raw)
        if _tag(root) not in {"testsuite", "testsuites"}:
            _write_fallback(junit_path, summary_path, "malformed_junit")
            return "malformed_junit"
    except (OSError, ET.ParseError, UnicodeError, RecursionError):
        _write_fallback(junit_path, summary_path, "malformed_junit")
        return "malformed_junit"

    cases = [element for element in root.iter() if _tag(element) == "testcase"]
    statuses = [_case_status(case) for case in cases]
    counts = {
        "tests": _count(root, "tests", len(cases)),
        "failures": max(_count(root, "failures", statuses.count("failure")), statuses.count("failure")),
        "errors": max(_count(root, "errors", statuses.count("error")), statuses.count("error")),
        "skipped": max(_count(root, "skipped", statuses.count("skipped")), statuses.count("skipped")),
    }

    safe_root = ET.Element(
        "testsuite",
        {
            "name": "marketos-pytest",
            **{key: str(value) for key, value in counts.items()},
        },
    )
    diagnostic_cases = 0
    identities: list[str] = []
    for case, status in zip(cases, statuses):
        if status == "passed" or diagnostic_cases >= MAX_CASES:
            continue
        safe_case = ET.SubElement(
            safe_root,
            "testcase",
            {
                "classname": _safe_text(case.attrib.get("classname", "unknown")) or "unknown",
                "name": _safe_text(case.attrib.get("name", "unknown")) or "unknown",
                "time": _safe_time(case.attrib.get("time", "0")),
            },
        )
        ET.SubElement(safe_case, status, {"type": status, "message": "redacted"})
        diagnostic_cases += 1
        if status in {"failure", "error"}:
            identities.append(_case_identity(case))

    _write_xml(junit_path, safe_root)
    lines = [
        "## Required pytest diagnostics",
        "status=ready",
        *(f"{key}={value}" for key, value in counts.items()),
        f"diagnostic_cases_emitted={diagnostic_cases}",
    ]
    if identities:
        lines.append("failure_or_error_identities:")
        lines.extend(f"- {identity}" for identity in identities[:MAX_CASES])
    else:
        lines.append("failure_or_error_identities=none")
    lines.append("Raw pytest output is not published.")
    _write_summary(summary_path, lines)
    return "ready"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--junitxml", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    args = parser.parse_args(argv)
    build_diagnostics(args.input, args.junitxml, args.summary)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by CI workflow.
    raise SystemExit(main())
