"""Small durable store for research dossiers and approval requests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.core.persistence import save_json_atomic, state_path


class DossierStore:
    """JSON-backed store matching the repo's existing state persistence style.

    Writes are atomic and keyed by stable IDs, so repeated bounded runs update
    a dossier instead of creating unbounded duplicates.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else Path(state_path("research_dossiers.json"))

    def _read(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {"dossiers": {}, "approvals": {}}

    def save_dossier(self, dossier: Any) -> dict[str, Any]:
        data = self._read()
        record = dossier.to_dict()
        key = record.get("category_id") or record.get("product_id") or record.get("brand_id")
        if not key:
            raise ValueError("dossier requires a stable identifier")
        data.setdefault("dossiers", {})[key] = record
        save_json_atomic(self.path, data)
        return record

    def save_approval(self, approval: Any) -> dict[str, Any]:
        data = self._read()
        record = approval.to_dict()
        key = f"{record['subject_type']}:{record['subject_id']}:{record['requested_action']}"
        data.setdefault("approvals", {})[key] = record
        save_json_atomic(self.path, data)
        return record

    def get(self, key: str) -> dict[str, Any] | None:
        return self._read().get("dossiers", {}).get(key)

    def approvals_for(self, subject_id: str) -> list[dict[str, Any]]:
        return [item for item in self._read().get("approvals", {}).values() if item.get("subject_id") == subject_id]

    def decide_approval(self, subject_type: str, subject_id: str, requested_action: str,
                        *, state: str, decided_by: str, reason: str = "") -> dict[str, Any]:
        if state not in {"approved", "rejected"}:
            raise ValueError("approval decision must be approved or rejected")
        data = self._read()
        key = f"{subject_type}:{subject_id}:{requested_action}"
        existing = data.setdefault("approvals", {}).get(key)
        if not existing:
            raise KeyError("approval request not found")
        existing.update({"state": state, "decided_by": decided_by, "reason": reason, "decided_at": __import__("time").time()})
        save_json_atomic(self.path, data)
        return existing

    def snapshot(self) -> dict[str, Any]:
        return self._read()
