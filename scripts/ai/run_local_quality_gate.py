"""Run deterministic, local-only MarketOS agentic quality gates in one command."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

try:
    from . import ci_matrix_plan, impact_planner, phase_gate, pr_readiness_report, select_tests
    from .operating_layer import ROOT, changed_from_git, normal_paths, render_json_or_markdown, write_optional_output
    from evaluation.commerce.readiness import build_phase1_readiness
except ImportError:  # pragma: no cover - direct script execution
    import ci_matrix_plan, impact_planner, phase_gate, pr_readiness_report, select_tests
    from operating_layer import ROOT, changed_from_git, normal_paths, render_json_or_markdown, write_optional_output
    from evaluation.commerce.readiness import build_phase1_readiness


def _diff_text(path: str | None) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    completed = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "HEAD"],
        text=True, encoding="utf-8", errors="replace", capture_output=True, check=False,
    )
    return completed.stdout or ""


def _implementation_diff(paths: list[str], diff_text: str) -> str:
    """Keep mutation phrase checks out of prose/test diffs, not secret scans."""
    allowed = {path for path in paths if not path.startswith(("docs/", "tests/")) and path not in {"AGENTS.md", "CLAUDE.md", "README.md"}}
    if not allowed:
        return ""
    if "diff --git " not in diff_text:
        return diff_text
    chunks = diff_text.split("diff --git ")
    kept = [chunks[0]]
    for chunk in chunks[1:]:
        header = chunk.splitlines()[0] if chunk.splitlines() else ""
        path = header.split(" b/")[-1] if " b/" in header else ""
        if path in allowed:
            kept.append("diff --git " + chunk)
    return "".join(kept)


def run(paths: list[str], *, diff_text: str = "", branch: str = "local") -> dict[str, Any]:
    """Compose existing planning functions; no network, writes, or subprocess tests."""
    paths = normal_paths(paths)
    implementation_diff = _implementation_diff(paths, diff_text)
    readiness = pr_readiness_report.report(paths, diff_text, branch=branch, mutation_diff=implementation_diff)
    phase = phase_gate.check(paths, implementation_diff)
    selected = select_tests.select(paths)
    ci_plan = ci_matrix_plan.plan(paths)
    phase1_readiness = build_phase1_readiness().to_dict()
    impact = impact_planner.plan(impact_planner.DEFAULT_BACKLOG, phase1_readiness)
    blocked = phase["status"] == "blocked" or readiness["risk_category"] == "blocked"
    status = "blocked" if blocked else "clear" if not paths else "advisory"
    flags = readiness["detections"]
    next_action = (
        "remove credentials, generated artifacts, or blocked mutation work before continuing"
        if blocked else "no changed files; choose one unblocked task from the impact backlog"
        if not paths else "run the recommended focused tests, then session_finish and PR readiness before opening a PR"
    )
    return {
        "status": status, "changed_files": paths, "risk_level": readiness["risk_category"],
        "phase_gate_status": phase["status"], "phase_gate_blockers": phase["blockers"],
        "secret_or_artifact_flags": {key: flags[key] for key in ("artifacts_detected", "credential_file_detected", "secret_value_like_detected")},
        "mutation_flags": {"provider_mutation_like_detected": flags["provider_mutation_like_detected"]},
        "recommended_tests": selected["recommended_commands"], "recommended_ci_lanes": ci_plan["recommended_lanes"],
        "pr_merge_readiness": readiness["merge_readiness"],
        "impact_top_task": impact["ranked_backlog"][0]["task"], "recommended_next_action": next_action,
        "phase1_readiness": {"overall_status": phase1_readiness["overall_status"], "overall_score": phase1_readiness["overall_score"], "next_best_action": phase1_readiness["next_best_action"], "blocking_gates": phase1_readiness["blocking_gates"]},
        "network_calls": False, "mutated": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-git", action="store_true", help="include changed/untracked paths from local git state")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--diff-file", help="synthetic or saved diff content for deterministic review")
    parser.add_argument("--branch", default="local")
    parser.add_argument("--json", action="store_true"); parser.add_argument("--markdown", action="store_true"); parser.add_argument("--output")
    args = parser.parse_args(argv)
    if args.json and args.markdown: parser.error("choose --json or --markdown")
    paths = list(args.changed_file) + (changed_from_git() if args.from_git else [])
    report = run(paths, diff_text=_diff_text(args.diff_file), branch=args.branch)
    content = render_json_or_markdown(report, markdown=args.markdown, title="MarketOS local quality gate")
    write_optional_output(content, args.output); print(content, end="")
    return 0


if __name__ == "__main__": raise SystemExit(main())
