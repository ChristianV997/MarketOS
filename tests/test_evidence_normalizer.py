from pathlib import Path
import pytest
from backend.discovery.evidence_normalizer import normalize_imported_evidence


def test_normalizer_applies_quality_and_deduplicates():
    path = Path(__file__).parent / "fixtures" / "evidence_imports" / "google_trends_sample.csv"
    result = normalize_imported_evidence(str(path), "google_trends_csv", "google_trends")
    assert result.import_job.status == "completed"
    assert result.records[0].confidence < 0.5
    assert result.records[0].provenance["source_file"] == path.name


def test_unsupported_and_unsafe_inputs_fail_closed():
    result = normalize_imported_evidence("tests/fixtures/evidence_imports/google_trends_sample.csv", "unknown", "x")
    assert result.import_job.status == "blocked"
    unsafe = normalize_imported_evidence("../outside.csv", "google_trends_csv", "x")
    assert unsafe.import_job.status == "failed"
