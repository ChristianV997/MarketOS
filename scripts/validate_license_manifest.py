"""Ensure third-party license records remain aligned with the OSS inventory."""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

try:
    from scripts.validate_oss_inventory import INVENTORY, validate_inventory
except ModuleNotFoundError:  # direct ``python scripts/...`` invocation
    from validate_oss_inventory import INVENTORY, validate_inventory


ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "docs" / "oss" / "LICENSE_MANIFEST.yml"
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
REQUIRED = {"name", "license", "reviewed_ref", "distribution", "notice"}


def validate_manifest(manifest: Path = MANIFEST, inventory: Path = INVENTORY, notices: Path = NOTICES) -> list[str]:
    errors = validate_inventory(inventory)
    data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    components = data.get("components", [])
    if not isinstance(components, list):
        return errors + ["license manifest components must be a list"]
    records: dict[str, dict] = {}
    for index, item in enumerate(components):
        if not isinstance(item, dict):
            errors.append(f"license component {index} must be a mapping")
            continue
        missing = REQUIRED - set(item)
        if missing:
            errors.append(f"license component {index} missing: {sorted(missing)}")
        name = str(item.get("name", ""))
        if name in records:
            errors.append(f"duplicate license component: {name}")
        records[name] = item
    inventory_records = yaml.safe_load(inventory.read_text(encoding="utf-8")) or {}
    for candidate in inventory_records.get("candidates", []):
        name = candidate.get("name")
        record = records.get(name)
        if record is None:
            errors.append(f"inventory component missing license record: {name}")
            continue
        for field in ("license", "reviewed_ref"):
            if record.get(field) != candidate.get(field):
                errors.append(f"{name}: license manifest {field} differs from inventory")
        if record.get("distribution") != candidate.get("mode"):
            errors.append(f"{name}: license manifest distribution differs from inventory mode")
    notice_text = notices.read_text(encoding="utf-8") if notices.exists() else ""
    for name in records:
        if name not in notice_text:
            errors.append(f"THIRD_PARTY_NOTICES.md is missing {name}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--inventory", type=Path, default=INVENTORY)
    args = parser.parse_args()
    errors = validate_manifest(args.manifest, args.inventory)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"License manifest valid: {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
