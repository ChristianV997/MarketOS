"""Cross-file consistency check between docs/oss/INVENTORY.yml,
docs/oss/LICENSE_MANIFEST.yml, and THIRD_PARTY_NOTICES.md — the three files
that must stay mutually consistent per docs/oss/DEPENDENCY_POLICY.md."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _inventory_names_and_licenses() -> dict[str, str]:
    data = yaml.safe_load((ROOT / "docs/oss/INVENTORY.yml").read_text())
    return {c["name"]: c["license"] for c in data["candidates"]}


def _manifest_names_and_licenses() -> dict[str, str]:
    data = yaml.safe_load((ROOT / "docs/oss/LICENSE_MANIFEST.yml").read_text())
    return {c["name"]: c["license"] for c in data["components"]}


def test_every_inventory_candidate_has_a_matching_license_manifest_entry():
    inventory = _inventory_names_and_licenses()
    manifest = _manifest_names_and_licenses()
    for name, license_ in inventory.items():
        assert name in manifest, f"{name} is in INVENTORY.yml but missing from LICENSE_MANIFEST.yml"
        assert manifest[name] == license_, (
            f"{name} license mismatch: INVENTORY.yml={license_!r} LICENSE_MANIFEST.yml={manifest[name]!r}"
        )


def test_every_inventory_candidate_has_a_third_party_notices_row():
    inventory = _inventory_names_and_licenses()
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    for name in inventory:
        pattern = rf"^\|\s*{re.escape(name)}\s*\|"
        assert re.search(pattern, notices, re.MULTILINE), f"{name} has no THIRD_PARTY_NOTICES.md row"


def test_no_duplicate_candidate_names():
    data = yaml.safe_load((ROOT / "docs/oss/INVENTORY.yml").read_text())
    names = [c["name"] for c in data["candidates"]]
    assert len(names) == len(set(names))
