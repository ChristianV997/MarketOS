from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from pathlib import Path
from typing import Any

from .evidence_source_contract import EvidenceRecord

MAX_RECORDS = 10_000


def _project_root() -> Path:
    return Path.cwd().resolve()


def validate_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(dataset, dict): errors.append("dataset_must_be_object")
    if not dataset.get("dataset_id"): errors.append("dataset_id_required")
    if not dataset.get("source_name"): errors.append("source_name_required")
    if not isinstance(dataset.get("provenance"), dict) or not dataset.get("provenance"): errors.append("dataset_provenance_required")
    if not isinstance(dataset.get("records"), list): errors.append("records_must_be_list")
    elif len(dataset["records"]) > MAX_RECORDS: errors.append("record_limit_exceeded")
    return {"valid": not errors, "errors": errors}


def _confined_dataset_path(path: str) -> str:
    """Return the real path of ``path`` if it stays under the project root, else raise.

    Relative paths are taken from the project root. Symlinks are resolved first, so a
    link inside the project that points outside is rejected. A rejected path raises the
    same error whether or not it exists, so the result is not an existence oracle.
    """
    if ".." in Path(path).parts:
        raise ValueError("dataset_path_traversal_blocked")
    root = os.path.realpath(_project_root())
    try:
        resolved = os.path.realpath(os.path.join(root, path))
    except ValueError:
        raise ValueError("dataset_path_invalid") from None
    if not (resolved == root or resolved.startswith(root.rstrip(os.sep) + os.sep)):
        raise ValueError("dataset_path_outside_project_root")
    return resolved


def _read_regular_file(resolved: str) -> bytes:
    """Open without following a final-component symlink and read only a regular file.

    The path was validated a moment ago; ``O_NOFOLLOW`` stops the last component from
    being swapped for an outside symlink in between, and ``O_NONBLOCK`` plus the regular
    file check keep a FIFO or device from hanging or feeding the loader.
    """
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(resolved, flags)
    except OSError:
        raise FileNotFoundError("dataset_not_found") from None
    with os.fdopen(descriptor, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise FileNotFoundError("dataset_not_found")
        return handle.read()


def load_local_evidence_dataset(path: str) -> dict[str, Any]:
    dataset = json.loads(_read_regular_file(_confined_dataset_path(path)).decode("utf-8"))
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
