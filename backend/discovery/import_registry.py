from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from .evidence_import import EvidenceImportJob, EvidenceSourceQuality


class EvidenceImportRegistry:
    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path or os.getenv("MARKETOS_EVIDENCE_IMPORT_STATE", "state/evidence_import_registry.json"))
        self.import_jobs: dict[str, EvidenceImportJob] = {}
        self.source_quality: dict[str, EvidenceSourceQuality] = {}
        self._lock = threading.RLock(); self.load()

    def register_import_job(self, job: EvidenceImportJob) -> EvidenceImportJob:
        self.import_jobs[job.import_id] = job; self.save(); return job
    def update_import_job(self, job: EvidenceImportJob) -> EvidenceImportJob: return self.register_import_job(job)
    def get_import_job(self, import_id: str) -> EvidenceImportJob | None: return self.import_jobs.get(import_id)
    def list_import_jobs(self, workspace_id: str | None = None, source_name: str | None = None, status: str | None = None, limit: int = 50) -> list[EvidenceImportJob]:
        items = [job for job in self.import_jobs.values() if (workspace_id is None or job.workspace_id == workspace_id) and (source_name is None or job.source_name == source_name) and (status is None or job.status == status)]
        return sorted(items, key=lambda item: (item.created_at, item.import_id), reverse=True)[:max(0, min(int(limit), 500))]
    def register_source_quality(self, quality: EvidenceSourceQuality) -> EvidenceSourceQuality:
        self.source_quality[quality.source_name] = quality; self.save(); return quality
    def get_source_quality(self, source_name: str) -> EvidenceSourceQuality | None: return self.source_quality.get(source_name)
    def list_source_quality(self, limit: int = 100) -> list[EvidenceSourceQuality]: return list(self.source_quality.values())[:max(0, min(int(limit), 500))]
    def clear_for_tests(self) -> None: self.import_jobs.clear(); self.source_quality.clear(); self.save()
    def to_dict(self) -> dict[str, Any]: return {"import_jobs": {k: v.to_dict() for k, v in self.import_jobs.items()}, "source_quality": {k: v.to_dict() for k, v in self.source_quality.items()}}
    def load(self) -> None:
        try:
            if not self.path.exists(): return
            raw = json.loads(self.path.read_text(encoding="utf-8")); self.import_jobs = {k: EvidenceImportJob.from_dict(v) for k, v in raw.get("import_jobs", {}).items() if isinstance(v, dict)}; self.source_quality = {k: EvidenceSourceQuality.from_dict(v) for k, v in raw.get("source_quality", {}).items() if isinstance(v, dict)}
        except Exception: self.import_jobs, self.source_quality = {}, {}
    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True); temp = self.path.with_suffix(self.path.suffix + ".tmp"); temp.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8"); temp.replace(self.path)
        except Exception: pass


_singleton: EvidenceImportRegistry | None = None
_lock = threading.Lock()
def get_import_registry() -> EvidenceImportRegistry:
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None: _singleton = EvidenceImportRegistry()
    return _singleton
