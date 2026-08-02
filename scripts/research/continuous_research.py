"""Single-writer continuous research scheduler."""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.research.lease import ResearchLease
from services.product_research.run import ResearchRunConfig, run_category_research


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("category")
    parser.add_argument("--interval-seconds", type=float, default=21_600)
    parser.add_argument("--max-products", type=int, default=20)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    os.environ["MARKETOS_RESEARCH_ONLY"] = "true"
    lease = ResearchLease()
    if not lease.acquire():
        print("research lease is held by another worker")
        return 2
    try:
        while True:
            run_category_research(ResearchRunConfig(args.category, args.max_products))
            if args.once:
                return 0
            lease.heartbeat()
            time.sleep(max(60.0, args.interval_seconds))
    finally:
        lease.release()


if __name__ == "__main__":
    raise SystemExit(main())
