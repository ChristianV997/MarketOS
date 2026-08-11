"""Produce a local, deterministic PR safety/readiness report without GitHub I/O."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

try:
    from .operating_layer import ROOT, changed_from_git, staged_from_git, docs_only, normal_paths, render_json_or_markdown, write_optional_output
    from .select_tests import select
except ImportError:  # pragma: no cover - direct script execution
    from operating_layer import ROOT, changed_from_git, staged_from_git, docs_only, normal_paths, render_json_or_markdown, write_optional_output
    from select_tests import select


SECRET_VALUE = re.compile(r"(?:CJ_API_KEY|CJ_EMAIL|SUPABASE_SERVICE_ROLE_KEY|(?:api[_-]?key|token|secret|password))\s*[=:]\s*['\"]?[^\s'\"]{6,}", re.I)
MUTATION = re.compile(r"(?:create[_ ]order|capture[_ ]payment|refund|fulfill|mutate[_ ]inventory|shopify.*(?:create|update|publish)|send[_ ]customer)", re.I)


def _diff_text(path: str | None, *, staged: bool = False) -> str:
    if path: return Path(path).read_text(encoding="utf-8")
    command = ["git", "-C", str(ROOT), "diff", "--cached"] if staged else ["git", "-C", str(ROOT), "diff", "HEAD"]
    completed = subprocess.run(command, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    return completed.stdout or ""


def report(paths: list[str], diff: str, *, branch: str, metadata: dict[str, Any] | None = None, mutation_diff: str | None = None) -> dict[str, Any]:
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
    return {
        "branch": branch, "changed_files": paths, "changed_file_count": len(paths), "risk_category": risk,
        "detections": flags, "docs_touched": any(path.startswith("docs/") for path in paths),
        "tests_touched": any(path.startswith("tests/") for path in paths), "recommended_test_set": tests["recommended_commands"],
        "merge_readiness": "clear" if not paths else "blocked" if risk == "blocked" else "needs_tests" if not any(path.startswith("tests/") for path in paths) and not docs_only(paths) else "ready_for_review",
        "blocking_warnings": warnings, "final_report_checklist": ["scope and safety boundary", "tests and exact results", "unrun checks", "rollback", "no external mutation confirmation"],
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
