"""Validate an agent batch plan before dispatch and print a sanitized JSON report.

Read-only: never dispatches agents, reads credentials, or calls a host.
Exit 0 when the plan is valid. Exit 2 when it is invalid, unreadable, or the
policy cannot be loaded. The report never echoes the input path or raw values.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.ai import agent_batch_plan as plan  # noqa: E402


def _emit(report: dict[str, Any]) -> int:
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["valid"] else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="agent batch plan JSON to validate")
    parser.add_argument(
        "--policy",
        type=Path,
        default=plan.POLICY_PATH,
        help="roster policy JSON (default: scripts/ai/agent_batch_policy.json)",
    )
    args = parser.parse_args(argv)
    try:
        policy = plan.load_policy(args.policy)
    except plan.PlanError as exc:
        return _emit(plan.failure_report(exc.code, "policy"))
    try:
        # Only a regular file is read, so a FIFO or directory cannot block or mislead the check.
        if not stat.S_ISREG(os.stat(args.manifest).st_mode):
            raise OSError("not a regular file")
        with args.manifest.open("rb") as handle:
            raw = handle.read(plan.MAX_MANIFEST_BYTES + 1)
    except OSError:
        return _emit(plan.failure_report("manifest_unreadable", "", policy["policy_id"]))
    return _emit(plan.validate_plan_bytes(raw, policy))


if __name__ == "__main__":
    raise SystemExit(main())
