"""Generate a deterministic, network-free OSS inventory/dependency manifest."""
from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
from pathlib import Path

try:
    from scripts.validate_oss_inventory import INVENTORY, validate_inventory
except ModuleNotFoundError:  # direct script execution
    from validate_oss_inventory import INVENTORY, validate_inventory


def build_sbom(inventory: Path = INVENTORY) -> dict:
    packages = []
    for distribution in sorted(metadata.distributions(), key=lambda item: item.metadata.get("Name", "").lower()):
        name = distribution.metadata.get("Name")
        if not name:
            continue
        packages.append({
            "name": name,
            "version": distribution.version,
            "license": distribution.metadata.get("License", "UNKNOWN") or "UNKNOWN",
        })
    return {
        "format": "marketos-oss-sbom-v1",
        "network_access": False,
        "inventory": str(inventory),
        "inventory_errors": validate_inventory(inventory),
        "candidates": __import__("yaml").safe_load(inventory.read_text(encoding="utf-8")).get("candidates", []),
        "python_packages": packages,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, default=INVENTORY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_sbom(args.inventory)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0 if not report["inventory_errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
