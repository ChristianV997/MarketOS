from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from .category_discovery import CategoryDiscoveryRun
from .evidence_source_contract import EvidenceRecord
from .product_hypothesis import ProductHypothesisRun


class DiscoveryRegistry:
    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path or os.getenv("MARKETOS_DISCOVERY_STATE", "state/discovery_registry.json"))
        self.evidence: dict[str, EvidenceRecord] = {}; self.categories: dict[str, CategoryDiscoveryRun] = {}; self.hypotheses: dict[str, ProductHypothesisRun] = {}; self._lock = threading.RLock(); self.load()
    def register_evidence(self, records: list[EvidenceRecord]) -> list[EvidenceRecord]:
        for record in records: self.evidence[record.evidence_id] = record
        self.save(); return records
    def get_evidence(self, evidence_id: str) -> EvidenceRecord | None: return self.evidence.get(evidence_id)
    def list_evidence(self, source_name: str | None = None, entity_type: str | None = None, signal_type: str | None = None, limit: int = 100) -> list[EvidenceRecord]:
        return list([record for record in self.evidence.values() if (source_name is None or record.source_name == source_name) and (entity_type is None or record.entity_type == entity_type) and (signal_type is None or record.signal_type == signal_type)])[:max(0, min(int(limit), 1000))]
    def register_category_discovery(self, run: CategoryDiscoveryRun) -> CategoryDiscoveryRun: self.categories[run.discovery_id] = run; self.save(); return run
    def get_category_discovery(self, discovery_id: str) -> CategoryDiscoveryRun | None: return self.categories.get(discovery_id)
    def list_category_discoveries(self, workspace_id: str | None = None, status: str | None = None, limit: int = 50) -> list[CategoryDiscoveryRun]: return list([run for run in self.categories.values() if (workspace_id is None or run.workspace_id == workspace_id) and (status is None or run.status == status)])[:max(0, min(int(limit), 500))]
    def register_product_hypothesis_run(self, run: ProductHypothesisRun) -> ProductHypothesisRun: self.hypotheses[run.hypothesis_run_id] = run; self.save(); return run
    def get_product_hypothesis_run(self, hypothesis_run_id: str) -> ProductHypothesisRun | None: return self.hypotheses.get(hypothesis_run_id)
    def list_product_hypothesis_runs(self, workspace_id: str | None = None, discovery_id: str | None = None, limit: int = 50) -> list[ProductHypothesisRun]: return list([run for run in self.hypotheses.values() if (workspace_id is None or run.workspace_id == workspace_id) and (discovery_id is None or run.discovery_id == discovery_id)])[:max(0, min(int(limit), 500))]
    def clear_for_tests(self) -> None: self.evidence.clear(); self.categories.clear(); self.hypotheses.clear(); self.save()
    def to_dict(self) -> dict[str, Any]: return {"evidence": {key: value.to_dict() for key, value in self.evidence.items()}, "categories": {key: value.to_dict() for key, value in self.categories.items()}, "hypotheses": {key: value.to_dict() for key, value in self.hypotheses.items()}}
    def load(self) -> None:
        try:
            if not self.path.exists(): return
            raw = json.loads(self.path.read_text(encoding="utf-8")); self.evidence = {key: EvidenceRecord.from_dict(value) for key, value in raw.get("evidence", {}).items() if isinstance(value, dict)}; self.categories = {key: CategoryDiscoveryRun.from_dict(value) for key, value in raw.get("categories", {}).items() if isinstance(value, dict)}; self.hypotheses = {key: ProductHypothesisRun.from_dict(value) for key, value in raw.get("hypotheses", {}).items() if isinstance(value, dict)}
        except Exception: self.evidence, self.categories, self.hypotheses = {}, {}, {}
    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True); temp = self.path.with_suffix(self.path.suffix + ".tmp"); temp.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8"); temp.replace(self.path)
        except Exception: pass


_singleton: DiscoveryRegistry | None = None; _lock = threading.Lock()
def get_discovery_registry() -> DiscoveryRegistry:
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None: _singleton = DiscoveryRegistry()
    return _singleton
