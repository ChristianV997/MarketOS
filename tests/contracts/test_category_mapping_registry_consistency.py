"""Registry/work-order entries for Shopify taxonomy must match the real mapper path and pinned source."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

from services.category_mapping.schemas import TAXONOMY_SOURCE_PROVENANCE

ROOT = Path(__file__).resolve().parents[2]


def _entry(path: str, key: str, value: str) -> dict:
    return next(r for r in json.loads((ROOT / path).read_text(encoding="utf-8")) if r[key] == value)


def test_registry_entry_matches_pinned_provenance_and_real_mapper_symbol():
    record = _entry("data/source_adaptation_registry.json", "source_id", "src-shopify-product-taxonomy")
    assert record["commit_sha"] == record["revision"] == TAXONOMY_SOURCE_PROVENANCE["commit_sha"]
    assert record["version_tag"] == TAXONOMY_SOURCE_PROVENANCE["version_tag"]
    assert record["license"] == TAXONOMY_SOURCE_PROVENANCE["license"] == "MIT"
    module_path, _, symbol = record["marketos_target_authority"].rpartition(".")
    assert callable(getattr(importlib.import_module(module_path), symbol))
    assert record["security_surface"]["network_access"] is False


def test_work_order_entry_matches_registry_and_mapper_file():
    wo = _entry("data/source_adaptation_work_orders.json", "source_id", "src-shopify-product-taxonomy")
    assert (ROOT / wo["marketos_target_module"]).is_file()
    assert wo["commit_sha"] == TAXONOMY_SOURCE_PROVENANCE["commit_sha"]


def test_registry_artifacts_regenerate_byte_identically(tmp_path):
    from scripts.ai.build_source_adaptation_registry import build_and_save

    reg, wo = tmp_path / "reg.json", tmp_path / "wo.json"
    build_and_save(reg, wo)
    assert reg.read_bytes() == (ROOT / "data" / "source_adaptation_registry.json").read_bytes()
    assert wo.read_bytes() == (ROOT / "data" / "source_adaptation_work_orders.json").read_bytes()
