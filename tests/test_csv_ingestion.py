import csv
from pathlib import Path

import pytest

from backend.discovery.csv_ingestion import PARSERS, load_csv_rows


FIXTURES = Path(__file__).parent / "fixtures" / "evidence_imports"


def test_all_csv_parsers_are_deterministic_and_provenanced():
    for path in FIXTURES.glob("*.csv"):
        parser = path.stem.replace("_sample", "") + "_csv"
        if parser == "generic_market_csv": parser = "generic_market_csv"
        rows = load_csv_rows(str(path))
        records = PARSERS[parser](rows, {"source_name": parser, "type": "test"})
        assert records, parser
        assert all(record.provenance["parser_type"] == parser for record in records)
        assert all(record.provenance["row_number"] >= 2 for record in records)


def test_row_cap_and_utf8_sig(tmp_path, monkeypatch):
    import backend.discovery.csv_ingestion as ingestion
    monkeypatch.setattr(ingestion, "_project_root", lambda: tmp_path)
    path = tmp_path / "sample.csv"
    path.write_text("category,trend_score\n" + "x,0.5\n" * 3, encoding="utf-8-sig")
    assert len(load_csv_rows(str(path), 2)) == 2


def test_generic_import_omits_blank_value_and_preserves_explicit_zero():
    records = PARSERS["generic_market_csv"](
        [
            {
                "entity_type": "category",
                "entity_name": "Missing observation",
                "signal_type": "demand_proxy",
                "value": "  ",
            },
            {
                "entity_type": "category",
                "entity_name": "Observed zero",
                "signal_type": "demand_proxy",
                "value": "0",
            },
            {
                "entity_type": "pain_point",
                "entity_name": "Synthetic audience",
                "signal_type": "pain_point",
                "value": "A textual observation remains text",
            },
        ],
        {"source_name": "synthetic_manual_import", "evidence_class": "manual"},
    )

    assert [(record.entity_name, record.value) for record in records] == [
        ("Observed zero", 0.0),
        ("Synthetic audience", "A textual observation remains text"),
    ]
    assert all(record.provenance["source_name"] == "synthetic_manual_import" for record in records)


@pytest.mark.parametrize("raw_value", ["NaN", "Infinity", "-Infinity"])
def test_generic_import_omits_non_finite_numeric_observations(raw_value):
    records = PARSERS["generic_market_csv"](
        [
            {
                "entity_type": "category",
                "entity_name": "Synthetic category",
                "signal_type": "demand_proxy",
                "value": raw_value,
            }
        ],
        {"source_name": "synthetic_manual_import", "evidence_class": "manual"},
    )

    assert records == []


def test_generic_import_marks_non_finite_metadata_invalid_without_retaining_values():
    records = PARSERS["generic_market_csv"](
        [
            {
                "entity_type": "category",
                "entity_name": "Synthetic category",
                "signal_type": "demand_proxy",
                "value": "0",
                "metadata_json": '{"nested":{"ratio":NaN,"bounds":[Infinity,-Infinity]}}',
            }
        ],
        {"source_name": "synthetic_manual_import", "evidence_class": "manual"},
    )

    assert len(records) == 1
    assert records[0].value == 0.0
    assert records[0].metadata == {"metadata_json_invalid": True}


def test_generic_import_marks_overflowing_metadata_number_invalid():
    records = PARSERS["generic_market_csv"](
        [
            {
                "entity_type": "category",
                "entity_name": "Synthetic category",
                "signal_type": "demand_proxy",
                "value": "1",
                "metadata_json": '{"nested":{"ratio":1e9999}}',
            }
        ],
        {"source_name": "synthetic_manual_import", "evidence_class": "manual"},
    )

    assert len(records) == 1
    assert records[0].metadata == {"metadata_json_invalid": True}


def test_generic_import_marks_deeply_nested_metadata_invalid_without_dropping_value():
    from backend.discovery.csv_ingestion import MAX_METADATA_NESTING_DEPTH

    depth = MAX_METADATA_NESTING_DEPTH + 1
    records = PARSERS["generic_market_csv"](
        [
            {
                "entity_type": "category",
                "entity_name": "Synthetic category",
                "signal_type": "demand_proxy",
                "value": "3",
                "metadata_json": '{"nested":' * depth + "0" + "}" * depth,
            }
        ],
        {"source_name": "synthetic_manual_import", "evidence_class": "manual"},
    )

    assert len(records) == 1
    assert records[0].value == 3.0
    assert records[0].metadata == {"metadata_json_invalid": True}


@pytest.mark.parametrize("raw_metadata", ["[]", "null", "42", '"scalar"'])
def test_generic_import_marks_non_object_metadata_invalid(raw_metadata):
    records = PARSERS["generic_market_csv"](
        [
            {
                "entity_type": "category",
                "entity_name": "Synthetic category",
                "signal_type": "demand_proxy",
                "value": "1",
                "metadata_json": raw_metadata,
            }
        ],
        {"source_name": "synthetic_manual_import", "evidence_class": "manual"},
    )

    assert len(records) == 1
    assert records[0].metadata == {"metadata_json_invalid": True}


def test_generic_import_pipeline_preserves_value_and_manual_provenance(tmp_path, monkeypatch):
    import backend.discovery.csv_ingestion as ingestion
    from backend.discovery.evidence_normalizer import normalize_imported_evidence

    path = tmp_path / "synthetic.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["entity_type", "entity_name", "signal_type", "value", "metadata_json"],
        )
        writer.writeheader()
        writer.writerows(
            [
                {
                    "entity_type": "category",
                    "entity_name": "Missing observation",
                    "signal_type": "demand_proxy",
                    "value": " ",
                    "metadata_json": "{}",
                },
                {
                    "entity_type": "category",
                    "entity_name": "Observed zero",
                    "signal_type": "demand_proxy",
                    "value": "0",
                    "metadata_json": "{}",
                },
                {
                    "entity_type": "category",
                    "entity_name": "Invalid metadata",
                    "signal_type": "demand_proxy",
                    "value": "5",
                    "metadata_json": '{"nested":{"ratio":NaN}}',
                },
                {
                    "entity_type": "category",
                    "entity_name": "Invalid metadata shape",
                    "signal_type": "demand_proxy",
                    "value": "7",
                    "metadata_json": "[]",
                },
            ]
        )
    monkeypatch.setattr(ingestion, "_project_root", lambda: tmp_path)

    result = normalize_imported_evidence(
        str(path),
        "generic_market_csv",
        "synthetic_manual_import",
        workspace_id="workspace_synthetic",
        provenance={"evidence_class": "manual"},
    )

    records = {record.entity_name: record for record in result.records}
    assert set(records) == {
        "Observed zero",
        "Invalid metadata",
        "Invalid metadata shape",
    }
    assert records["Observed zero"].value == 0.0
    assert records["Invalid metadata"].value == 5.0
    assert records["Invalid metadata"].metadata == {"metadata_json_invalid": True}
    assert records["Invalid metadata shape"].value == 7.0
    assert records["Invalid metadata shape"].metadata == {"metadata_json_invalid": True}
    assert all(record.source_type == "local_file" for record in records.values())
    assert all(record.provenance["evidence_class"] == "manual" for record in records.values())
    assert result.import_job.status == "completed"
    assert result.import_job.records_imported == 3
