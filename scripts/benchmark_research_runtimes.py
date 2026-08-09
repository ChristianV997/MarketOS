"""Explicit, non-persisting Hermes versus DeerFlow benchmark.

The command never enables feature flags itself. With the default environment it
returns skipped results; callers must enable each runtime and the Agent-Reach
sensor explicitly before any external request can occur.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.research import SwarmJobSpec, benchmark_runtimes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--objective", required=True)
    parser.add_argument("--allow-domain", action="append", default=[])
    parser.add_argument("--live", action="store_true", help="Require an allowlist and permit live sidecars when flags are enabled")
    args = parser.parse_args()
    spec = SwarmJobSpec.create(
        query=args.query,
        objective=args.objective,
        runtime="hermes",
        sources=("agent_reach",),
        allowed_domains=tuple(args.allow_domain),
        dry_run=not args.live,
    )
    print(json.dumps(benchmark_runtimes(spec), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
