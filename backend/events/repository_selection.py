"""Explicit EventRepository target selection for narrow operator-owned tools."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .adapters.supabase_staging import build_supabase_staging_repository
from .repository import JsonlEventRepository


_TARGETS = ("none", "jsonl", "supabase_staging")

def available_event_repository_targets() -> tuple[str, ...]: return _TARGETS
def explain_repository_target(target: str) -> dict[str, Any]:
    if target not in _TARGETS: raise ValueError(f"unknown event repository target: {target}")
    return {"target": target, "default": target == "none", "requires_explicit_path": target == "jsonl", "requires_explicit_supabase_gate": target == "supabase_staging", "authoritative": False}
def select_event_repository(target: str = "none", *, jsonl_path: str | Path | None = None, supabase_enabled: bool = False, fake_client: Any | None = None, environ: dict[str, str] | None = None) -> Any | None:
    if target == "none": return None
    if target == "jsonl":
        if not jsonl_path: raise ValueError("jsonl target requires an explicit path")
        return JsonlEventRepository(jsonl_path)
    if target == "supabase_staging":
        if not supabase_enabled: raise ValueError("Supabase staging target requires explicit enablement")
        return build_supabase_staging_repository(client=fake_client, environ=environ)
    raise ValueError(f"unknown event repository target: {target}")

__all__ = ["available_event_repository_targets", "explain_repository_target", "select_event_repository"]
