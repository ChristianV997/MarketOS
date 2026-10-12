"""Round trip: starter templates, and synthetic fills of them, import through the existing normalizer without losing fields or mislabeling provenance.

Callers: pytest. Data: synthetic placeholder and fill rows written to a temporary working directory only.
"""
import csv
import json
from pathlib import Path

import pytest

from backend.discovery.evidence_normalizer import normalize_imported_evidence
from backend.discovery.import_recommendation import _FIELDS
from backend.discovery.import_templates import IMPORT_PROVENANCE, create_import_template

SUPPLIER_ROW = {
    "category": "Kitchen",
    "product": "Synthetic Widget",
    "supplier_cost": "4.50",
    "shipping_cost": "1.25",
    "moq": "50",
    "lead_time_days": "12",
    "availability": "0.8",
    "supplier": "Synthetic Supplier A",
}


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _canonical_columns(parser):
    required, optional = _FIELDS[parser]
    return required + optional


def _write_csv(directory, name, columns, rows):
    path = directory / name
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return str(path)


def _by_signal(records, signal):
    return [record for record in records if record.signal_type == signal]


def _shape(records):
    return [(record.entity_name, record.signal_type, record.value, record.metadata) for record in records]


@pytest.mark.parametrize("parser", sorted(_FIELDS))
def test_unedited_template_round_trips_through_the_normalizer(workdir, parser):
    item = create_import_template(parser)
    result = normalize_imported_evidence(item.file_path, parser, item.metadata["source_name"])
    assert result.import_job.status == "completed"
    assert result.records
    assert all(record.entity_name.startswith("PLACEHOLDER") for record in result.records)
    assert all(record.provenance["parser_type"] == parser for record in result.records)


def test_unedited_generic_template_is_not_silently_empty(workdir):
    # Previously the placeholder signal was unknown, so the importer dropped the row and still reported completed.
    item = create_import_template("generic_market_csv")
    result = normalize_imported_evidence(item.file_path, "generic_market_csv", item.metadata["source_name"])
    assert result.import_job.status == "completed"
    assert len(result.records) >= 1


def test_metadata_documents_the_provenance_the_importer_needs_and_manifest_bytes_are_unchanged(workdir):
    item = create_import_template("supplier_catalog_csv")
    assert item.metadata["import_provenance"] == dict(IMPORT_PROVENANCE)
    manifest = json.loads(Path(item.file_path).with_name("supplier_catalog_csv.manifest.json").read_text(encoding="utf-8"))
    assert "import_provenance" not in manifest


@pytest.mark.parametrize("parser", sorted(_FIELDS))
def test_unedited_template_stays_synthetic_when_imported_with_its_documented_provenance(workdir, parser):
    item = create_import_template(parser)
    result = normalize_imported_evidence(item.file_path, parser, item.metadata["source_name"], provenance=dict(item.metadata["import_provenance"]))
    assert result.import_job.status == "completed"
    assert result.source_quality.metadata["synthetic_or_cached_only"] is True
    assert result.source_quality.quality_score == 15.0
    assert all(record.source_type == "local_file" for record in result.records)
    assert all(record.provenance["parser_type"] == parser for record in result.records)


def test_filled_supplier_row_keeps_its_fields_and_stays_synthetic(workdir):
    path = _write_csv(workdir, "supplier_filled.csv", _canonical_columns("supplier_catalog_csv"), [SUPPLIER_ROW])
    result = normalize_imported_evidence(path, "supplier_catalog_csv", "synthetic_fixture", provenance=dict(IMPORT_PROVENANCE))
    assert result.import_job.status == "completed"
    margin = _by_signal(result.records, "margin_proxy")
    assert len(margin) == 1 and margin[0].value == 4.5
    assert margin[0].metadata == {"supplier_cost": 4.5, "shipping_cost": 1.25}
    supplier = _by_signal(result.records, "supplier_proxy")
    assert len(supplier) == 1 and supplier[0].value == 0.8
    assert supplier[0].metadata == {"supplier": "Synthetic Supplier A"}
    assert _by_signal(result.records, "risk_proxy") == []  # moq 50 and a 12-day lead time are under the parser's thresholds
    assert all(record.provenance["parser_type"] == "supplier_catalog_csv" for record in result.records)
    assert result.source_quality.metadata["synthetic_or_cached_only"] is True


def test_blank_supplier_cost_is_missing_and_explicit_zero_is_a_real_zero(workdir):
    rows = [
        {**SUPPLIER_ROW, "category": "Blank", "supplier_cost": "", "shipping_cost": ""},
        {**SUPPLIER_ROW, "category": "Zero", "supplier_cost": "0", "shipping_cost": "0"},
        {**SUPPLIER_ROW, "category": "Partial", "supplier_cost": "3", "shipping_cost": ""},
    ]
    path = _write_csv(workdir, "supplier_missing_zero.csv", _canonical_columns("supplier_catalog_csv"), rows)
    result = normalize_imported_evidence(path, "supplier_catalog_csv", "synthetic_fixture", provenance=dict(IMPORT_PROVENANCE))
    margin = {record.entity_name: record for record in _by_signal(result.records, "margin_proxy")}
    assert set(margin) == {"Zero", "Partial"}
    assert margin["Zero"].value == 0.0 and margin["Zero"].metadata == {"supplier_cost": 0.0, "shipping_cost": 0.0}
    assert margin["Partial"].value == 3.0 and margin["Partial"].metadata == {"supplier_cost": 3.0, "shipping_cost": None}


def test_reordered_and_unknown_columns_import_the_same_records(workdir):
    canonical = _canonical_columns("supplier_catalog_csv")
    plain = _write_csv(workdir, "plain.csv", canonical, [SUPPLIER_ROW])
    shuffled = _write_csv(
        workdir,
        "shuffled.csv",
        list(reversed(canonical)) + ["internal_notes"],
        [{**SUPPLIER_ROW, "internal_notes": "analyst scratch"}],
    )
    plain_result = normalize_imported_evidence(plain, "supplier_catalog_csv", "synthetic_fixture", provenance=dict(IMPORT_PROVENANCE))
    shuffled_result = normalize_imported_evidence(shuffled, "supplier_catalog_csv", "synthetic_fixture", provenance=dict(IMPORT_PROVENANCE))
    assert _shape(shuffled_result.records) == _shape(plain_result.records)
    assert "analyst scratch" not in json.dumps([record.to_dict() for record in shuffled_result.records], default=str)


def test_filled_google_trends_row_keeps_its_value(workdir):
    row = {"category": "Kitchen", "keyword": "synthetic kettle", "trend_score": "73", "growth": "12", "region": "XX", "timeframe": "synthetic"}
    path = _write_csv(workdir, "trends_filled.csv", _canonical_columns("google_trends_csv"), [row])
    result = normalize_imported_evidence(path, "google_trends_csv", "synthetic_fixture", provenance=dict(IMPORT_PROVENANCE))
    trend = _by_signal(result.records, "trend_proxy")
    assert len(trend) == 1 and trend[0].value == 73.0
    assert trend[0].provenance["parser_type"] == "google_trends_csv"


def test_same_filled_file_imports_to_identical_records(workdir):
    path = _write_csv(workdir, "supplier_repeat.csv", _canonical_columns("supplier_catalog_csv"), [SUPPLIER_ROW])
    first = normalize_imported_evidence(path, "supplier_catalog_csv", "synthetic_fixture", provenance=dict(IMPORT_PROVENANCE))
    second = normalize_imported_evidence(path, "supplier_catalog_csv", "synthetic_fixture", provenance=dict(IMPORT_PROVENANCE))
    assert [record.to_dict() for record in first.records] == [record.to_dict() for record in second.records]
