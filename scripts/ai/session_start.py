"""Read-only preflight for synchronized Codex/Claude sessions."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path


OWNERSHIP = {
    "claude": ("docs/archive/", ".github/workflows/codeql.yml", "docs/CRM_CANDIDATE_RESEARCH.md", "services/sales_automation/"),
    "codex": ("scripts/ai/", "docs/ai/PARALLEL_WORK_MATRIX.md", "scripts/benchmark_inference_stack.py", "tests/test_inference_stack_benchmark.py", ".github/workflows/performance-regression.yml"),
    "shared": ("docs/ai/SESSION_HANDOFF.md", "AGENTS.md", "CLAUDE.md"),
}


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    return result.stdout.strip()


def changed_paths(root: Path) -> list[str]:
    result = subprocess.run(["git", "-C", str(root), "status", "--short"], capture_output=True, text=True, check=False)
    paths: list[str] = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path)
    return paths


def owner_for(path: str) -> str | None:
    normalized = path.replace("\\", "/")
    for owner, prefixes in OWNERSHIP.items():
        if any(normalized == prefix or normalized.startswith(prefix) for prefix in prefixes):
            return owner
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--fetch", action="store_true", help="fetch origin before the read-only report")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = args.repository.resolve()
    if args.fetch:
        subprocess.run(["git", "-C", str(root), "fetch", "origin"], check=False)
    branch = git(root, "branch", "--show-current") or "detached"
    upstream = f"origin/{branch}"
    changed = changed_paths(root)
    conflicts = [{"path": path, "owner": owner_for(path)} for path in changed if owner_for(path)]
    report = {
        "repository": str(root),
        "branch": branch,
        "head": git(root, "rev-parse", "HEAD"),
        "upstream": upstream,
        "upstream_exists": bool(git(root, "rev-parse", "--verify", upstream)),
        "changed_paths": changed,
        "owned_path_changes": conflicts,
        "tools": {name: bool(shutil.which(name)) for name in ("python", "git", "uv", "semgrep", "repomix", "ollama")},
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Repository: {report['repository']}\nBranch: {branch}\nHEAD: {report['head']}")
        print(f"Changed paths: {len(changed)}")
        for item in conflicts:
            print(f"OWNERSHIP REVIEW: {item['path']} ({item['owner']})")
        print("Tools:", ", ".join(name for name, present in report["tools"].items() if present))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
