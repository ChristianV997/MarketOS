"""Validate MarketOS's OSS adoption inventory without downloading code."""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
INVENTORY = ROOT / "docs" / "oss" / "INVENTORY.yml"
REQUIRED = {"name", "repository", "license", "mode", "status", "owner", "capabilities", "reviewed_ref"}
FORBIDDEN_VENDOR_MODES = {"vendored", "monorepo_copy"}


def validate_inventory(path: Path = INVENTORY) -> list[str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    errors: list[str] = []
    if data.get("commercial_distribution") is not True:
        errors.append("commercial_distribution must be true")
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ["candidates must be a non-empty list"]
    names: set[str] = set()
    for index, candidate in enumerate(candidates):
        missing = REQUIRED - set(candidate)
        if missing:
            errors.append(f"candidate {index} missing: {sorted(missing)}")
        name = candidate.get("name")
        if name in names:
            errors.append(f"duplicate candidate: {name}")
        names.add(name)
        if candidate.get("mode") in FORBIDDEN_VENDOR_MODES:
            errors.append(f"{name}: source copying is forbidden for this inventory")
        if not str(candidate.get("repository", "")).startswith("https://github.com/"):
            errors.append(f"{name}: repository must be an HTTPS GitHub URL")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, default=INVENTORY)
    args = parser.parse_args()
    errors = validate_inventory(args.inventory)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"OSS inventory valid: {args.inventory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
