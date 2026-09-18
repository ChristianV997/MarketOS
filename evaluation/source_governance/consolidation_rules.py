"""Extra fail-closed rules for source-adaptation consolidation v1.

Imported by tests and operator notes. Does not replace the canonical validator.
"""
from __future__ import annotations

from typing import Any, Mapping

STALE_TARGET_AUTHORITIES = {
    "backend.scouting.crawl4ai_client": "backend.adapters.research.crawl4ai",
}


def extra_record_errors(record: Mapping[str, Any]) -> list[str]:
    sid = str(record.get("source_id", ""))
    target = str(record.get("marketos_target_authority", ""))
    mode = str(record.get("adaptation_mode", ""))
    errors: list[str] = []
    if target in STALE_TARGET_AUTHORITIES:
        errors.append(
            f"stale_target_authority in {sid}: '{target}' relocated to {STALE_TARGET_AUTHORITIES[target]}"
        )
    if "gpu" in sid.lower() and mode in {"emulate", "copy_pattern", "integrate"}:
        errors.append(
            f"gpu_orchestration_unauthorized in {sid}: reject or reference_only"
        )
    return errors
