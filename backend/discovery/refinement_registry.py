from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from .discovery_comparison import DiscoveryComparison
from .evidence_gap import EvidenceGapAnalysis
from .import_recommendation import ImportRecommendationPlan
from .import_templates import ImportTemplate

logger = logging.getLogger(__name__)

# (state section, record class, identity attribute that must equal the section key)
_SECTIONS = (
    ("gap_analyses", EvidenceGapAnalysis, "analysis_id"),
    ("import_plans", ImportRecommendationPlan, "plan_id"),
    ("templates", ImportTemplate, "template_id"),
    ("comparisons", DiscoveryComparison, "comparison_id"),
)
_MISSING = object()


class RegistryPersistenceError(RuntimeError):
    """Carries a fixed reason code only: never a path, file content, or wrapped exception text."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _InvalidState(Exception):
    """Internal: the file parsed as JSON but does not match the registry's shape."""


def _parse_sections(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        raise _InvalidState
    parsed: dict[str, dict[str, Any]] = {}
    for name, model, identity in _SECTIONS:
        section = raw.get(name, {})
        if not isinstance(section, dict):
            raise _InvalidState
        items: dict[str, Any] = {}
        for key, record in section.items():
            if not isinstance(record, dict):
                raise _InvalidState
            try:
                item = model.from_dict(record)
            except Exception:  # any from_dict failure means the record cannot round-trip faithfully
                raise _InvalidState from None
            if getattr(item, identity) != key:
                raise _InvalidState
            items[key] = item
        parsed[name] = items
    return parsed


def _write_atomic(path: Path, text: str) -> None:
    """Write to a unique temp file beside *path*, fsync it, then replace. A failure leaves *path* as it was."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    replaced = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        replaced = True
    finally:
        if not replaced:
            Path(temp_name).unlink(missing_ok=True)


class RefinementRegistry:
    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path or os.getenv("MARKETOS_REFINEMENT_STATE", "state/refinement_registry.json")); self.gap_analyses = {}; self.import_plans = {}; self.templates = {}; self.comparisons = {}
        self.load_error: str | None = None; self._lock = threading.RLock(); self.load()
    def register_gap_analysis(self, item): return self._store("gap_analyses", item.analysis_id, item)
    def get_gap_analysis(self, item_id): return self.gap_analyses.get(item_id)
    def list_gap_analyses(self, workspace_id=None, limit=50):
        with self._lock: return list(reversed([x for x in self.gap_analyses.values() if workspace_id is None or x.workspace_id == workspace_id]))[:max(0, min(int(limit), 500))]
    def register_import_plan(self, item): return self._store("import_plans", item.plan_id, item)
    def get_import_plan(self, item_id): return self.import_plans.get(item_id)
    def list_import_plans(self, workspace_id=None, limit=50):
        with self._lock: return list(reversed([x for x in self.import_plans.values() if workspace_id is None or x.workspace_id == workspace_id]))[:max(0, min(int(limit), 500))]
    def register_template(self, item): return self._store("templates", item.template_id, item)
    def get_template(self, item_id): return self.templates.get(item_id)
    def list_templates(self, parser_type=None, limit=100):
        with self._lock: return [x for x in self.templates.values() if parser_type is None or x.parser_type == parser_type][:max(0, min(int(limit), 500))]
    def register_comparison(self, item): return self._store("comparisons", item.comparison_id, item)
    def get_comparison(self, item_id): return self.comparisons.get(item_id)
    def list_comparisons(self, workspace_id=None, limit=50):
        with self._lock: return list(reversed([x for x in self.comparisons.values() if workspace_id is None or x.workspace_id == workspace_id]))[:max(0, min(int(limit), 500))]
    def clear_for_tests(self):
        with self._lock:
            maps = self._section_maps(); previous = [dict(items) for items in maps]
            for items in maps: items.clear()
            try: self._save_locked()
            except RegistryPersistenceError:
                for items, saved in zip(maps, previous): items.clear(); items.update(saved)
                raise
    def to_dict(self):
        with self._lock: return {"gap_analyses": {k: v.to_dict() for k, v in self.gap_analyses.items()}, "import_plans": {k: v.to_dict() for k, v in self.import_plans.items()}, "templates": {k: v.to_dict() for k, v in self.templates.items()}, "comparisons": {k: v.to_dict() for k, v in self.comparisons.items()}}
    def load(self):
        with self._lock:
            self.load_error = None; self.gap_analyses, self.import_plans, self.templates, self.comparisons = {}, {}, {}, {}
            try: text = self.path.read_text(encoding="utf-8")
            except FileNotFoundError: return  # first run: nothing has been persisted yet
            except UnicodeDecodeError: return self._refuse_load("registry_corrupt")
            except OSError: return self._refuse_load("registry_unreadable")
            try: parsed = _parse_sections(json.loads(text))
            except (json.JSONDecodeError, RecursionError): return self._refuse_load("registry_corrupt")
            except _InvalidState: return self._refuse_load("registry_invalid")
            self.gap_analyses, self.import_plans = parsed["gap_analyses"], parsed["import_plans"]
            self.templates, self.comparisons = parsed["templates"], parsed["comparisons"]
    def save(self):
        with self._lock: self._save_locked()
    def _refuse_load(self, reason: str) -> None:
        # The file is left exactly as found. Writes stay blocked until it is repaired and load() runs again (or the process restarts).
        self.load_error = reason
        logger.warning("refinement registry not loaded: %s", reason)
    def _section_maps(self) -> tuple[dict[str, Any], ...]: return (self.gap_analyses, self.import_plans, self.templates, self.comparisons)
    def _store(self, section: str, key: str, item: Any) -> Any:
        with self._lock:
            items = getattr(self, section); previous = items.get(key, _MISSING); items[key] = item
            try: self._save_locked()
            except RegistryPersistenceError:
                if previous is _MISSING: items.pop(key, None)
                else: items[key] = previous
                raise
            return item
    def _save_locked(self) -> None:
        if self.load_error is not None: raise RegistryPersistenceError("registry_writes_blocked")
        try: _write_atomic(self.path, json.dumps(self.to_dict(), indent=2, default=str))
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("refinement registry write failed: %s", type(exc).__name__)
            raise RegistryPersistenceError("registry_write_failed") from None


_singleton = None; _lock = threading.Lock()
def get_refinement_registry():
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None: _singleton = RefinementRegistry()
    return _singleton
