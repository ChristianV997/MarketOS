"""Generate a deterministic, network-free OSS inventory/dependency manifest."""
from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
from pathlib import Path
import re

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
    inventory_data = __import__("yaml").safe_load(inventory.read_text(encoding="utf-8")) or {}
    requirements = _declared_requirements()
    return {
        "format": "marketos-oss-sbom-v2",
        "network_access": False,
        "inventory": str(inventory),
        "inventory_errors": validate_inventory(inventory),
        "candidates": inventory_data.get("candidates", []),
        "declared_requirements": requirements,
        "python_packages": packages,
    }


def _declared_requirements() -> list[dict[str, str]]:
    """Record source requirement declarations alongside resolved packages."""
    root = Path(__file__).parents[1]
    records: list[dict[str, str]] = []
    pattern = re.compile(r"^([A-Za-z0-9_.-]+)\s*(.*)$")
    for filename in ("requirements.txt", "requirements-oss-agents.txt", "requirements-security.txt"):
        path = root / filename
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            match = pattern.match(line)
            if match:
                records.append({"source": filename, "name": match.group(1), "specifier": match.group(2).strip() or "unconstrained"})
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, default=INVENTORY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_sbom(args.inventory)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0 if not report["inventory_errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
