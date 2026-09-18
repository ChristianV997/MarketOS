"""scripts/coderos_snapshot.py -- bounded read-only snapshot utility for CoderOS.

Safely captures CoderOS capability state and repository metadata for MarketOS
planning purposes without creating runtime dependencies or mutating CoderOS.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

# Ensure repository root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from backend.adapters import coderos_readonly as adapter
except ImportError:
    adapter = None


def capture_snapshot(repo_path: str, mode: str = "plan_only") -> Dict[str, Any]:
    """Capture a safe, bounded snapshot of CoderOS metadata."""
    path = Path(repo_path).resolve()
    if not path.exists():
        return {
            "status": "error",
            "error": f"Repository path does not exist: {repo_path}",
            "mode": mode,
        }

    # Extract git commit if git repository
    head_sha = "unknown"
    git_dir = path / ".git"
    if git_dir.exists():
        try:
            res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(path),
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if res.returncode == 0:
                head_sha = res.stdout.strip()
        except Exception:
            pass

    # Inspect high-level directory manifest (read-only, whitelist)
    known_subsystems = []
    for item in ("docs", "projects", "repo_dev_runtime", "scripts", "templates", "tests", ".agents"):
        if (path / item).exists():
            known_subsystems.append(item)

    # Document skills and workflows if .agents exists
    skills_count = 0
    workflows_count = 0
    agents_dir = path / ".agents"
    if agents_dir.exists():
        skills_dir = agents_dir / "skills"
        if skills_dir.exists():
            skills_count = len([p for p in skills_dir.iterdir() if p.is_dir()])
        wf_dir = agents_dir / "workflows"
        if wf_dir.exists():
            workflows_count = len([p for p in wf_dir.iterdir() if p.is_file()])

    # Bounded capability check via adapter if available
    adapter_report = None
    if adapter is not None:
        try:
            cfg = adapter.CoderOSAdapterConfig(
                coderos_root=str(path),
                mode=mode,
            )
            rep = adapter.probe(cfg)
            adapter_report = {
                "adapter_version": rep.adapter_version,
                "contract_version": rep.contract_version,
                "probe_state": rep.probe_result.state,
                "mode": cfg.mode,
                "planned_action": rep.planned_action.to_dict(),
                "safety_summary": rep.safety_summary.to_dict(),
            }
        except Exception as e:
            adapter_report = {"error": str(e)}

    snapshot = {
        "status": "success",
        "target_repo": str(path),
        "head_sha": head_sha,
        "mode": mode,
        "subsystems": sorted(known_subsystems),
        "declared_skills_count": skills_count,
        "declared_workflows_count": workflows_count,
        "adapter_report": adapter_report,
        "evidence_class": "simulated_readonly_snapshot",
        "safety": {
            "mutations_allowed": False,
            "network_used": False,
            "credentials_read": False,
        },
    }
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture bounded CoderOS snapshot.")
    parser.add_argument("--repo", required=True, help="Path to CoderOS repository.")
    parser.add_argument("--mode", choices=["plan_only", "probe"], default="plan_only", help="Execution mode.")
    parser.add_argument("--json", action="store_true", help="Output JSON directly.")
    parser.add_argument("--output", help="Optional output file path.")
    args = parser.parse_args()

    snapshot = capture_snapshot(args.repo, mode=args.mode)
    output_str = json.dumps(snapshot, indent=2)

    if args.output:
        out_p = Path(args.output).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(output_str, encoding="utf-8")
        print(f"Snapshot written to {out_p}")
    else:
        print(output_str)

    return 0 if snapshot.get("status") == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
