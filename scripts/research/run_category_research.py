"""CLI entrypoint for a bounded, research-only category run."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.product_research.run import ResearchRunConfig, run_category_research


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("category")
    parser.add_argument("--max-products", type=int, default=20)
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    os.environ["MARKETOS_RESEARCH_ONLY"] = "true"
    dossier = run_category_research(ResearchRunConfig(args.category, args.max_products, force_refresh=args.force_refresh))
    payload = dossier.to_dict()
    print(json.dumps(payload, indent=2, default=str) if args.json else f"{dossier.category}: {len(dossier.products)} candidates; tipping={dossier.tipping_point.get('score', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
