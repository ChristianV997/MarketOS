"""Produce a local, deterministic PR safety/readiness report without GitHub I/O."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping

try:
    from .operating_layer import ROOT, changed_from_git, staged_from_git, docs_only, normal_paths, render_json_or_markdown, write_optional_output
    from .select_tests import select
except ImportError:  # pragma: no cover - direct script execution
    from operating_layer import ROOT, changed_from_git, staged_from_git, docs_only, normal_paths, render_json_or_markdown, write_optional_output
    from select_tests import select


SECRET_VALUE = re.compile(r"(?:CJ_API_KEY|CJ_EMAIL|SUPABASE_SERVICE_ROLE_KEY|(?:api[_-]?key|token|secret|password))\s*[=:]\s*['\"]?[^\s'\"]{6,}", re.I)
MUTATION = re.compile(r"(?:create[_ ]order|capture[_ ]payment|refund(?:[_ ](?:payment|order|transaction|customer)|\s*\()|fulfill|mutate[_ ]inventory|shopify.*(?:create|update|publish)|send[_ ]customer)", re.I)
QUALITY_GATE_FAILURE_STATUSES = {"failed", "timed_out", "collection_failed", "blocked", "configuration_error"}


def _quality_gate_failures(quality_gate: Mapping[str, Any]) -> list[str]:
    failures: set[str] = set()

    def visit(item: Any) -> None:
        if not isinstance(item, Mapping):
            return
        name = item.get("name")
        status = item.get("status")
        if isinstance(name, str) and status in QUALITY_GATE_FAILURE_STATUSES and item.get("execution_status") in {"executed", "timed_out"}:
            failures.add(name)
        for key in ("checks", "subchecks"):
            children = item.get(key, [])
            if isinstance(children, list):
                for child in children:
                    visit(child)
            elif isinstance(children, Mapping):
                for child_name, child in children.items():
                    if isinstance(child, Mapping) and "name" not in child:
                        child = dict(child)
                        child["name"] = child_name
                    visit(child)

    for item in quality_gate.get("checks", []):
        visit(item)
    ci = quality_gate.get("ci")
    if isinstance(ci, Mapping):
        for job in ci.get("jobs", []):
            if not isinstance(job, Mapping) or not isinstance(job.get("name"), str):
                continue
            if job.get("status") in {"failed", "timed_out"} and isinstance(job.get("steps_executed"), int) and job["steps_executed"] > 0:
                failures.add(f"ci:{job['name']}")
    return sorted(failures)


def _baseline_delta_projection(delta: Any, quality_gate: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(delta, Mapping):
        return {"provided": False, "status": "not_run", "classification": "not_run", "controls": []}

    controls: list[dict[str, Any]] = []
    for raw in delta.get("controls", []):
        if not isinstance(raw, Mapping) or not isinstance(raw.get("name"), str):
            continue
        control = {"name": raw["name"], "classification": str(raw.get("classification", "malformed"))}
        for field in ("baseline_status", "candidate_status"):
            if field in raw and (raw[field] is None or isinstance(raw[field], str)):
                control[field] = raw[field]
        controls.append(control)
    controls.sort(key=lambda item: item["name"])

    names_by_class: dict[str, list[str]] = {}
    for control in controls:
        names_by_class.setdefault(control["classification"], []).append(control["name"])
    classifications = sorted({str(item) for item in delta.get("classifications", []) if isinstance(item, str)} or names_by_class)
    projection = {
        "provided": True,
        "status": str(delta.get("status", "malformed")),
        "classification": str(delta.get("classification", "malformed")),
        "classifications": classifications,
        "baseline_available": bool(delta.get("baseline_available", False)),
        "controls": controls,
        "fingerprint": str(delta.get("fingerprint", "")),
        "introduced_failures": sorted(names_by_class.get("introduced_failure", [])),
        "inherited_failures": sorted(names_by_class.get("inherited_failure", [])),
        "resolved_failures": sorted(names_by_class.get("resolved_failure", [])),
        "newly_available_passes": sorted(names_by_class.get("newly_available_pass", [])),
        "unavailable_in_both": sorted(names_by_class.get("unavailable_in_both", [])),
        "candidate_incomplete": sorted(names_by_class.get("candidate_incomplete", [])),
        "candidate_executed_failure": _quality_gate_failures(quality_gate),
    }
    return projection


def _quality_gate_projection(quality_gate: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(quality_gate, Mapping):
        return {"provided": False}
    status = str(quality_gate.get("status", "malformed"))
    classification = str(quality_gate.get("classification", "malformed"))
    ci = quality_gate.get("ci") if isinstance(quality_gate.get("ci"), Mapping) else {}
    ci_status = str(ci.get("status", "unavailable"))
    ci_classification = str(ci.get("classification", "ci_unavailable"))
    ci_diagnostic_state = str(ci.get("diagnostic_state", "evidence_not_queried"))
    ci_operator_action = str(ci.get("operator_action", "collect complete sanitized CI evidence before final attestation"))
    delta = _baseline_delta_projection(quality_gate.get("baseline_delta"), quality_gate)
    blocking_reasons: set[str] = set()
    if status != "passed":
        blocking_reasons.add(f"quality_gate:{status}")
    if ci_status != "passed":
        blocking_reasons.add(f"ci:{ci_classification}")
        blocking_reasons.add(f"ci_diagnostic:{ci_diagnostic_state}")
    if delta.get("status") in {"failed", "unavailable", "malformed"}:
        blocking_reasons.add(f"baseline_delta:{delta['status']}")
    executed_failures = delta.get("candidate_executed_failure", [])
    if executed_failures:
        blocking_reasons.add("candidate_executed_failure")
    if quality_gate.get("phase") == "final" and quality_gate.get("ready_for_supervised_use") is False:
        blocking_reasons.add("quality_gate_not_ready")
    return {
        "provided": True,
        "status": status,
        "classification": classification,
        "ci_status": ci_status,
        "ci_classification": ci_classification,
        "ci_diagnostic_state": ci_diagnostic_state,
        "ci_operator_action": ci_operator_action,
        "ready_for_supervised_use": quality_gate.get("ready_for_supervised_use") is True,
        "blocking": bool(blocking_reasons),
        "blocking_reasons": sorted(blocking_reasons),
        "baseline_delta": delta,
    }


def _diff_text(path: str | None, *, staged: bool = False) -> str:
    if path: return Path(path).read_text(encoding="utf-8")
    command = ["git", "-C", str(ROOT), "diff", "--cached"] if staged else ["git", "-C", str(ROOT), "diff", "HEAD"]
    completed = subprocess.run(command, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    return completed.stdout or ""


def report(
    paths: list[str],
    diff: str,
    *,
    branch: str,
    metadata: dict[str, Any] | None = None,
    mutation_diff: str | None = None,
    quality_gate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    paths = normal_paths(paths)
    implementation_paths = [path for path in paths if not path.startswith(("docs/", "tests/")) and path not in {"AGENTS.md", "CLAUDE.md", "README.md"}]
    flags = {
        "artifacts_detected": any(path.startswith("artifacts/") for path in paths),
        "credential_file_detected": any(".env" in path.lower() and not path.endswith(".example") for path in paths),
        "secret_value_like_detected": bool(SECRET_VALUE.search(diff)),
        "provider_mutation_like_detected": bool(MUTATION.search(mutation_diff if mutation_diff is not None else diff)) if implementation_paths else False,
        "raw_payload_risk": any("payload" in path.lower() and path.startswith("tests/fixtures/") is False for path in paths),
    }
    risk = "none" if not paths else "blocked" if any(flags[key] for key in ("artifacts_detected", "credential_file_detected", "secret_value_like_detected", "provider_mutation_like_detected")) else "low" if docs_only(paths) else "moderate"
    warnings = [name for name, value in flags.items() if value]
    tests = select(paths)
    quality_gate_projection = _quality_gate_projection(quality_gate)
    merge_readiness = "clear" if not paths else "blocked" if risk == "blocked" else "needs_tests" if not any(path.startswith("tests/") for path in paths) and not docs_only(paths) else "ready_for_review"
    if quality_gate_projection.get("blocking"):
        merge_readiness = "blocked"
        warnings.extend(quality_gate_projection["blocking_reasons"])
    warnings = sorted(set(warnings))
    return {
        "branch": branch, "changed_files": paths, "changed_file_count": len(paths), "risk_category": risk,
        "detections": flags, "docs_touched": any(path.startswith("docs/") for path in paths),
        "tests_touched": any(path.startswith("tests/") for path in paths), "recommended_test_set": tests["recommended_commands"],
        "merge_readiness": merge_readiness,
        "blocking_warnings": warnings, "final_report_checklist": ["scope and safety boundary", "tests and exact results", "unrun checks", "rollback", "no external mutation confirmation"],
        "quality_gate": quality_gate_projection,
        "metadata": metadata or {},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", action="append", default=[]); parser.add_argument("--from-git", action="store_true")
    parser.add_argument("--diff-file"); parser.add_argument("--staged", action="store_true", help="evaluate only the staged PR scope")
    parser.add_argument("--metadata-file"); parser.add_argument("--branch")
    parser.add_argument("--json", action="store_true"); parser.add_argument("--markdown", action="store_true"); parser.add_argument("--output")
    args = parser.parse_args(argv)
    if args.json and args.markdown: parser.error("choose --json or --markdown")
    current_branch = subprocess.run(["git", "-C", str(ROOT), "branch", "--show-current"], text=True, encoding="utf-8", errors="replace", capture_output=True).stdout or ""
    branch = args.branch or current_branch.strip()
    metadata = json.loads(Path(args.metadata_file).read_text(encoding="utf-8")) if args.metadata_file else None
    paths = list(args.path) + (staged_from_git() if args.staged else changed_from_git() if args.from_git else [])
    diff = _diff_text(args.diff_file, staged=args.staged)
    policy_labels = ("forbidden_next_phases", "supplier_mutation", "shopify_mutation", "orders_payments_or_", "MUTATION = re.compile")
    policy_safe_diff = "\n".join(line for line in diff.splitlines() if not any(label in line for label in policy_labels))
    result = report(paths, diff, branch=branch, metadata=metadata, mutation_diff=policy_safe_diff)
    content = render_json_or_markdown(result, markdown=args.markdown, title="MarketOS PR readiness")
    write_optional_output(content, args.output); print(content, end="")
    return 0


if __name__ == "__main__": raise SystemExit(main())
