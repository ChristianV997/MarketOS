"""Enforce MarketOS's commercial OSS integration policy."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from scripts.validate_oss_inventory import INVENTORY, validate_inventory
except ModuleNotFoundError:
    from validate_oss_inventory import INVENTORY, validate_inventory

RESTRICTED = {"AGPL-3.0", "GPL-3.0", "Sustainable-Use"}
REVIEW_STATUSES = {"deferred", "review_required", "legal_review_required", "internal_only"}


def check_policy(path: Path = INVENTORY) -> list[str]:
    errors = validate_inventory(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for candidate in data.get("candidates", []):
        name = candidate.get("name", "unknown")
        license_name = candidate.get("license", "")
        mode = candidate.get("mode", "")
        status = candidate.get("status", "")
        if mode in {"vendored", "monorepo_copy"}:
            errors.append(f"{name}: source copying is forbidden")
        if license_name in RESTRICTED and status not in REVIEW_STATUSES:
            errors.append(f"{name}: restricted license requires legal/deployment review")
        if license_name in RESTRICTED and mode in {"optional_library", "commercial_core"}:
            errors.append(f"{name}: restricted license cannot enter the commercial core")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, default=INVENTORY)
    args = parser.parse_args()
    errors = check_policy(args.inventory)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"OSS policy valid: {args.inventory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
