from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from .evidence_import import EvidenceImportJob, EvidenceSourceQuality

logger = logging.getLogger(__name__)

# (state section, record class, identity attribute that must equal the section key)
_SECTIONS = (
    ("import_jobs", EvidenceImportJob, "import_id"),
    ("source_quality", EvidenceSourceQuality, "source_name"),
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


class EvidenceImportRegistry:
    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path or os.getenv("MARKETOS_EVIDENCE_IMPORT_STATE", "state/evidence_import_registry.json"))
        self.import_jobs: dict[str, EvidenceImportJob] = {}
        self.source_quality: dict[str, EvidenceSourceQuality] = {}
        self.load_error: str | None = None
        self._lock = threading.RLock(); self.load()

    def register_import_job(self, job: EvidenceImportJob) -> EvidenceImportJob:
        return self._store("import_jobs", job.import_id, job)
    def update_import_job(self, job: EvidenceImportJob) -> EvidenceImportJob: return self.register_import_job(job)
    def get_import_job(self, import_id: str) -> EvidenceImportJob | None: return self.import_jobs.get(import_id)
    def list_import_jobs(self, workspace_id: str | None = None, source_name: str | None = None, status: str | None = None, limit: int = 50) -> list[EvidenceImportJob]:
        with self._lock:
            items = [job for job in self.import_jobs.values() if (workspace_id is None or job.workspace_id == workspace_id) and (source_name is None or job.source_name == source_name) and (status is None or job.status == status)]
        return sorted(items, key=lambda item: (item.created_at, item.import_id), reverse=True)[:max(0, min(int(limit), 500))]
    def register_source_quality(self, quality: EvidenceSourceQuality) -> EvidenceSourceQuality:
        return self._store("source_quality", quality.source_name, quality)
    def get_source_quality(self, source_name: str) -> EvidenceSourceQuality | None: return self.source_quality.get(source_name)
    def list_source_quality(self, limit: int = 100) -> list[EvidenceSourceQuality]:
        with self._lock: return list(self.source_quality.values())[:max(0, min(int(limit), 500))]
    def clear_for_tests(self) -> None:
        with self._lock:
            maps = self._section_maps(); previous = [dict(items) for items in maps]
            for items in maps: items.clear()
            try: self._save_locked()
            except RegistryPersistenceError:
                for items, saved in zip(maps, previous): items.clear(); items.update(saved)
                raise
    def to_dict(self) -> dict[str, Any]:
        with self._lock: return {"import_jobs": {k: v.to_dict() for k, v in self.import_jobs.items()}, "source_quality": {k: v.to_dict() for k, v in self.source_quality.items()}}
    def load(self) -> None:
        with self._lock:
            self.load_error = None; self.import_jobs, self.source_quality = {}, {}
            try: text = self.path.read_text(encoding="utf-8")
            except FileNotFoundError: return  # first run: nothing has been persisted yet
            except UnicodeDecodeError: return self._refuse_load("registry_corrupt")
            except OSError: return self._refuse_load("registry_unreadable")
            try: parsed = _parse_sections(json.loads(text))
            except (json.JSONDecodeError, RecursionError): return self._refuse_load("registry_corrupt")
            except _InvalidState: return self._refuse_load("registry_invalid")
            self.import_jobs, self.source_quality = parsed["import_jobs"], parsed["source_quality"]
    def save(self) -> None:
        with self._lock: self._save_locked()
    def _refuse_load(self, reason: str) -> None:
        # The file is left exactly as found. Writes stay blocked until it is repaired and load() runs again (or the process restarts).
        self.load_error = reason
        logger.warning("evidence import registry not loaded: %s", reason)
    def _section_maps(self) -> tuple[dict[str, Any], ...]: return (self.import_jobs, self.source_quality)
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
            logger.warning("evidence import registry write failed: %s", type(exc).__name__)
            raise RegistryPersistenceError("registry_write_failed") from None


_singleton: EvidenceImportRegistry | None = None
_lock = threading.Lock()
def get_import_registry() -> EvidenceImportRegistry:
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None: _singleton = EvidenceImportRegistry()
    return _singleton
