"""Serialization privacy contracts for discovery evidence-import jobs.

Uses the canonical TrustOS client-export boundary
(``evaluation.trustos.client_workspace_isolation.check_workspace_leakage``).
Fixtures are synthetic only — no real paths, credentials, raw payloads, or
client data.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from backend.discovery.evidence_import import (
    EvidenceImportJob,
    EvidenceNormalizationResult,
    EvidenceSourceQuality,
)
from backend.discovery.evidence_source_contract import EvidenceRecord


# Synthetic secret-shaped local path — never a real host path or credential.
# Avoid TrustOS forbidden value markers (token/credential/sk-/...) in the string.
_SYNTHETIC_SECRET_PATH = "/var/private_ops/client_alpha/import_bundle.csv"


def _check_workspace_leakage(payload: dict):
    """Load TrustOS leakage check without requiring evaluation package side effects."""
    try:
        from evaluation.trustos.client_workspace_isolation import check_workspace_leakage
    except ModuleNotFoundError:
        root = Path(__file__).resolve().parents[1]
        if "evaluation" not in sys.modules:
            pkg = types.ModuleType("evaluation")
            pkg.__path__ = [str(root / "evaluation")]
            sys.modules["evaluation"] = pkg
        if "evaluation.trustos" not in sys.modules:
            sub = types.ModuleType("evaluation.trustos")
            sub.__path__ = [str(root / "evaluation" / "trustos")]
            sys.modules["evaluation.trustos"] = sub
        from evaluation.trustos.client_workspace_isolation import check_workspace_leakage
    return check_workspace_leakage(payload, client_safe=True)


def _sample_job(*, input_path: str = _SYNTHETIC_SECRET_PATH) -> EvidenceImportJob:
    return EvidenceImportJob(
        import_id="import_synth_0001",
        workspace_id="workspace_synth",
        source_name="synthetic_source",
        source_type="local_file",
        input_path=input_path,
        parser_type="generic_market_csv",
        status="completed",
        records_imported=1,
        records_rejected=0,
        warnings=["duplicates_removed:0"],
        blocked_reasons=[],
        created_at=1.0,
        finished_at=2.0,
        metadata={"read_only": True, "network_required": False},
    )


def _sample_quality() -> EvidenceSourceQuality:
    return EvidenceSourceQuality(
        source_name="synthetic_source",
        source_type="local_file",
        quality_score=50.0,
        confidence_multiplier=0.5,
        strengths=["synthetic"],
        weaknesses=[],
        allowed_signal_types=["demand"],
        blocked_signal_types=[],
        freshness_label="static",
        provenance_requirements=["source_file"],
        metadata={},
    )


def test_input_path_preserved_internally_but_omitted_from_to_dict():
    job = _sample_job()
    assert job.input_path == _SYNTHETIC_SECRET_PATH

    payload = job.to_dict()
    assert "input_path" not in payload
    serialized = json.dumps(payload, sort_keys=True, default=str)
    assert _SYNTHETIC_SECRET_PATH not in serialized
    assert "import_bundle" not in serialized
    assert "/var/private_ops/" not in serialized


def test_normalization_result_client_projection_omits_secret_shaped_path():
    job = _sample_job()
    record = EvidenceRecord(
        evidence_id="ev_synth_0001",
        source_name="synthetic_source",
        source_type="local_file",
        entity_type="product",
        entity_name="synth item",
        signal_type="demand",
        value=1.0,
        weight=1.0,
        confidence=0.5,
        timestamp=1.0,
        provenance={"type": "fixture", "source_file": "import_bundle.csv"},
        metadata={},
    )
    result = EvidenceNormalizationResult(
        records=[record],
        rejected=[],
        warnings=list(job.warnings),
        source_quality=_sample_quality(),
        import_job=job,
    )

    # Internal processing still has the path on the live object.
    assert result.import_job.input_path == _SYNTHETIC_SECRET_PATH

    projected = result.to_dict()
    assert "input_path" not in projected["import_job"]
    blob = json.dumps(projected, sort_keys=True, default=str)
    assert _SYNTHETIC_SECRET_PATH not in blob
    assert _check_workspace_leakage(projected) == ()


def test_from_dict_tolerates_omitted_input_path_for_registry_reload():
    job = _sample_job()
    payload = job.to_dict()
    assert "input_path" not in payload

    restored = EvidenceImportJob.from_dict(payload)
    assert restored.input_path == ""
    assert restored.import_id == job.import_id
    assert restored.workspace_id == job.workspace_id
    assert restored.parser_type == job.parser_type
    assert restored.status == job.status


def test_to_dict_is_deterministic():
    job = _sample_job()
    first = job.to_dict()
    second = job.to_dict()
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_serialized_job_does_not_leak_exception_details():
    job = _sample_job()
    job.status = "failed"
    # Mirror normalizer contract: type name only, never str(exc) or paths.
    job.warnings = ["import_failed:OSError"]
    payload = job.to_dict()
    blob = json.dumps(payload, sort_keys=True, default=str)

    assert payload["warnings"] == ["import_failed:OSError"]
    assert "Traceback" not in blob
    assert "No such file" not in blob
    assert _SYNTHETIC_SECRET_PATH not in blob
    assert "exception" not in blob.lower()
    assert _check_workspace_leakage(payload) == ()
