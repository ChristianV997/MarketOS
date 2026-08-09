from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .evidence_source_contract import EvidenceRecord

MAX_RECORDS = 10_000


def validate_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(dataset, dict): errors.append("dataset_must_be_object")
    if not dataset.get("dataset_id"): errors.append("dataset_id_required")
    if not dataset.get("source_name"): errors.append("source_name_required")
    if not isinstance(dataset.get("provenance"), dict) or not dataset.get("provenance"): errors.append("dataset_provenance_required")
    if not isinstance(dataset.get("records"), list): errors.append("records_must_be_list")
    elif len(dataset["records"]) > MAX_RECORDS: errors.append("record_limit_exceeded")
    return {"valid": not errors, "errors": errors}


def load_local_evidence_dataset(path: str) -> dict[str, Any]:
    candidate = Path(path)
    if ".." in candidate.parts: raise ValueError("dataset_path_traversal_blocked")
    if not candidate.exists() or not candidate.is_file(): raise FileNotFoundError(str(candidate))
    dataset = json.loads(candidate.read_text(encoding="utf-8"))
    validation = validate_dataset(dataset)
    if not validation["valid"]: raise ValueError(";".join(validation["errors"]))
    return dataset


def parse_evidence_records(dataset: dict[str, Any]) -> list[EvidenceRecord]:
    validation = validate_dataset(dataset)
    if not validation["valid"]: raise ValueError(";".join(validation["errors"]))
    source_name = str(dataset["source_name"])
    records: list[EvidenceRecord] = []
    for index, raw in enumerate(dataset["records"][:MAX_RECORDS]):
        if not isinstance(raw, dict): continue
        provenance = dict(dataset["provenance"])
        provenance.setdefault("dataset_id", dataset["dataset_id"])
        provenance.setdefault("source_path_type", "local_dataset")
        if not provenance: continue
        seed = f"{dataset['dataset_id']}:{index}:{raw.get('entity_type')}:{raw.get('entity_name')}:{raw.get('signal_type')}"
        evidence = {"evidence_id": f"evidence_{hashlib.sha256(seed.encode()).hexdigest()[:16]}", "source_name": source_name, "source_type": "fixture" if provenance.get("type") == "synthetic_fixture" else "local_file", "entity_type": raw.get("entity_type", ""), "entity_name": raw.get("entity_name", ""), "signal_type": raw.get("signal_type", ""), "value": raw.get("value"), "weight": raw.get("weight", 1.0), "confidence": raw.get("confidence", 0.0), "timestamp": float(raw.get("timestamp", time.time())), "provenance": provenance, "metadata": raw.get("metadata", {})}
        try: records.append(EvidenceRecord.from_dict(evidence))
        except (TypeError, ValueError): continue
    return records
