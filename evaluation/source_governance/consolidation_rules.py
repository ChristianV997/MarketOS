"""Canonical extra fail-closed rules for source-adaptation records.

Called by evaluation.source_governance.validator.validate_source_record.
This is not a second registry.
"""
from __future__ import annotations

from typing import Any, Mapping

STALE_TARGET_AUTHORITIES = {
    "backend.scouting.crawl4ai_client": "backend.adapters.research.crawl4ai",
}

# Sequential placeholder pins previously published in the catalog.
SYNTHETIC_COMMIT_SHAS = frozenset({
    "e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4",
    "1a8b9c0d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b",
    "3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d",
})


def extra_record_errors(record: Mapping[str, Any]) -> list[str]:
    sid = str(record.get("source_id", ""))
    target = str(record.get("marketos_target_authority", ""))
    mode = str(record.get("adaptation_mode", ""))
    sha = str(record.get("commit_sha") or record.get("revision") or "")
    errors: list[str] = []
    if target in STALE_TARGET_AUTHORITIES:
        errors.append(
            f"stale_target_authority in {sid}: '{target}' relocated to {STALE_TARGET_AUTHORITIES[target]}"
        )
    if sha in SYNTHETIC_COMMIT_SHAS:
        errors.append(f"synthetic_commit_sha in {sid}: placeholder pin {sha} is not a real revision")
    if "gpu" in sid.lower() and mode in {"emulate", "copy_pattern", "integrate"}:
        errors.append(
            f"gpu_orchestration_unauthorized in {sid}: reject or reference_only"
        )
    return errors
