"""Compare two bounded JUnit XML reports without running tests or contacting services.

The comparator is an evidence tool, not a readiness gate. A complete comparison
can contain failures; an incomplete comparison is never represented as a pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any


SCHEMA = "MarketOS.JUnitDifferential.v1"
MAX_REPORT_BYTES = 2 * 1024 * 1024
MAX_TESTCASES = 50_000
MAX_OUTPUT_ITEMS = 10_000
MAX_FIELD_LENGTH = 512
EXIT_COMPLETE = 0
EXIT_INCOMPLETE = 2

OUTCOME_FAILURE = "failure"
OUTCOME_ERROR = "error"
OUTCOME_SKIPPED = "skipped"
OUTCOME_PASSED = "passed"
FAILURE_OUTCOMES = {OUTCOME_FAILURE, OUTCOME_ERROR}

_IDENTITY_ATTRIBUTES = ("file", "package", "classname", "name", "id", "line")
_COUNT_ATTRIBUTES = ("tests", "failures", "errors", "skipped")


def _tag(element: ET.Element) -> str:
    """Return a namespace-independent XML tag name."""
    return element.tag.rsplit("}", 1)[-1] if isinstance(element.tag, str) else ""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _read_bounded(path: Path) -> tuple[bytes | None, str | None]:
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_REPORT_BYTES + 1)
    except FileNotFoundError:
        return None, "missing_report"
    except IsADirectoryError:
        return None, "report_not_a_file"
    except OSError:
        return None, "report_unreadable"
    if len(data) > MAX_REPORT_BYTES:
        return None, "report_too_large"
    if not data:
        return None, "report_empty"
    return data, None


def _attribute_values(element: ET.Element) -> tuple[dict[str, str], list[str]]:
    values: dict[str, str] = {}
    issues: list[str] = []
    for name in _IDENTITY_ATTRIBUTES:
        raw = element.attrib.get(name)
        if raw is None:
            continue
        value = str(raw).strip()
        if len(value) > MAX_FIELD_LENGTH:
            issues.append("testcase_field_too_long")
            continue
        values[name] = value
    return values, issues


def _outcome(element: ET.Element) -> tuple[str, str | None]:
    children = {_tag(child) for child in element}
    if "error" in children:
        return OUTCOME_ERROR, "error"
    if "failure" in children:
        return OUTCOME_FAILURE, "failure"
    if "skipped" in children:
        return OUTCOME_SKIPPED, None
    return OUTCOME_PASSED, None


def _node_identity(attributes: dict[str, str], ordinal: int) -> dict[str, str | int]:
    identity = {name: attributes[name] for name in _IDENTITY_ATTRIBUTES if attributes.get(name)}
    if not identity:
        # The report is marked incomplete, but retaining an ordinal keeps the
        # diagnostic bounded and makes its case count visible to the caller.
        return {"ordinal": ordinal}
    return identity


def _load_report(path: Path, role: str) -> dict[str, Any]:
    data, read_error = _read_bounded(path)
    if read_error:
        return {
            "role": role,
            "status": "incomplete",
            "issue_codes": [read_error],
            "test_count": 0,
            "counts": {},
            "cases": [],
        }

    assert data is not None
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        return {
            "role": role,
            "status": "incomplete",
            "issue_codes": ["unsafe_xml_declaration"],
            "test_count": 0,
            "counts": {},
            "cases": [],
        }
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, UnicodeDecodeError):
        return {
            "role": role,
            "status": "incomplete",
            "issue_codes": ["malformed_xml"],
            "test_count": 0,
            "counts": {},
            "cases": [],
        }

    if _tag(root) not in {"testsuite", "testsuites"}:
        return {
            "role": role,
            "status": "incomplete",
            "issue_codes": ["invalid_junit_root"],
            "test_count": 0,
            "counts": {},
            "cases": [],
        }

    elements = [element for element in root.iter() if _tag(element) == "testcase"]
    issues: set[str] = set()
    if len(elements) > MAX_TESTCASES:
        issues.add("too_many_testcases")
        elements = []
    raw_cases: list[dict[str, Any]] = []
    for ordinal, element in enumerate(elements, start=1):
        attributes, attribute_issues = _attribute_values(element)
        issues.update(attribute_issues)
        if not attributes.get("name") and not attributes.get("id") and not attributes.get("classname"):
            issues.add("missing_testcase_identity")
        outcome, detail = _outcome(element)
        identity = _node_identity(attributes, ordinal)
        raw_cases.append({
            "identity": identity,
            "outcome": outcome,
            "detail": detail,
            "ordinal": ordinal,
        })

    if not raw_cases:
        issues.add("no_testcases")

    declared: dict[str, int] = {}
    for name in _COUNT_ATTRIBUTES:
        raw_value = root.attrib.get(name)
        if raw_value is None:
            continue
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            issues.add("invalid_declared_count")
            continue
        if value < 0:
            issues.add("invalid_declared_count")
            continue
        declared[name] = value

    counts = Counter(case["outcome"] for case in raw_cases)
    observed_counts = {
        "tests": len(raw_cases),
        "failures": counts[OUTCOME_FAILURE],
        "errors": counts[OUTCOME_ERROR],
        "skipped": counts[OUTCOME_SKIPPED],
    }
    if declared and any(declared[name] != observed_counts[name] for name in declared):
        issues.add("declared_count_mismatch")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for case in raw_cases:
        identity_key = _canonical_json(case["identity"])
        grouped.setdefault(identity_key, []).append(case)
    cases: list[dict[str, Any]] = []
    for identity_key in sorted(grouped):
        duplicate_cases = sorted(
            grouped[identity_key],
            key=lambda case: (case["outcome"], case["detail"] or "", case["ordinal"]),
        )
        identity = json.loads(identity_key)
        for index, case in enumerate(duplicate_cases, start=1):
            node_key = identity_key if len(duplicate_cases) == 1 else f"{identity_key}#duplicate-{index}"
            cases.append({
                "node_key": node_key,
                "outcome": case["outcome"],
                "detail": case["detail"],
                "identity": identity,
            })

    cases.sort(key=lambda case: case["node_key"])
    return {
        "role": role,
        "status": "complete" if not issues else "incomplete",
        "issue_codes": sorted(issues),
        "test_count": len(cases),
        "counts": dict(sorted(observed_counts.items())),
        "declared_counts": dict(sorted(declared.items())),
        "cases": cases,
    }


def _report_summary(report: dict[str, Any]) -> dict[str, Any]:
    result = {
        "role": report["role"],
        "status": report["status"],
        "issue_codes": report["issue_codes"],
        "test_count": report["test_count"],
        "counts": report["counts"],
    }
    if report.get("declared_counts"):
        result["declared_counts"] = report["declared_counts"]
    return result


def _case_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {case["node_key"]: case for case in report["cases"]}


def _compare_complete(base: dict[str, Any], candidate: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    base_cases = _case_map(base)
    candidate_cases = _case_map(candidate)
    all_keys = sorted(set(base_cases) | set(candidate_cases))
    buckets: dict[str, list[str]] = {
        "candidate_only_failures": [],
        "shared_failures": [],
        "base_only_failures": [],
        "candidate_skips": [],
        "base_skips": [],
        "shared_skips": [],
        "candidate_missing": [],
        "base_missing": [],
        "unchanged": [],
    }
    outcome_changes: list[dict[str, str]] = []
    for node_key in all_keys:
        base_case = base_cases.get(node_key)
        candidate_case = candidate_cases.get(node_key)
        base_outcome = base_case["outcome"] if base_case else "missing"
        candidate_outcome = candidate_case["outcome"] if candidate_case else "missing"
        if candidate_outcome in FAILURE_OUTCOMES and base_outcome not in FAILURE_OUTCOMES:
            buckets["candidate_only_failures"].append(node_key)
        if candidate_outcome in FAILURE_OUTCOMES and base_outcome in FAILURE_OUTCOMES:
            buckets["shared_failures"].append(node_key)
        if base_outcome in FAILURE_OUTCOMES and candidate_outcome not in FAILURE_OUTCOMES:
            buckets["base_only_failures"].append(node_key)
        if candidate_outcome == OUTCOME_SKIPPED:
            buckets["candidate_skips"].append(node_key)
        if base_outcome == OUTCOME_SKIPPED:
            buckets["base_skips"].append(node_key)
        if base_outcome == OUTCOME_SKIPPED and candidate_outcome == OUTCOME_SKIPPED:
            buckets["shared_skips"].append(node_key)
        if candidate_case is None:
            buckets["candidate_missing"].append(node_key)
        if base_case is None:
            buckets["base_missing"].append(node_key)
        if base_outcome == candidate_outcome and base_outcome == OUTCOME_PASSED:
            buckets["unchanged"].append(node_key)
        if base_outcome != candidate_outcome:
            outcome_changes.append({"node_key": node_key, "base": base_outcome, "candidate": candidate_outcome})

    if any(len(values) > MAX_OUTPUT_ITEMS for values in buckets.values()) or len(outcome_changes) > MAX_OUTPUT_ITEMS:
        return None, "comparison_output_limit_exceeded"
    return {
        "candidate_only_failures": buckets["candidate_only_failures"],
        "shared_failures": buckets["shared_failures"],
        "base_only_failures": buckets["base_only_failures"],
        "candidate_skips": buckets["candidate_skips"],
        "base_skips": buckets["base_skips"],
        "shared_skips": buckets["shared_skips"],
        "candidate_missing": buckets["candidate_missing"],
        "base_missing": buckets["base_missing"],
        "unchanged": buckets["unchanged"],
        "outcome_changes": outcome_changes,
        "node_count": len(all_keys),
    }, None


def compare(base_path: Path, candidate_path: Path) -> dict[str, Any]:
    base = _load_report(base_path, "base")
    candidate = _load_report(candidate_path, "candidate")
    errors = [
        {"role": report["role"], "code": code}
        for report in (base, candidate)
        for code in report["issue_codes"]
    ]
    errors.sort(key=lambda item: (item["role"], item["code"]))
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "incomplete",
        "reports": {
            "base": _report_summary(base),
            "candidate": _report_summary(candidate),
        },
        "comparison": None,
        "errors": errors,
        "limits": {
            "max_report_bytes": MAX_REPORT_BYTES,
            "max_testcases": MAX_TESTCASES,
            "max_output_items": MAX_OUTPUT_ITEMS,
        },
    }
    if base["status"] != "complete" or candidate["status"] != "complete":
        result["fingerprint"] = _fingerprint({"reports": result["reports"], "errors": errors})
        return result
    comparison, comparison_error = _compare_complete(base, candidate)
    if comparison_error:
        result["errors"].append({"role": "comparison", "code": comparison_error})
        result["errors"].sort(key=lambda item: (item["role"], item["code"]))
        result["fingerprint"] = _fingerprint({"reports": result["reports"], "errors": result["errors"]})
        return result
    result["status"] = "complete"
    result["comparison"] = comparison
    result["fingerprint"] = _fingerprint({"reports": result["reports"], "comparison": comparison})
    return result


def render_text(result: dict[str, Any]) -> str:
    lines = [
        f"schema: {result['schema']}",
        f"status: {result['status']}",
        f"base: {result['reports']['base']['status']} ({result['reports']['base']['test_count']} tests)",
        f"candidate: {result['reports']['candidate']['status']} ({result['reports']['candidate']['test_count']} tests)",
    ]
    comparison = result.get("comparison")
    if comparison:
        for name in (
            "candidate_only_failures",
            "shared_failures",
            "base_only_failures",
            "candidate_skips",
            "base_skips",
            "shared_skips",
            "candidate_missing",
            "base_missing",
            "outcome_changes",
        ):
            values = comparison[name]
            lines.append(f"{name}: {len(values)}")
            if name == "outcome_changes":
                lines.extend(
                    f"- {value['node_key']}: {value['base']} -> {value['candidate']}"
                    for value in values
                )
            else:
                lines.extend(f"- {value}" for value in values)
    if result["errors"]:
        lines.append("errors:")
        lines.extend(f"- {item['role']}: {item['code']}" for item in result["errors"])
    lines.append(f"fingerprint: {result['fingerprint']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True, help="caller-supplied base JUnit XML report")
    parser.add_argument("--candidate", type=Path, required=True, help="caller-supplied candidate JUnit XML report")
    parser.add_argument("--json", action="store_true", help="render deterministic JSON instead of text")
    args = parser.parse_args(argv)
    result = compare(args.base, args.candidate)
    if args.json:
        output = _canonical_json(result) + "\n"
    else:
        output = render_text(result)
    sys.stdout.write(output)
    return EXIT_COMPLETE if result["status"] == "complete" else EXIT_INCOMPLETE


if __name__ == "__main__":
    raise SystemExit(main())
