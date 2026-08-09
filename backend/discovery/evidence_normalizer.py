from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from .csv_ingestion import MAX_ROWS, PARSERS, SUPPORTED_PARSERS, load_csv_rows
from .evidence_import import EvidenceImportJob, EvidenceNormalizationResult
from .evidence_source_contract import EvidenceRecord, get_evidence_source_registry
from .local_dataset import load_local_evidence_dataset, parse_evidence_records
from .source_quality import score_source_quality


def normalize_entity_name(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def coerce_confidence(value: Any, default: float = 0.0) -> float:
    return max(0.0, min(coerce_float(value, default), 1.0))


def coerce_weight(value: Any, default: float = 1.0) -> float:
    return max(0.0, min(coerce_float(value, default), 1.0))


def parse_metadata_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict): return value
    if not value: return {}
    import json
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {"metadata_json_invalid": True}


def _dedup(records: list[EvidenceRecord]) -> tuple[list[EvidenceRecord], int]:
    chosen: dict[str, tuple[EvidenceRecord, int]] = {}
    for index, record in enumerate(records):
        context = sorted((str(k), str(v)) for k, v in record.metadata.items() if k not in {"row_number"})
        key = "|".join([record.source_name, record.entity_type, normalize_entity_name(record.entity_name), record.signal_type, repr(context)])
        previous = chosen.get(key)
        if previous is None or (record.confidence, record.weight, -index) > (previous[0].confidence, previous[0].weight, -previous[1]):
            chosen[key] = (record, index)
    return [item[0] for item in chosen.values()], len(records) - len(chosen)


def normalize_imported_evidence(input_path: str, parser_type: str, source_name: str, workspace_id: str = "default", provenance: dict[str, Any] | None = None, max_rows: int = MAX_ROWS) -> EvidenceNormalizationResult:
    now = time.time()
    import_id = "import_" + hashlib.sha256(f"{workspace_id}:{source_name}:{parser_type}:{input_path}".encode()).hexdigest()[:16]
    job = EvidenceImportJob(import_id, workspace_id, source_name, "local_file", input_path, parser_type, "running", created_at=now, metadata={"read_only": True, "network_required": False})
    warnings: list[str] = []
    rejected: list[dict[str, Any]] = []
    try:
        if parser_type not in SUPPORTED_PARSERS:
            job.status = "blocked"; job.blocked_reasons = ["unsupported_parser_type"]
            quality = score_source_quality(source_name, "local_file", parser_type, provenance or {}, 0, [])
            job.finished_at = time.time()
            return EvidenceNormalizationResult([], rejected, warnings, quality, job)
        if source_name == "external_live" or any(bool((provenance or {}).get(key)) for key in ("network_required", "credentials_required", "mutation_possible")):
            job.status = "blocked"; job.blocked_reasons = ["live_or_mutating_source_blocked"]; job.finished_at = time.time()
            quality = score_source_quality(source_name, "external_live", parser_type, provenance or {}, 0, [])
            return EvidenceNormalizationResult([], rejected, warnings, quality, job)
        capability = get_evidence_source_registry().validate_source_safe("local_dataset")
        if not capability.get("allowed"):
            job.status = "blocked"; job.blocked_reasons = capability.get("blocked_reasons", ["source_not_allowed"])
            quality = score_source_quality(source_name, "local_file", parser_type, provenance or {}, 0, [])
            job.finished_at = time.time()
            return EvidenceNormalizationResult([], rejected, warnings, quality, job)
        provenance_data = dict(provenance or {})
        provenance_data.update({"source_name": source_name, "source_file": str(Path(input_path).name), "workspace_id": workspace_id})
        if parser_type == "local_json_dataset":
            dataset = load_local_evidence_dataset(input_path)
            raw_records = parse_evidence_records(dataset)
            for record in raw_records:
                record.provenance.update(provenance_data)
            records = raw_records
            fields = list(dataset.get("records", [{}])[0].keys()) if dataset.get("records") else []
        else:
            rows = load_csv_rows(input_path, max_rows)
            fields = list(rows[0].keys()) if rows else []
            records = PARSERS[parser_type](rows, provenance_data)
        quality = score_source_quality(source_name, "local_file", parser_type, provenance_data, len(records), fields)
        normalized: list[EvidenceRecord] = []
        for record in records:
            if not record.provenance:
                rejected.append({"reason": "provenance_required"}); continue
            if record.signal_type in quality.blocked_signal_types:
                rejected.append({"reason": "signal_not_allowed_for_source", "signal_type": record.signal_type}); continue
            record.confidence = coerce_confidence(record.confidence, 0.5) * quality.confidence_multiplier
            record.weight = coerce_weight(record.weight)
            normalized.append(record)
        normalized, duplicates = _dedup(normalized)
        if duplicates: warnings.append(f"duplicates_removed:{duplicates}")
        job.records_imported = len(normalized); job.records_rejected = len(rejected) + max(0, len(records) - len(normalized)); job.warnings = warnings; job.status = "completed"; job.finished_at = time.time()
        return EvidenceNormalizationResult(normalized, rejected, warnings, quality, job)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        job.status = "failed"; job.finished_at = time.time(); job.warnings = [f"import_failed:{type(exc).__name__}"]
        quality = score_source_quality(source_name, "local_file", parser_type, provenance or {}, 0, [])
        return EvidenceNormalizationResult([], rejected, job.warnings, quality, job)
