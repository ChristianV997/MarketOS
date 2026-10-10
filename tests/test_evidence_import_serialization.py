"""Serialization privacy contracts for discovery evidence-import jobs.

Uses the canonical TrustOS client-export boundary
(``evaluation.trustos.client_workspace_isolation.check_workspace_leakage``).
Fixtures are synthetic only — no real paths, credentials, raw payloads, or
client data.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import types
from pathlib import Path

from backend.discovery.evidence_import import (
    EvidenceImportJob,
    EvidenceNormalizationResult,
    EvidenceSourceQuality,
)
from backend.discovery.evidence_normalizer import normalize_imported_evidence
from backend.discovery.evidence_source_contract import EvidenceRecord
from backend.discovery.import_registry import EvidenceImportRegistry
from backend.obsidian.templates import render_evidence_import_note


# Synthetic secret-shaped local path — never a real host path or credential.
# Avoid TrustOS forbidden value markers (token/credential/sk-/...) in the string.
_SYNTHETIC_SECRET_PATH = "/var/private_ops/client_alpha/import_bundle.csv"
_FIXTURE_CSV = Path(__file__).resolve().parent / "fixtures" / "evidence_imports" / "google_trends_sample.csv"

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


def test_from_dict_ignores_untrusted_input_path_injection():
    """Serialized JSON must not restore a filesystem path for later reads."""
    forged = {
        "import_id": "import_forged_0001",
        "workspace_id": "workspace_synth",
        "source_name": "synthetic_source",
        "source_type": "local_file",
        "input_path": _SYNTHETIC_SECRET_PATH,
        "parser_type": "generic_market_csv",
        "status": "completed",
        "records_imported": 1,
        "records_rejected": 0,
        "warnings": [],
        "blocked_reasons": [],
        "created_at": 1.0,
        "finished_at": 2.0,
        "metadata": {"read_only": True},
    }
    restored = EvidenceImportJob.from_dict(forged)
    assert restored.input_path == ""
    assert _SYNTHETIC_SECRET_PATH not in json.dumps(restored.to_dict(), sort_keys=True)
    assert _check_workspace_leakage(restored.to_dict()) == ()


def test_to_dict_from_dict_round_trip_is_deterministic():
    job = _sample_job()
    first = job.to_dict()
    second = job.to_dict()
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    restored = EvidenceImportJob.from_dict(first)
    assert restored.input_path == ""
    round_trip = restored.to_dict()
    assert round_trip == first
    assert json.dumps(round_trip, sort_keys=True) == json.dumps(first, sort_keys=True)
    assert EvidenceImportJob.from_dict(round_trip).to_dict() == round_trip


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


def test_normalize_keeps_basename_provenance_and_omits_full_path():
    """Local processing retains input_path; client projection keeps basename only.

    CSV ingestion confines reads to project roots, so the synthetic file is
    staged under tests/fixtures (not a host secret path).
    """
    fixture_root = Path(__file__).resolve().parent / "fixtures"
    with tempfile.TemporaryDirectory(prefix="synth_private_ops_", dir=fixture_root) as tmp:
        synthetic_dir = Path(tmp) / "client_alpha"
        synthetic_dir.mkdir(parents=True)
        synthetic_path = synthetic_dir / "import_bundle.csv"
        shutil.copyfile(_FIXTURE_CSV, synthetic_path)

        result = normalize_imported_evidence(
            str(synthetic_path),
            "google_trends_csv",
            "google_trends",
            workspace_id="workspace_synth",
        )
        assert result.import_job.status == "completed"
        assert result.import_job.input_path == str(synthetic_path)
        assert result.records
        assert result.records[0].provenance.get("source_file") == "import_bundle.csv"

        projected = result.to_dict()
        assert "input_path" not in projected["import_job"]
        blob = json.dumps(projected, sort_keys=True, default=str)
        assert str(synthetic_path) not in blob
        assert "import_bundle.csv" in blob
        # Basename provenance is allowed; full filesystem path must not appear.
        assert _check_workspace_leakage({"import_job": projected["import_job"]}) == ()


def test_registry_and_obsidian_projections_omit_input_path():
    job = _sample_job()
    quality = _sample_quality()
    with tempfile.TemporaryDirectory(prefix="marketos_registry_") as tmp:
        registry = EvidenceImportRegistry(Path(tmp) / "imports.json")
        registry.register_import_job(job)
        registry.register_source_quality(quality)
        raw = (Path(tmp) / "imports.json").read_text(encoding="utf-8")
        assert "input_path" not in raw
        assert _SYNTHETIC_SECRET_PATH not in raw

        # Forged on-disk path must not restore into the in-memory job.
        data = json.loads(raw)
        data["import_jobs"][job.import_id]["input_path"] = _SYNTHETIC_SECRET_PATH
        (Path(tmp) / "imports.json").write_text(json.dumps(data), encoding="utf-8")
        reloaded = EvidenceImportRegistry(Path(tmp) / "imports.json")
        assert reloaded.get_import_job(job.import_id).input_path == ""

    note = render_evidence_import_note(job, quality)
    assert "input_path" not in note
    assert _SYNTHETIC_SECRET_PATH not in note
    # Live object still holds the path for local processing.
    assert job.input_path == _SYNTHETIC_SECRET_PATH
