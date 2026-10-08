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
    """Return a root-relative posix path if ``path`` stays under the project root.

    Relative paths are taken from the project root. Symlinks are resolved first, so a
    link inside the project that points outside is rejected. Confinement uses a path
    boundary check (``commonpath`` / ``relative_to``), not a plain string prefix, so
    sibling directories that share a name prefix cannot sneak through. A rejected path
    raises the same error whether or not it exists, so the result is not an existence
    oracle. The return value is relative and safe to open via ``dir_fd``.
    """
    if not isinstance(path, str) or not path or "\x00" in path:
        raise ValueError("dataset_path_invalid")
    if ".." in Path(path).parts:
        raise ValueError("dataset_path_traversal_blocked")
    root = Path(os.path.realpath(_project_root()))
    root_s = str(root)
    candidate = Path(path) if Path(path).is_absolute() else root / path
    try:
        resolved_s = os.path.realpath(candidate)
    except (OSError, ValueError):
        raise ValueError("dataset_path_invalid") from None
    try:
        if os.path.commonpath([root_s, resolved_s]) != root_s:
            raise ValueError("dataset_path_outside_project_root")
        relative = Path(resolved_s).relative_to(root)
    except ValueError:
        raise ValueError("dataset_path_outside_project_root") from None
    if not relative.parts or relative == Path(".") or ".." in relative.parts:
        raise ValueError("dataset_path_outside_project_root")
    return relative.as_posix()


def _read_regular_file(relative: str) -> bytes:
    """Open ``relative`` under the project root without following a final-component symlink.

    The path was confined to a root-relative form a moment ago. Opening through the
    project-root directory descriptor keeps the sink inside that root; ``O_NOFOLLOW``
    stops the last component from being swapped for an outside symlink in between;
    ``O_NONBLOCK`` plus the regular-file check keep a FIFO or device from hanging or
    feeding the loader. Descriptors are always closed.
    """
    if not isinstance(relative, str) or not relative or "\x00" in relative:
        raise ValueError("dataset_path_invalid")
    if ".." in Path(relative).parts or Path(relative).is_absolute():
        raise ValueError("dataset_path_traversal_blocked")
    root_s = os.path.realpath(_project_root())
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        root_fd = os.open(root_s, dir_flags)
    except OSError:
        raise FileNotFoundError("dataset_not_found") from None
    try:
        try:
            descriptor = os.open(relative, flags, dir_fd=root_fd)
        except OSError:
            raise FileNotFoundError("dataset_not_found") from None
    finally:
        os.close(root_fd)
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
